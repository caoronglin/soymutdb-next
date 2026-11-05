"""Pin the behavior contracts ``app.main`` publishes into the OpenAPI document.

``_build_openapi_schema`` injects four client-visible declarations that are
*not* part of FastAPI's automatic schema:

* ``x-idempotent`` on every ``GET``/``PUT``/``DELETE``;
* ``x-pagination`` from ``PAGINATION_CONTRACTS``;
* ``x-error-codes`` from ``error_code_catalog()``;
* a uniform ``500`` response, plus a documented ``429`` (with the
  ``Retry-After`` header the handler always sends) on the operations in
  ``RATE_LIMITED_OPERATIONS``.

Each is derived from a source constant or an injection loop in ``main.py``, so
deleting that source and regenerating both committed artifacts keeps
``check-contract.sh`` green: the export, the snapshot and the generated client
all agree with each other while the published contract silently loses a
declaration.  This is the same genus as PR #154 (declared 422 shape vs the
runtime envelope) and PR #155 (normalizer fixed point) -- equality of generated
products is not evidence that the source declares the truth.  The 422 guard
covers only 422; the snapshot guard covers key order and nested ``$defs``; the
error-code guards cover the catalog's contents.  None of them cover these
extensions or the 500/429 response shapes.

The expected sets are parsed from ``main.py`` with ``ast.literal_eval`` rather
than hardcoded, so a genuine new rate-limited or paginated operation stays
green when source and snapshot move together (positive controls below).  A
co-reverted "drop the injection" fails because the source declaration vanishes
or the snapshot's set stops matching it.

Run directly (stdlib only) or collect with pytest:
    python3 scripts/test_openapi_behavior_contracts.py
    pytest scripts/test_openapi_behavior_contracts.py -q
"""
from __future__ import annotations

import ast
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "packages/api-client/openapi.json"
GENERATED = ROOT / "packages/api-client/src/generated/openapi.d.ts"
MAIN = ROOT / "apps/api/app/main.py"
SMOKE = ROOT / "scripts/smoke.sh"
SELF = Path(__file__).name

METHODS = {"get", "put", "post", "patch", "delete", "options", "head", "trace"}
IDEMPOTENT_METHODS = {"GET", "PUT", "DELETE"}
ERROR_RESPONSE_REF = "#/components/schemas/ErrorResponse"

# The shape main.py injects for a documented 429.  The handler emits
# ``Retry-After`` for *every* RateLimitExceededError, so a declared 429 that
# omits the header advertises less than the runtime sends.
VALID_429 = {
    "description": "Rate limit exceeded; retry after the indicated number of seconds.",
    "headers": {
        "Retry-After": {
            "description": "Seconds until this login attempt may be retried.",
            "schema": {"type": "integer", "minimum": 1},
        }
    },
    "content": {"application/json": {"schema": {"$ref": ERROR_RESPONSE_REF}}},
}


def _operations(document: dict) -> set[tuple[str, str]]:
    """Operations that carry a responses object and therefore need contracts."""
    return {
        (path, method)
        for path, ops in document.get("paths", {}).items()
        for method, op in ops.items()
        if method in METHODS and isinstance(op, dict) and "responses" in op
    }


def _declared(document: dict, code: str) -> dict[tuple[str, str], dict]:
    """Map (path, method) -> the response object for a status code."""
    out: dict[tuple[str, str], dict] = {}
    for path, ops in document.get("paths", {}).items():
        for method, op in ops.items():
            if method not in METHODS or not isinstance(op, dict):
                continue
            response = op.get("responses", {}).get(code)
            if isinstance(response, dict):
                out[(path, method)] = response
    return out


def _source_constant(main: str, name: str):
    """literal_eval a module-level constant, failing closed when it is gone."""
    tree = ast.parse(main)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            return ast.literal_eval(node.value)
    raise ValueError(f"main.py no longer declares {name}")


def _json_ref(response: dict) -> str | None:
    schema = (
        response.get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )
    return schema.get("$ref") if isinstance(schema, dict) else None


def failures(document: dict, generated: str, main: str, smoke: str) -> list[str]:
    found: list[str] = []
    operations = _operations(document)
    if not operations:
        return ["openapi.json declares no operations at all"]

    # 1. x-idempotent: derived from the method, not from a hardcoded path list.
    for path, method in sorted(operations):
        op = document["paths"][path][method]
        want = method.upper() in IDEMPOTENT_METHODS
        got = op.get("x-idempotent") is True
        if want != got:
            state = "missing" if want else "forged"
            found.append(f"{method.upper()} {path} has a {state} x-idempotent flag")
    if '{"GET", "PUT", "DELETE"}' not in main:
        found.append("main.py no longer derives x-idempotent from the method set")

    # 2. x-pagination: the published map must equal PAGINATION_CONTRACTS.
    try:
        pagination = _source_constant(main, "PAGINATION_CONTRACTS")
    except (ValueError, SyntaxError) as exc:
        found.append(str(exc))
        pagination = None
    if pagination is not None:
        declared = {
            key: document["paths"][key[0]][key[1]]["x-pagination"]
            for key in operations
            if "x-pagination" in document["paths"][key[0]][key[1]]
        }
        for key, value in sorted(pagination.items()):
            if declared.get(key) != value:
                found.append(
                    f"{key[1].upper()} {key[0]} publishes x-pagination "
                    f"{declared.get(key)!r}, PAGINATION_CONTRACTS says {value!r}"
                )
        for key in sorted(set(declared) - set(pagination)):
            found.append(
                f"{key[1].upper()} {key[0]} publishes x-pagination with no "
                "PAGINATION_CONTRACTS entry"
            )

    # 3. Uniform 500: declared on every operation, with the runtime envelope.
    five_hundreds = _declared(document, "500")
    for key in sorted(operations - set(five_hundreds)):
        found.append(f"{key[1].upper()} {key[0]} declares no 500 response")
    for key, response in five_hundreds.items():
        if _json_ref(response) != ERROR_RESPONSE_REF:
            found.append(
                f"{key[1].upper()} {key[0]} declares 500 as {_json_ref(response)!r}, "
                "not the runtime's ErrorResponse envelope"
            )
    if not re.search(r'responses\.setdefault\(\s*"500"', main):
        found.append("main.py no longer declares the uniform 500 response")

    # 4. Documented 429: exactly RATE_LIMITED_OPERATIONS, each advertising the
    # Retry-After header the handler always sends.  The global limiter can
    # reject any request with 429; the contract deliberately documents only
    # these, so the set is pinned against drift in *both* directions.
    four_twenty_nines = _declared(document, "429")
    try:
        rate_limited = set(_source_constant(main, "RATE_LIMITED_OPERATIONS"))
    except (ValueError, SyntaxError) as exc:
        found.append(str(exc))
        rate_limited = None
    # A source + snapshot whole-set co-revert can empty both sides at once:
    # zero declared 429s equals an empty RATE_LIMITED_OPERATIONS, so every
    # set-equality check below is vacuously satisfied. Pin the injection site
    # and a non-empty constant so the set comparisons cannot pass on nothing.
    if not re.search(r'responses\.setdefault\(\s*"429"', main):
        found.append("main.py no longer declares the documented 429 response")
    if rate_limited is not None and not rate_limited:
        found.append("main.py declares an empty RATE_LIMITED_OPERATIONS")
    if rate_limited is not None:
        for key in sorted(rate_limited - set(four_twenty_nines)):
            found.append(
                f"{key[1].upper()} {key[0]} is in RATE_LIMITED_OPERATIONS but "
                "documents no 429"
            )
        for key in sorted(set(four_twenty_nines) - rate_limited):
            found.append(
                f"{key[1].upper()} {key[0]} documents a 429 with no "
                "RATE_LIMITED_OPERATIONS entry"
            )
    for key, response in four_twenty_nines.items():
        retry = response.get("headers", {}).get("Retry-After")
        retry_schema = retry.get("schema", {}) if isinstance(retry, dict) else {}
        if retry_schema.get("type") != "integer" or retry_schema.get("minimum") != 1:
            found.append(
                f"{key[1].upper()} {key[0]} 429 omits the Retry-After integer "
                "header the handler always sends"
            )
        if _json_ref(response) != ERROR_RESPONSE_REF:
            found.append(
                f"{key[1].upper()} {key[0]} declares 429 as {_json_ref(response)!r}, "
                "not the runtime's ErrorResponse envelope"
            )

    # 5. x-error-codes: present and sourced (its *contents* belong to the
    # dedicated error-code guards, not this one).
    codes = document.get("x-error-codes")
    if not isinstance(codes, dict) or not codes:
        found.append("openapi.json no longer publishes a non-empty x-error-codes catalog")
    if 'schema["x-error-codes"] = error_code_catalog()' not in main:
        found.append("main.py no longer publishes x-error-codes from the catalog")

    # 6. Both committed artifacts must still name the envelope component, so a
    # co-reverted deletion of it cannot hide behind their mutual agreement.
    if ERROR_RESPONSE_REF.rsplit("/", 1)[-1] not in document.get("components", {}).get(
        "schemas", {}
    ):
        found.append("openapi.json no longer defines ErrorResponse")
    if 'components["schemas"]["ErrorResponse"]' not in generated:
        found.append("generated client no longer names ErrorResponse")

    if f"scripts/{SELF}" not in smoke:
        found.append("contracts smoke layer no longer invokes the behavior-contracts guard")

    return found


def _load() -> tuple[dict, str, str, str]:
    return (
        json.loads(SNAPSHOT.read_text(encoding="utf-8")),
        GENERATED.read_text(encoding="utf-8"),
        MAIN.read_text(encoding="utf-8"),
        SMOKE.read_text(encoding="utf-8"),
    )


def _any(failures_list: list[str], needle: str) -> bool:
    return any(needle in f for f in failures_list)


def test_committed_tree_advertises_the_runtime_behavior_contracts() -> None:
    assert failures(*_load()) == []


def test_a_dropped_500_is_rejected() -> None:
    document, generated, main, smoke = _load()
    key = next(iter(_operations(document)))
    assert "500" in document["paths"][key[0]][key[1]]["responses"], "setup is not a control"
    del document["paths"][key[0]][key[1]]["responses"]["500"]
    assert _any(failures(document, generated, main, smoke), "declares no 500 response")


def test_a_framework_500_is_rejected() -> None:
    document, generated, main, smoke = _load()
    key = next(iter(_declared(document, "500")))
    document["paths"][key[0]][key[1]]["responses"]["500"]["content"][
        "application/json"
    ]["schema"]["$ref"] = "#/components/schemas/HTTPValidationError"
    assert _any(failures(document, generated, main, smoke), "not the runtime's ErrorResponse")


def test_a_429_without_retry_after_is_rejected() -> None:
    document, generated, main, smoke = _load()
    key = next(iter(_declared(document, "429")))
    response = document["paths"][key[0]][key[1]]["responses"]["429"]
    assert "Retry-After" in response.get("headers", {}), "setup is not a control"
    del response["headers"]["Retry-After"]
    assert _any(failures(document, generated, main, smoke), "omits the Retry-After")


def test_a_phantom_429_is_rejected() -> None:
    document, generated, main, smoke = _load()
    key = next(
        k for k in sorted(_operations(document)) if k != ("/api/v1/auth/login", "post")
    )
    document["paths"][key[0]][key[1]]["responses"]["429"] = copy.deepcopy(VALID_429)
    assert _any(failures(document, generated, main, smoke), "no RATE_LIMITED_OPERATIONS entry")


def test_a_missing_documented_429_is_rejected() -> None:
    document, generated, main, smoke = _load()
    responses = document["paths"]["/api/v1/auth/login"]["post"]["responses"]
    assert "429" in responses, "committed tree already regressed; setup is not a control"
    del responses["429"]
    assert _any(failures(document, generated, main, smoke), "documents no 429")


def test_a_dropped_idempotence_flag_is_rejected() -> None:
    document, generated, main, smoke = _load()
    key = next(k for k in sorted(_operations(document)) if k[1].upper() in IDEMPOTENT_METHODS)
    op = document["paths"][key[0]][key[1]]
    assert "x-idempotent" in op, "committed tree already regressed; setup is not a control"
    del op["x-idempotent"]
    assert _any(failures(document, generated, main, smoke), "missing x-idempotent")


def test_a_forged_idempotence_flag_on_post_is_rejected() -> None:
    document, generated, main, smoke = _load()
    key = next(k for k in sorted(_operations(document)) if k[1] == "post")
    assert "x-idempotent" not in document["paths"][key[0]][key[1]], "setup is not a control"
    document["paths"][key[0]][key[1]]["x-idempotent"] = True
    assert _any(failures(document, generated, main, smoke), "forged x-idempotent")


def test_a_reshaped_pagination_contract_is_rejected() -> None:
    document, generated, main, smoke = _load()
    key = ("/api/v1/homologs/search", "get")
    assert "x-pagination" in document["paths"][key[0]][key[1]], "setup is not a control"
    document["paths"][key[0]][key[1]]["x-pagination"]["cursor_is_exclusive"] = False
    assert _any(failures(document, generated, main, smoke), "PAGINATION_CONTRACTS says")


def test_a_dropped_pagination_contract_is_rejected() -> None:
    document, generated, main, smoke = _load()
    op = document["paths"]["/api/v1/homologs/search"]["get"]
    assert "x-pagination" in op, "committed tree already regressed; setup is not a control"
    del op["x-pagination"]
    assert _any(failures(document, generated, main, smoke), "PAGINATION_CONTRACTS says")


def test_a_phantom_pagination_contract_is_rejected() -> None:
    document, generated, main, smoke = _load()
    key = next(
        k for k in sorted(_operations(document)) if k != ("/api/v1/homologs/search", "get")
    )
    document["paths"][key[0]][key[1]]["x-pagination"] = {"mode": "keyset"}
    assert _any(failures(document, generated, main, smoke), "no PAGINATION_CONTRACTS entry")


def test_a_dropped_error_code_catalog_is_rejected() -> None:
    document, generated, main, smoke = _load()
    document.pop("x-error-codes", None)
    assert _any(failures(document, generated, main, smoke), "non-empty x-error-codes")


def test_dropping_the_500_injection_is_rejected() -> None:
    document, generated, main, smoke = _load()
    dropped = re.sub(r'responses\.setdefault\(\s*"500"', 'responses.setdefault("501"', main, count=1)
    assert dropped != main
    assert _any(failures(document, generated, dropped, smoke), "no longer declares the uniform 500")


def test_dropping_the_429_constant_is_rejected() -> None:
    document, generated, main, smoke = _load()
    dropped = main.replace(
        'RATE_LIMITED_OPERATIONS = {("/api/v1/auth/login", "post")}', "", 1
    )
    assert dropped != main
    assert _any(failures(document, generated, dropped, smoke), "no longer declares RATE_LIMITED_OPERATIONS")


def test_a_whole_set_429_co_revert_is_rejected() -> None:
    """Source + snapshot emptied together must fail, not pass vacuously."""
    document, generated, main, smoke = _load()
    committed = _declared(document, "429")
    assert committed, "committed tree already declares no 429; setup is not a control"
    for path, ops in document["paths"].items():
        for method, op in ops.items():
            if isinstance(op, dict) and "responses" in op:
                op["responses"].pop("429", None)
    emptied = re.sub(
        r"RATE_LIMITED_OPERATIONS = \{[^}]*\}",
        "RATE_LIMITED_OPERATIONS = set()",
        main,
        count=1,
    )
    assert emptied != main, "whole-set co-revert already applied to the committed tree; setup is not a control"
    # The control is "the snapshot used to declare 429s and now declares none in
    # the operations this test rewrote", not "the substring 429 vanished from
    # the document": the x-error-codes map legitimately spells 429 as a value.
    remaining = _declared(document, "429")
    assert not remaining.keys() & committed.keys(), (
        "whole-set co-revert left a declared 429 behind; setup is not a control"
    )
    assert _any(
        failures(document, generated, emptied, smoke),
        "empty RATE_LIMITED_OPERATIONS",
    )


def test_dropping_the_error_code_publication_is_rejected() -> None:
    document, generated, main, smoke = _load()
    dropped = main.replace(
        'schema["x-error-codes"] = error_code_catalog()', "", 1
    )
    assert dropped != main
    assert _any(failures(document, generated, dropped, smoke), "no longer publishes x-error-codes")


def test_dropping_smoke_wiring_is_rejected() -> None:
    document, generated, main, smoke = _load()
    unwired = smoke.replace(f"    scripts/{SELF}\n", "", 1)
    assert unwired != smoke
    assert _any(failures(document, generated, main, unwired), "no longer invokes the behavior-contracts guard")


def test_a_genuinely_new_rate_limited_operation_stays_green() -> None:
    """No hardcoded 429 whitelist: source + snapshot moving together is fine."""
    document, generated, main, smoke = _load()
    key = next(
        k for k in sorted(_operations(document)) if k != ("/api/v1/auth/login", "post")
    )
    augmented = main.replace(
        'RATE_LIMITED_OPERATIONS = {("/api/v1/auth/login", "post")}',
        'RATE_LIMITED_OPERATIONS = {("/api/v1/auth/login", "post"), '
        f'("{key[0]}", "{key[1]}")}}',
        1,
    )
    assert augmented != main
    document["paths"][key[0]][key[1]]["responses"]["429"] = copy.deepcopy(VALID_429)
    # Only the 429 contract is under test here; other, unrelated drift in the
    # tree must not be able to turn this positive control into a false alarm.
    assert not _any(
        failures(document, generated, augmented, smoke),
        "no RATE_LIMITED_OPERATIONS entry",
    )


def test_a_genuinely_new_pagination_contract_stays_green() -> None:
    """No hardcoded pagination whitelist: a real new contract stays green."""
    document, generated, main, smoke = _load()
    key = next(
        k for k in sorted(_operations(document)) if k != ("/api/v1/homologs/search", "get")
    )
    needle = "PAGINATION_CONTRACTS: dict[tuple[str, str], dict[str, str | bool]] = {\n"
    augmented = main.replace(
        needle, needle + f'    ("{key[0]}", "{key[1]}"): {{"mode": "keyset"}},\n', 1
    )
    assert augmented != main
    document["paths"][key[0]][key[1]]["x-pagination"] = {"mode": "keyset"}
    # Only the pagination contract is under test here (see the 429 control).
    assert not _any(
        failures(document, generated, augmented, smoke),
        "no PAGINATION_CONTRACTS entry",
    )


def _whole_set_co_revert() -> bool:
    """Whether the committed tree lost an entire declared response set.

    A source + artifact co-revert empties both sides at once, so the setup
    assertions of the sampling checks fail for a shared reason rather than
    reporting new defects. Say so once instead of making each reader infer it.
    """
    found = failures(*_load())
    return any(
        "no longer declares the documented 429" in f
        or "empty RATE_LIMITED_OPERATIONS" in f
        or "declares no 500 response" in f
        for f in found
    )


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
        except (AssertionError, StopIteration) as exc:
            # A whole-set co-revert empties the setup data some checks sample;
            # report it as a failed check instead of escaping as a traceback.
            problems.append(f"{test.__name__}: {exc or 'assertion failed'}")
    if problems:
        if _whole_set_co_revert():
            print(
                "openapi-behavior-contracts: whole-set co-revert detected "
                "(a declared response set or its source constant was emptied); "
                "the FAILs below are its side effects, not new defects",
                file=sys.stderr,
            )
        for problem in problems:
            print(f"openapi-behavior-contracts: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"openapi-behavior-contracts: OK ({len(tests)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
