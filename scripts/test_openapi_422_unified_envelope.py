"""Every documented 422 must describe the body the runtime actually sends.

``app.main`` registers ``validation_exception_handler`` for every
``RequestValidationError`` and never uses FastAPI's default handler.  That
handler always returns the unified error envelope -- ``ValidationErrorResponse``
-- with the sanitised, field-level ``errors`` array.  ``HTTPValidationError``
(the flat ``detail`` list) is a shape this server does not emit for 422.

``_build_openapi_schema`` used ``responses.setdefault("422", ...)`` for the
unified schema.  ``get_openapi`` populates the auto 422 first, so setdefault
was a no-op on 235 of 266 operations: ``openapi.json`` and the generated
``openapi.d.ts`` typed 422 as ``HTTPValidationError`` for those operations.
A consumer writing error handling against the generated client wrote a branch
for a shape that never arrives and no branch for ``errors``.  The two committed
artifacts agreed with each other perfectly -- which is exactly why a byte-diff
gate cannot see this class of defect.  This guard reads the committed bytes and
asserts the *source* contract: the declared 422 schema matches the handler.

Also pins the knob itself: the builder must override (not ``setdefault``) the
auto 422, and the exception handler must still be registered.  Both are
mutation-tested so a guard that passes vacuously fails.

Run directly (stdlib only) or collect with pytest:
    python3 scripts/test_openapi_422_unified_envelope.py
    pytest scripts/test_openapi_422_unified_envelope.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "packages/api-client/openapi.json"
GENERATED = ROOT / "packages/api-client/src/generated/openapi.d.ts"
MAIN = ROOT / "apps/api/app/main.py"

UNIFIED = "#/components/schemas/ValidationErrorResponse"
FRAMEWORK = "#/components/schemas/HTTPValidationError"
SMOKE = ROOT / "scripts/smoke.sh"
SELF = Path(__file__).name


def _declared_422_refs(document: dict) -> dict[tuple[str, str], str]:
    """Map (path, method) -> the 422 response's JSON schema $ref, if any."""
    out: dict[tuple[str, str], str] = {}
    for path, ops in document.get("paths", {}).items():
        for method, op in ops.items():
            if not isinstance(op, dict):
                continue
            resp = op.get("responses", {}).get("422")
            if not isinstance(resp, dict):
                continue
            schema = (
                resp.get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            ref = schema.get("$ref") if isinstance(schema, dict) else None
            if ref is not None:
                out[(path, method)] = ref
    return out


def _operations(document: dict) -> set[tuple[str, str]]:
    """Every operation that carries a responses object must declare a 422."""
    out: set[tuple[str, str]] = set()
    methods = {"get", "put", "post", "patch", "delete", "options", "head", "trace"}
    for path, ops in document.get("paths", {}).items():
        for method, op in ops.items():
            if method in methods and isinstance(op, dict) and "responses" in op:
                out.add((path, method))
    return out


def failures(document: dict, generated: str, main: str, smoke: str) -> list[str]:
    found: list[str] = []
    refs = _declared_422_refs(document)

    if not refs:
        found.append("no operation declares a 422 response schema at all")

    missing = _operations(document) - set(refs)
    for path, method in sorted(missing):
        found.append(f"{method.upper()} {path} declares no 422 response schema")

    for key, ref in refs.items():
        if ref != UNIFIED:
            found.append(
                f"{key[1].upper()} {key[0]} declares 422 as {ref}, not the "
                "runtime's ValidationErrorResponse envelope"
            )

    # The generated TypeScript client must name the same schema, so a
    # co-reverted snapshot + client pair cannot hide behind each other.
    if 'components["schemas"]["HTTPValidationError"]' in generated:
        # Only the schema *definition* may still carry the name; every 422
        # response body must reference the unified envelope.  Count references
        # inside response bodies by structural position is what the json side
        # already proves; here we require the framework name is not used as a
        # response content type anywhere it used to be.
        body_refs = generated.count(
            '"application/json": components["schemas"]["HTTPValidationError"];'
        )
        if body_refs:
            found.append(
                f"generated client still types {body_refs} 422 response(s) as "
                "HTTPValidationError"
            )
    if 'components["schemas"]["ValidationErrorResponse"]' not in generated:
        found.append("generated client no longer names ValidationErrorResponse")

    # The builder must override the auto 422, not defer to it.
    if 'setdefault(\n                "422"' in main or 'setdefault("422"' in main:
        found.append("main.py still uses setdefault for the 422 response")
    if "add_exception_handler(RequestValidationError, validation_exception_handler)" not in main:
        found.append("main.py no longer registers validation_exception_handler")
    if "ValidationErrorResponse" not in main:
        found.append("main.py no longer references ValidationErrorResponse")
    # The declared schema must actually be defined in the document, or the
    # generated client names a component that does not exist.
    if UNIFIED.split("/")[-1] not in document.get("components", {}).get("schemas", {}):
        found.append("openapi.json no longer defines ValidationErrorResponse")

    if f"scripts/{SELF}" not in smoke:
        found.append("contracts smoke layer no longer invokes the 422 guard")

    return found


def _load() -> tuple[dict, str, str, str]:
    return (
        json.loads(SNAPSHOT.read_text(encoding="utf-8")),
        GENERATED.read_text(encoding="utf-8"),
        MAIN.read_text(encoding="utf-8"),
        SMOKE.read_text(encoding="utf-8"),
    )


def test_committed_tree_advertises_the_runtime_422_envelope() -> None:
    assert failures(*_load()) == []


def test_a_framework_422_is_rejected() -> None:
    document, generated, main, smoke = _load()
    # Plant one real regression: revert a single operation's 422 to the
    # framework shape the runtime never sends.
    key = next(iter(_declared_422_refs(document)))
    document["paths"][key[0]][key[1]]["responses"]["422"]["content"][
        "application/json"
    ]["schema"]["$ref"] = FRAMEWORK
    assert any("not the runtime's ValidationErrorResponse" in f
               for f in failures(document, generated, main, smoke))


def test_a_stale_generated_client_is_rejected() -> None:
    document, generated, main, smoke = _load()
    stale = generated.replace(
        '"application/json": components["schemas"]["ValidationErrorResponse"];',
        '"application/json": components["schemas"]["HTTPValidationError"];',
        1,
    )
    assert stale != generated
    assert any("generated client still types" in f
               for f in failures(document, stale, main, smoke))


def test_setdefault_regression_is_rejected() -> None:
    document, generated, main, smoke = _load()
    regressed = main.replace(
        'current_422.setdefault("description", "Validation Error")',
        'responses.setdefault("422", {"description": "Validation Error"})',
        1,
    )
    assert regressed != main
    assert any("still uses setdefault" in f
               for f in failures(document, generated, regressed, smoke))


def test_dropping_the_handler_registration_is_rejected() -> None:
    document, generated, main, smoke = _load()
    dropped = main.replace(
        "app.add_exception_handler(RequestValidationError, validation_exception_handler)",
        "",
        1,
    )
    assert dropped != main
    assert any("no longer registers validation_exception_handler" in f
               for f in failures(document, generated, dropped, smoke))


def test_deleting_the_unified_schema_is_rejected() -> None:
    document, generated, main, smoke = _load()
    document["components"]["schemas"].pop("ValidationErrorResponse", None)
    assert any("no longer defines ValidationErrorResponse" in f
               for f in failures(document, generated, main, smoke))


def test_dropping_smoke_wiring_is_rejected() -> None:
    document, generated, main, smoke = _load()
    unwired = smoke.replace(f"    scripts/{SELF}\n", "", 1)
    assert unwired != smoke
    assert any("no longer invokes the 422 guard" in f
               for f in failures(document, generated, main, unwired))


def test_missing_422_response_is_rejected() -> None:
    document, generated, main, smoke = _load()
    key = next(iter(_declared_422_refs(document)))
    del document["paths"][key[0]][key[1]]["responses"]["422"]
    # A single dropped 422 among hundreds must be caught; a guard that only
    # checks "at least one ref exists" would stay green.
    assert any(f"{key[1].upper()} {key[0]} declares no 422" in f
               for f in failures(document, generated, main, smoke))


def main() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    problems: list[str] = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            problems.append(f"{test.__name__}: {exc or 'assertion failed'}")
    if problems:
        for problem in problems:
            print(f"openapi-422-unified-envelope: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"openapi-422-unified-envelope: OK ({len(tests)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
