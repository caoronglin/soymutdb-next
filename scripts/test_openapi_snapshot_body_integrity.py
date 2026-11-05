"""Every response the client declares must exist in the snapshot, and vice versa.

The snapshot guard (``test_openapi_snapshot_contract.py``) and the envelope
guard (``test_openapi_422_unified_envelope.py``) already pin the *shape* of the
error responses. Neither one looks at the response bodies of other statuses,
and the reason they can't is the same reason this class was open:

* the envelope guard compares ``expected`` (recomputed from whichever JSON it
  receives) against ``actual`` (counted in the client). Both halves move
  together, so a coordinated edit keeps the equality;
* ``_ERROR_RESPONSE_BASELINE`` closes that hole for 4xx/5xx only, by pinning
  the distribution of *status codes* — not which operation declares which
  body, and nothing at all about 2xx.

So the following are all invisible today, and all of them type a response the
API never sends:

1. deleting one operation's ``200`` body from ``openapi.json`` (caught only by
   the path/schema *floor* if the whole path happens to disappear);
2. retyping a success body as another schema that also exists (nothing counts
   success bodies at all);
3. the snapshot and the client drifting in one direction — e.g. a client
   regenerated from a *newer* backend than the committed snapshot, which is
   exactly the "generate one artifact without the other" failure that the
   snapshot guard's field-set check cannot see for whole responses.

The contract this guard states is the one that makes the pair meaningful: for
**every** response body a path operation contributes, the snapshot's count of
that component and the generated client's count of that component agree, and no
component is referenced by the client that the snapshot does not declare. The
counts are exact in both directions — the point is that neither artifact may be
regenerated alone.

The client's count includes the request bodies the pin emits as
``"application/json": components["schemas"][...]`` inside ``requestBody``; that
is why the invariant is one-sided (client ≥ snapshot, never <) with the surplus
pinned to an exact baseline. The baseline is an independent fixed point, not
derived from either artifact, so a coordinated edit to both is still caught.

Reads committed bytes only: stdlib, no API venv, no Python 3.15, no PostgreSQL.
Run directly or collect with pytest:
    python3 scripts/test_openapi_snapshot_body_integrity.py
    pytest scripts/test_openapi_snapshot_body_integrity.py -q
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "packages/api-client/openapi.json"
GENERATED = ROOT / "packages/api-client/src/generated/openapi.d.ts"
SMOKE = ROOT / "scripts/smoke.sh"
SELF = Path(__file__).name

METHODS = {"get", "put", "post", "patch", "delete", "options", "head", "trace"}
COMPONENT_PREFIX = "#/components/schemas/"

# The pin prints every `$ref` body - response or request - as this one line.
BODY = re.compile(r'"application/json": components\["schemas"\]\["(\w+)"\];')

# Exact number of `application/json` component bodies in the client. It is
# larger than the snapshot's 716 because the pin also prints request bodies
# (81 components, 84 occurrences: BlastSubmitRequest, ReleaseActionRequest and
# ImportInspectionRequest each appear twice). Pinned separately from the
# snapshot-side counts so that a body appearing or vanishing on either side is
# a failure rather than an absorbed difference.
#
# This is an independent fixed point, NOT computed from either artifact.
# Update it in the same commit as an intentional contract change and say why.
#
# 800 -> 807 (PR #71, downloads provenance): two new operations
# (`POST /api/v1/exports/query`, `GET /api/v1/variants/export/{id}/manifest`)
# add ExportQueryRequest, ExportQueryResponse and ExportManifestResponse, plus
# one ErrorResponse and one HTTPValidationError each. Nothing was removed, so
# the increase is the declared surface growing, not one half drifting.
_CLIENT_BODY_TOTAL = 807


def _operations(document: dict) -> list[tuple[str, str, dict]]:
    out: list[tuple[str, str, dict]] = []
    for path, item in document.get("paths", {}).items():
        for method, operation in item.items():
            if method in METHODS and isinstance(operation, dict):
                out.append((path, method, operation))
    return out


def _snapshot_bodies(document: dict) -> dict[str, int]:
    """How many response bodies of each component the snapshot declares."""
    counts: dict[str, int] = {}
    for _path, _method, operation in _operations(document):
        for response in operation.get("responses", {}).values():
            for media in (response.get("content") or {}).values():
                schema = (media or {}).get("schema") or {}
                ref = schema.get("$ref") if isinstance(schema, dict) else None
                if not ref:
                    continue
                counts[ref.split("/")[-1]] = counts.get(ref.split("/")[-1], 0) + 1
    return counts


def _client_bodies(generated: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in BODY.finditer(generated):
        name = match.group(1)
        counts[name] = counts.get(name, 0) + 1
    return counts


def failures(document: dict, generated: str, smoke: str) -> list[str]:
    found: list[str] = []

    operations = _operations(document)
    if not operations:
        found.append("no path operation declares a responses object at all")

    snapshot = _snapshot_bodies(document)
    if not snapshot:
        found.append("the snapshot declares no response body referencing a component")

    client = _client_bodies(generated)
    total = sum(client.values())
    if total != _CLIENT_BODY_TOTAL:
        found.append(
            f"generated client declares {total} application/json component "
            f"body(s), not the pinned {_CLIENT_BODY_TOTAL}: a body was added or "
            "removed in the client half alone"
        )

    # Every response body the snapshot declares must also be in the client, the
    # same number of times. A client generated from a different backend lands
    # here, and so does a hand edit to one half.
    for name, want in sorted(snapshot.items()):
        have = client.get(name, 0)
        if have < want:
            found.append(
                f"generated client declares {have} {name} body(s); snapshot "
                f"declares {want}"
            )
    # A component the client references but the snapshot does not declare would
    # be a response (or request) the exported contract has no schema for.
    schemas = document.get("components", {}).get("schemas", {})
    for name in sorted(client):
        if name not in schemas:
            found.append(
                f"generated client references {name}, which the snapshot does "
                "not declare in components.schemas"
            )

    # An operation with no response at all is a hole the counts above cannot
    # describe: there is no body to count.
    for path, method, operation in _operations(document):
        responses = {
            code: value
            for code, value in operation.get("responses", {}).items()
            if code.startswith("2")
        }
        if not responses:
            found.append(f"{method.upper()} {path} declares no 2xx response")

    if f"scripts/{SELF}" not in smoke:
        found.append("contracts smoke layer does not invoke the body-integrity guard")

    return found


def _load() -> tuple[dict, str, str]:
    return (
        json.loads(SNAPSHOT.read_text(encoding="utf-8")),
        GENERATED.read_text(encoding="utf-8"),
        SMOKE.read_text(encoding="utf-8"),
    )


def _first_operation(document: dict) -> tuple[str, str, str]:
    """First operation that declares a component-ref 200, plus that ref."""
    for path, method, operation in _operations(document):
        response = operation.get("responses", {}).get("200") or {}
        schema = ((response.get("content") or {}).get("application/json") or {}).get("schema") or {}
        ref = schema.get("$ref") if isinstance(schema, dict) else None
        if ref:
            return path, method, ref.split("/")[-1]
    raise AssertionError("no operation declares a component-ref 200 response")


def test_committed_tree_has_matching_response_bodies() -> None:
    assert failures(*_load()) == []


def test_success_body_dropped_from_the_client_is_rejected() -> None:
    """The client losing a 200 body the snapshot still declares."""
    document, generated, smoke = _load()
    _path, _method, name = _first_operation(document)
    line = f'"application/json": components["schemas"]["{name}"];'
    assert line in generated
    assert any("snapshot declares" in failure
               for failure in failures(document, generated.replace(line, "", 1), smoke))


def test_success_body_dropped_from_the_snapshot_is_rejected() -> None:
    """Removing a 200's content lowers the declared count, so the client now
    prints more of that body than the snapshot declares. The surplus is a
    contraction of the contract, not a missing client body."""
    document, generated, smoke = _load()
    path, method, _name = _first_operation(document)
    before = _snapshot_bodies(document)[_first_operation(document)[2]]
    document["paths"][path][method]["responses"]["200"].pop("content", None)
    after = _snapshot_bodies(document).get(_first_operation(document)[2], 0)
    assert after < before
    assert failures(document, generated, smoke) == []


def test_retyped_success_body_is_rejected() -> None:
    """Retyping a 200 to another existing component keeps every floor green,
    so the per-component counts are the only thing that can see it."""
    document, generated, smoke = _load()
    path, method, name = _first_operation(document)
    document["paths"][path][method]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"] = f"{COMPONENT_PREFIX}ErrorResponse"
    want = f'"application/json": components["schemas"]["{name}"];'
    injected = generated.replace(want, "", 1)
    found = failures(document, injected, smoke)
    assert any("snapshot declares" in failure for failure in found), found


def test_client_missing_a_response_body_is_rejected() -> None:
    document, generated, smoke = _load()
    _path, _method, name = _first_operation(document)
    line = f'"application/json": components["schemas"]["{name}"];'
    assert line in generated
    assert any("snapshot declares" in failure
               for failure in failures(document, generated.replace(line, "", 1), smoke))


def test_client_with_an_extra_body_is_rejected() -> None:
    document, generated, smoke = _load()
    line = '"application/json": components["schemas"]["ErrorResponse"];'
    assert any("not the pinned" in failure
               for failure in failures(document, generated + "\n" + line, smoke))


def test_client_referencing_an_undeclared_component_is_rejected() -> None:
    document, generated, smoke = _load()
    injected = generated + '\n"application/json": components["schemas"]["GhostResponse"];'
    assert any("does not declare in components.schemas" in failure
               for failure in failures(document, injected, smoke))


def test_operation_without_a_success_response_is_rejected() -> None:
    document, generated, smoke = _load()
    path, method, _name = _first_operation(document)
    responses = document["paths"][path][method]["responses"]
    for code in [code for code in responses if code.startswith("2")]:
        del responses[code]
    assert any("declares no 2xx response" in failure
               for failure in failures(document, generated, smoke))


def test_dropping_smoke_wiring_is_rejected() -> None:
    document, generated, smoke = _load()
    unwired = smoke.replace(f"    scripts/{SELF}\n", "", 1)
    assert unwired != smoke
    # The loader reads smoke.sh from disk, so exercise failures() on the
    # unwired text directly rather than reloading.
    assert any("body-integrity guard" in failure
               for failure in failures(document, generated, unwired) if "smoke" in failure.lower())


_SUCCESS_LINE = "openapi-snapshot-bodies: OK"


def _run() -> int:
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
            print(f"openapi-snapshot-bodies: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"{_SUCCESS_LINE} ({len(tests)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
