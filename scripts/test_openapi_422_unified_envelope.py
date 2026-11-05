"""Every documented error response must describe the body the runtime sends.

``app.main`` registers four exception handlers. Every one emits the same
unified envelope (``ErrorResponse``), except the 422 handler, which emits
``ValidationErrorResponse`` (the same envelope plus a field-level ``errors``
array). FastAPI's default ``HTTPValidationError`` (a flat ``detail`` list) is
never emitted for 422.

``_build_openapi_schema`` used ``responses.setdefault("422", ...)`` for the
unified schema. ``get_openapi`` populates the auto 422 first, so setdefault
was a no-op on 235 of 266 operations: ``openapi.json`` and the generated
``openapi.d.ts`` typed 422 as ``HTTPValidationError`` for those operations.
PR #154 fixed that and added this guard -- but the guard only looked for the
*framework* shape by name in the generated client. Three regressions stayed
green against it (all reproduced on the live tree before this change):

1. retyping one 422 body in ``openapi.d.ts`` as ``ErrorResponse`` (a shape the
   server never sends for 422, but not the one name the guard banned);
2. deleting a single operation's ``500`` response from the snapshot;
3. retyping one ``500`` response as ``HTTPValidationError``.

In every case the two committed artifacts agreed with each other, so a byte
diff gate could not see it either. Equality of two generated products is
not evidence that either one declares the truth.

This guard closes the class instead of the one spelling. It reads committed
bytes only (stdlib, no API venv, no 3.15, no PostgreSQL) and asserts:

* every operation declares a 422 and a 500, each with the exact runtime schema;
* every other declared 4xx/5xx response uses ``ErrorResponse``;
* the generated client contains exactly as many ``ErrorResponse`` and
  ``ValidationErrorResponse`` response bodies as the snapshot declares, so a
  client that drops, adds or retypes one cannot hide behind the JSON half;
* the builder overrides rather than ``setdefault``s the 422, still registers
  all four handlers, and still declares both schemas;
* the guard is wired into ``smoke.sh --profile contracts``.

Each branch is mutation-tested in-file. Run directly or collect with pytest:
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
SMOKE = ROOT / "scripts/smoke.sh"
SELF = Path(__file__).name

VALIDATION = "#/components/schemas/ValidationErrorResponse"
ENVELOPE = "#/components/schemas/ErrorResponse"
FRAMEWORK = "#/components/schemas/HTTPValidationError"
METHODS = {"get", "put", "post", "patch", "delete", "options", "head", "trace"}

# Exact response-body spellings the pinned openapi-typescript emits. Counting
# these (rather than looking for a banned string) is what makes a dropped,
# added or retyped body visible even when the JSON half was reverted with it.
VALIDATION_BODY = '"application/json": components["schemas"]["ValidationErrorResponse"];'
ENVELOPE_BODY = '"application/json": components["schemas"]["ErrorResponse"];'


def _operations(document: dict) -> set[tuple[str, str]]:
    """Every operation that carries a responses object."""
    out: set[tuple[str, str]] = set()
    for path, ops in document.get("paths", {}).items():
        for method, op in ops.items():
            if method in METHODS and isinstance(op, dict) and "responses" in op:
                out.add((path, method))
    return out


def _response_ref(response: object) -> str | None:
    if not isinstance(response, dict):
        return None
    schema = (
        response.get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )
    return schema.get("$ref") if isinstance(schema, dict) else None


def _expected_bodies(document: dict) -> dict[str, int]:
    """How many response bodies of each runtime shape the snapshot declares."""
    expected = {ENVELOPE: 0, VALIDATION: 0}
    for path, ops in document.get("paths", {}).items():
        for method, op in ops.items():
            if method not in METHODS or not isinstance(op, dict):
                continue
            for code, response in op.get("responses", {}).items():
                if not (code.startswith("4") or code.startswith("5")):
                    continue
                ref = _response_ref(response)
                if ref in expected:
                    expected[ref] += 1
    return expected


def failures(document: dict, generated: str, main: str, smoke: str) -> list[str]:
    found: list[str] = []
    operations = _operations(document)

    if not operations:
        found.append("no operation declares a responses object at all")

    for path, method in sorted(operations):
        responses = document["paths"][path][method]["responses"]
        label = f"{method.upper()} {path}"

        declared_422 = responses.get("422")
        if declared_422 is None:
            found.append(f"{label} declares no 422 response")
        elif _response_ref(declared_422) != VALIDATION:
            found.append(
                f"{label} declares 422 as {_response_ref(declared_422)!r}, not "
                "the runtime's ValidationErrorResponse envelope"
            )

        declared_500 = responses.get("500")
        if declared_500 is None:
            found.append(f"{label} declares no 500 response")
        elif _response_ref(declared_500) != ENVELOPE:
            found.append(
                f"{label} declares 500 as {_response_ref(declared_500)!r}, not "
                "the runtime's ErrorResponse envelope"
            )

        for code, response in responses.items():
            if code in ("422", "500") or not (
                code.startswith("4") or code.startswith("5")
            ):
                continue
            ref = _response_ref(response)
            if ref != ENVELOPE:
                found.append(
                    f"{label} declares {code} as {ref!r}, not the runtime's "
                    "ErrorResponse envelope"
                )

    # The generated TypeScript client must contain exactly as many bodies of
    # each shape as the snapshot declares. A single retyped, dropped or added
    # body changes the count, so a co-reverted snapshot + client pair cannot
    # hide behind each other and neither can a shape the guard never named.
    expected = _expected_bodies(document)
    actual = {
        ENVELOPE: generated.count(ENVELOPE_BODY),
        VALIDATION: generated.count(VALIDATION_BODY),
    }
    for ref, want in expected.items():
        if actual[ref] != want:
            found.append(
                f"generated client declares {actual[ref]} "
                f"{ref.split('/')[-1]} response body(s); snapshot declares {want}"
            )
    framework_body = (
        '"application/json": components["schemas"]["HTTPValidationError"];'
    )
    if framework_body in generated:
        found.append("generated client still types a response body as HTTPValidationError")
    for ref in (VALIDATION, ENVELOPE):
        if f'components["schemas"]["{ref.split("/")[-1]}"]' not in generated:
            found.append(f"generated client no longer names {ref.split('/')[-1]}")

    # Source-side pins: the builder must override (not defer to) the auto 422,
    # all four handlers must stay registered, and both declared schemas must
    # actually be defined in the document.
    if 'setdefault("422"' in main:
        found.append("main.py still uses setdefault for the 422 response")
    for handler in (
        "SoyMutDBError, soy_mut_db_exception_handler",
        "HTTPException, http_exception_handler",
        "RequestValidationError, validation_exception_handler",
        "Exception, unhandled_exception_handler",
    ):
        if f"add_exception_handler({handler})" not in main:
            found.append(f"main.py no longer registers {handler}")
    if "ValidationErrorResponse" not in main or "ErrorResponse" not in main:
        found.append("main.py no longer references both error schemas")
    schemas = document.get("components", {}).get("schemas", {})
    for ref in (VALIDATION, ENVELOPE):
        if ref.split("/")[-1] not in schemas:
            found.append(f"openapi.json no longer defines {ref.split('/')[-1]}")

    if f"scripts/{SELF}" not in smoke:
        found.append("contracts smoke layer no longer invokes the error-envelope guard")

    return found


def _load() -> tuple[dict, str, str, str]:
    return (
        json.loads(SNAPSHOT.read_text(encoding="utf-8")),
        GENERATED.read_text(encoding="utf-8"),
        MAIN.read_text(encoding="utf-8"),
        SMOKE.read_text(encoding="utf-8"),
    )


def test_committed_tree_advertises_the_runtime_error_envelopes() -> None:
    assert failures(*_load()) == []


def test_a_framework_422_is_rejected() -> None:
    document, generated, main, smoke = _load()
    key = next(iter(_operations(document)))
    document["paths"][key[0]][key[1]]["responses"]["422"]["content"][
        "application/json"
    ]["schema"]["$ref"] = FRAMEWORK
    assert any("not the runtime's ValidationErrorResponse" in f
               for f in failures(document, generated, main, smoke))


def test_a_wrong_422_shape_is_rejected() -> None:
    """The guard must ban *any* non-runtime shape, not one banned name."""
    document, generated, main, smoke = _load()
    key = next(iter(_operations(document)))
    document["paths"][key[0]][key[1]]["responses"]["422"]["content"][
        "application/json"
    ]["schema"]["$ref"] = ENVELOPE
    assert any("not the runtime's ValidationErrorResponse" in f
               for f in failures(document, generated, main, smoke))


def test_a_stale_generated_client_is_rejected() -> None:
    document, generated, main, smoke = _load()
    stale = generated.replace(VALIDATION_BODY, ENVELOPE_BODY, 1)
    assert stale != generated
    assert any("response body(s); snapshot declares" in f
               for f in failures(document, stale, main, smoke))


def test_a_dropped_500_response_is_rejected() -> None:
    """A single dropped 500 among 266 must be caught by the JSON half alone."""
    document, generated, main, smoke = _load()
    key = next(iter(_operations(document)))
    del document["paths"][key[0]][key[1]]["responses"]["500"]
    assert any("declares no 500 response" in f
               for f in failures(document, generated, main, smoke))


def test_a_retyped_500_response_is_rejected() -> None:
    document, generated, main, smoke = _load()
    key = next(iter(_operations(document)))
    document["paths"][key[0]][key[1]]["responses"]["500"]["content"][
        "application/json"
    ]["schema"]["$ref"] = FRAMEWORK
    assert any("not the runtime's ErrorResponse envelope" in f
               for f in failures(document, generated, main, smoke))


def test_a_nonunified_409_response_is_rejected() -> None:
    document, generated, main, smoke = _load()
    key = next(
        (p, m)
        for p, ops in document["paths"].items()
        for m, op in ops.items()
        if isinstance(op, dict) and "409" in op.get("responses", {})
    )
    document["paths"][key[0]][key[1]]["responses"]["409"]["content"][
        "application/json"
    ]["schema"]["$ref"] = FRAMEWORK
    assert any("declares 409 as" in f
               for f in failures(document, generated, main, smoke))


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


def test_dropping_any_handler_registration_is_rejected() -> None:
    document, generated, main, smoke = _load()
    dropped = main.replace(
        "app.add_exception_handler(HTTPException, http_exception_handler)",
        "",
        1,
    )
    assert dropped != main
    assert any("no longer registers HTTPException" in f
               for f in failures(document, generated, dropped, smoke))


def test_deleting_either_schema_is_rejected() -> None:
    document, generated, main, smoke = _load()
    document["components"]["schemas"].pop("ErrorResponse", None)
    assert any("no longer defines ErrorResponse" in f
               for f in failures(document, generated, main, smoke))


def test_dropping_smoke_wiring_is_rejected() -> None:
    document, generated, main, smoke = _load()
    unwired = smoke.replace(f"    scripts/{SELF}\n", "", 1)
    assert unwired != smoke
    assert any("no longer invokes the error-envelope guard" in f
               for f in failures(document, generated, main, unwired))


def test_missing_422_response_is_rejected() -> None:
    document, generated, main, smoke = _load()
    key = next(iter(_operations(document)))
    del document["paths"][key[0]][key[1]]["responses"]["422"]
    assert any("declares no 422" in f
               for f in failures(document, generated, main, smoke))


def test_a_client_with_an_extra_error_body_is_rejected() -> None:
    document, generated, main, smoke = _load()
    injected = generated.replace(
        ENVELOPE_BODY, ENVELOPE_BODY + "\n" + ENVELOPE_BODY, 1
    )
    assert injected != generated
    assert any("response body(s); snapshot declares" in f
               for f in failures(document, injected, main, smoke))


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
            print(f"openapi-error-envelope: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"openapi-error-envelope: OK ({len(tests)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
