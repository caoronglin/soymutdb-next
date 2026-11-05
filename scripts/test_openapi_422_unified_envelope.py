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
  client that drops, retypes or one-sidedly adds one cannot hide behind the
  JSON half;
* the declared error-response distribution is pinned to an exact baseline, so
  a *coordinated* edit to both artifacts (drop OR add) is also caught;
* the builder overrides rather than ``setdefault``s the 422, still registers
  all four handlers, and still declares both schemas;
* the guard is wired into ``smoke.sh --profile contracts``.

The equality check is self-referential: ``expected`` is recomputed from
whichever JSON is supplied, so a snapshot and client edited together still
agree. ``_ERROR_RESPONSE_BASELINE`` is independent of both halves and is the
fixed point that closes that blind spot -- the same idiom as the snapshot
guard's ``_SNAPSHOT_FLOOR``, but exact in both directions because an error
status the runtime never sends is as wrong as a dropped one. It pins the
*declared surface*, not the set of operations: adding an endpoint legitimately
adds its 422/500, so the baseline must be updated in that same commit with a
reason.

Each branch is mutation-tested in-file. Run directly or collect with pytest:
    python3 scripts/test_openapi_422_unified_envelope.py
    pytest scripts/test_openapi_422_unified_envelope.py -q
"""
from __future__ import annotations

import json
import subprocess
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
# these (rather than looking for a banned string) is what makes a dropped or
# retyped body visible even when the JSON half was reverted with it. A body
# ADDED to both halves keeps expected == actual; the baseline below catches it.
VALIDATION_BODY = '"application/json": components["schemas"]["ValidationErrorResponse"];'
ENVELOPE_BODY = '"application/json": components["schemas"]["ErrorResponse"];'

# Exact declared error-response surface (code -> number of operations declaring
# it), measured on the live snapshot: 266 operations x {422, 500}, plus 3 x 409
# and 1 x 429. This is an independent fixed point, NOT derived from the supplied
# document. Equality of expected-vs-actual cannot see a coordinated edit to
# both artifacts -- a dropped 500 or an invented 418 added on both sides -- so
# the distribution itself is pinned. Update it in the same commit as an
# intentional change to the error surface and say why.
#
# 266 -> 268 (PR #71, downloads provenance): `POST /api/v1/exports/query` and
# `GET /api/v1/variants/export/{id}/manifest` each declare both a 422 and a
# 500, and both now advertise the runtime `ValidationErrorResponse` envelope
# rather than FastAPI's `HTTPValidationError`. 409 and 429 are unchanged.
_ERROR_RESPONSE_BASELINE = {"409": 3, "422": 268, "429": 1, "500": 268}


def _error_code_counts(document: dict) -> dict[str, int]:
    """How many operations declare each 4xx/5xx status."""
    counts: dict[str, int] = {}
    for path, ops in document.get("paths", {}).items():
        for method, op in ops.items():
            if method not in METHODS or not isinstance(op, dict):
                continue
            for code in op.get("responses", {}):
                if code.startswith("4") or code.startswith("5"):
                    counts[code] = counts.get(code, 0) + 1
    return counts


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
    # each shape as the snapshot declares. A retyped or dropped body breaks the
    # equality even when both artifacts were reverted together. A body ADDED to
    # both keeps the equality, so the independent baseline is checked too.
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

    declared = _error_code_counts(document)
    if declared != _ERROR_RESPONSE_BASELINE:
        found.append(
            f"snapshot declares error responses {dict(sorted(declared.items()))}, "
            f"not the pinned {dict(sorted(_ERROR_RESPONSE_BASELINE.items()))}: a "
            "coordinated edit to both artifacts cannot be seen by comparing "
            "them to each other"
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
    assert not (found := failures(*_load())), found


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


def test_a_coordinated_added_error_response_is_rejected() -> None:
    """The blind spot: adding a 418 to BOTH halves keeps expected == actual."""
    document, generated, main_src, smoke = _load()
    key = next(iter(_operations(document)))
    responses = document["paths"][key[0]][key[1]]["responses"]
    responses["418"] = json.loads(json.dumps(responses["500"]))
    injected = generated.replace(
        ENVELOPE_BODY, ENVELOPE_BODY + "\n" + ENVELOPE_BODY, 1
    )
    assert injected != generated
    found = failures(document, injected, main_src, smoke)
    assert any("not the pinned" in f for f in found), found


def test_a_coordinated_dropped_error_response_is_rejected() -> None:
    """Dropping a 500 from BOTH halves is caught by the baseline too."""
    document, generated, main_src, smoke = _load()
    key = next(iter(_operations(document)))
    del document["paths"][key[0]][key[1]]["responses"]["500"]
    stripped = generated.replace(ENVELOPE_BODY, "", 1)
    assert stripped != generated
    found = failures(document, stripped, main_src, smoke)
    assert any("not the pinned" in f for f in found), found


def test_a_one_sided_added_error_response_is_rejected() -> None:
    """A 418 declared in JSON only breaks both the equality and the baseline."""
    document, generated, main_src, smoke = _load()
    key = next(iter(_operations(document)))
    responses = document["paths"][key[0]][key[1]]["responses"]
    responses["418"] = json.loads(json.dumps(responses["500"]))
    found = failures(document, generated, main_src, smoke)
    assert any("response body(s); snapshot declares" in f for f in found), found
    assert any("not the pinned" in f for f in found), found

# ---------------------------------------------------------------------------
# Reachable-cause contract for the stdlib guard runners
#
# A guard that fails is only half a gate: it must also say *why*. Two byte
# shapes used to silence every one of these OpenAPI guards on a real drift:
#
#   * ``assert failures(...) == []`` -- a bare assert raises
#     ``AssertionError()`` whose ``args == ()`` and ``str`` is ``''``. The
#     ``failures()`` result (the actual reason) is discarded completely; it is
#     NOT recoverable from ``e.args[0]``.
#   * ``f"...: {exc or 'assertion failed'}"`` -- ``bool(AssertionError())`` is
#     True (exceptions define no ``__bool__``/``__len__``), so the fallback is
#     dead and ``f"{exc}"`` prints ``str(exc) == ''``. The line ends in a colon
#     and a space: ``FAIL: test_x:``.
#
# ``named_guard_diagnostics.describe_assertion`` is the shared renderer and
# ``assert not (found := failures(...)), found`` is the shared attach shape.
# Both are pinned tree-wide one layer up, by
# ``scripts/test_named_guard_diagnostics.py``. What this file adds is the third
# leg those scanners cannot see: when the guarded *artifact* really drifts, the
# runner's own ``FAIL:`` line must carry the reason. The scan checks alone
# would stay green on a runner whose message is always ``''``.
# ---------------------------------------------------------------------------

_DRIFT_HOST = "scripts/test_openapi_snapshot_body_integrity.py"
_HARNESSED_CASE = "test_committed_tree_has_matching_response_bodies"
_DRIFT_INPUTS = (
    _DRIFT_HOST,
    "packages/api-client/openapi.json",
    "packages/api-client/src/generated/openapi.d.ts",
    "scripts/named_guard_diagnostics.py",
    "scripts/smoke.sh",
)


def _copy_drift_tree(tmp: str) -> Path:
    """Copy the guard and its inputs into ``tmp``; never mutate the worktree."""
    import shutil

    tree = Path(tmp)
    for rel in _DRIFT_INPUTS:
        dest = tree / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
    return tree


def _run_drift_tree(tree: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(tree / _DRIFT_HOST)],
        cwd=tree,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _reason_of(line: str) -> str:
    """Everything the runner printed after ``FAIL: <case>: ``."""
    tail = line.split("FAIL:", 1)[-1]
    case_name = tail.split(":", 1)[0]
    if not case_name.startswith(" test_"):
        return tail.strip()
    return tail.split(":", 1)[-1].strip()


def _repin_everything_the_drift_moves(tree: Path) -> None:
    """Update every legitimately-moved literal in the copy's harnessed guard.

    Two rounds: the first repin changes the host's own bytes, which the blob
    pins cover; the second pins the blobs as they now are. After this the
    artifact pin and the pair digest are both satisfied and the *pairing* check
    is the only one left with something to say.
    """
    import hashlib
    import importlib.util
    import re

    host = tree / _DRIFT_HOST

    def load() -> object:
        spec = importlib.util.spec_from_file_location("drifted_guard", host)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    for _ in range(2):
        module = load()
        document = module._load()[0]
        digest = module._body_pair_digest(document)
        source = host.read_text(encoding="utf-8")
        source = re.sub(
            r'_BODY_PAIR_DIGEST = "[0-9a-f]+"',
            f'_BODY_PAIR_DIGEST = "{digest}"',
            source,
            count=1,
        )
        for name, relative in (
            ("snapshot_blob", "packages/api-client/openapi.json"),
            ("generated_blob", "packages/api-client/src/generated/openapi.d.ts"),
        ):
            data = (tree / relative).read_bytes()
            blob = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
            source = re.sub(
                rf'"{name}": "[0-9a-f]+"',
                f'"{name}": "{blob}"',
                source,
                count=1,
            )
        host.write_text(source, encoding="utf-8")


def _drift_the_client_half(tree: Path) -> None:
    """Retype one 200 in *both* halves, then re-pin what the drift moves.

    Retyping only the client trips the pinned-artifact digests first, and that
    failure is built by ``_baseline_moved_with_the_artifacts`` -- a function
    that composes its own reason, so it stays readable even with the runner
    silenced. Re-pinning leaves the *pairing* as the only thing wrong, which is
    the case whose sole assertion is the bare ``assert not found, found``.
    """
    import json

    snapshot = tree / "packages/api-client/openapi.json"
    generated = tree / "packages/api-client/src/generated/openapi.d.ts"

    document = json.loads(snapshot.read_text(encoding="utf-8"))
    operation = document["paths"]["/api/v1/auth/login"]["post"]
    operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] = (
        "#/components/schemas/ErrorResponse"
    )
    snapshot.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    client = generated.read_text(encoding="utf-8")
    assert 'components["schemas"]["TokenResponse"]' in client, "client anchor is gone"
    generated.write_text(
        client.replace(
            'components["schemas"]["TokenResponse"]',
            'components["schemas"]["ErrorResponse"]',
            1,
        ),
        encoding="utf-8",
    )
    _repin_everything_the_drift_moves(tree)


def _drift_the_snapshot_half(tree: Path) -> None:
    """Drop one ``GeneDetail`` declaration from the copy's snapshot."""
    snapshot = tree / "packages/api-client/openapi.json"
    source = snapshot.read_text(encoding="utf-8")
    assert '"GeneDetail"' in source, "drift fixture anchor is gone"
    snapshot.write_text(
        source.replace('"GeneDetail"', '"GeneListResponse"', 1), encoding="utf-8"
    )


_DRIFTS: tuple[tuple[str, object], ...] = (
    ("client-half retype", _drift_the_client_half),
    ("snapshot-half declaration drop", _drift_the_snapshot_half),
)


def test_the_guard_runner_copies_cleanly_before_drift() -> None:
    """The copy is a real control: unmodified bytes must still pass."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        clean = _run_drift_tree(_copy_drift_tree(tmp))
    assert clean.returncode == 0, clean.stderr


def test_a_drift_report_names_its_reason() -> None:
    """A real drift must fail with a cause on *every* ``FAIL:`` line.

    Not just the harnessed case: a runner that loses its renderer keeps the
    cause of any case that attached one (``assert not found, found``) and
    prints nothing for every case that did not. Both legs are real; the pin
    covers the line that has nothing going for it. Verified against the
    historical shape: swapping the runner to ``f"{exc}"`` leaves the harnessed
    line named and two others empty.
    """
    import tempfile

    for label, drift_the_tree in _DRIFTS:
        with tempfile.TemporaryDirectory() as tmp:
            tree = _copy_drift_tree(tmp)
            drift_the_tree(tree)
            drift = _run_drift_tree(tree)

        assert drift.returncode == 1, (label, drift.returncode, drift.stderr)
        lines = [line for line in drift.stderr.splitlines() if "FAIL:" in line]
        assert lines, f"{label} produced no FAIL line: {drift.stderr!r}"
        unreachable = [line for line in lines if not _reason_of(line)]
        assert not unreachable, (
            f"{label}: {len(unreachable)} of {len(lines)} FAIL lines lost their "
            f"cause: {unreachable!r}"
        )


def _silent_fixture(tree: Path) -> None:
    """Point one harnessed case at a failure whose cause never reaches the line.

    Two edits, both in the copy: the harnessed case is rebound to a bare
    ``assert not found`` (the ``failures()`` reason is discarded, the set up
    display below keeps the *contract* red), and the runner's final renderer is
    stubbed to ``""`` so the ``describe_assertion`` fallback cannot name the
    precondition either. The package is self-contained, and its own suite is
    pinned by ``test_named_guard_diagnostics`` -- stubbing both is exactly what
    a careless edit would do.
    """
    host = tree / _DRIFT_HOST
    source = host.read_text(encoding="utf-8")
    anchor = "def test_committed_tree_has_matching_response_bodies() -> None:\n"
    assert anchor in source, "drift host lost the case this pin harnesses"
    silent_case = (
        anchor
        + "    found = failures(*_load())\n"
        + "    assert not found\n"
        + "    del found\n"
        + "\n\n"
    )
    source = source.replace(anchor, silent_case, 1)
    # Spelled from parts on purpose: ``_report_line`` searches this very file
    # for the literal reporting line, and a verbatim copy here would be the
    # first match -- the scanner would then read this helper instead of the
    # real runner and go green on the wrong bytes.
    head = "problems.append("
    label = 'f"{test.__name__}: '
    renderer = head + label + "{str(exc) or 'assertion failed'}" + '")'
    silent = head + label + "{exc}" + '")'

    assert renderer in source, "drift host lost the runner this pin harnesses"
    host.write_text(source.replace(renderer, silent, 1), encoding="utf-8")


def test_the_drift_pin_can_go_red() -> None:
    """The pin above must not be a tautology: a lost cause has to turn it red.

    Drift the tree as usual, then flatten the harnessed case *and* the renderer
    in the copy. The contract is still red, the ``FAIL:`` line is still
    printed, and the part after the case name is empty. The pin's own judgement
    over that line must therefore be falsey -- which is what its assertion
    rejects. If it stayed green here it would be a gate with no teeth.

    Deliberately not done by swapping the real runner to ``f"{exc}"``: the
    harnessed case attaches its cause, so that mutant keeps this line named and
    only silences the two permutation cases, which
    ``test_a_drift_report_names_its_reason`` catches instead.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tree = _copy_drift_tree(tmp)
        _drift_the_client_half(tree)
        _silent_fixture(tree)
        silent = _run_drift_tree(tree)

    assert silent.returncode == 1, (silent.returncode, silent.stderr)
    harnessed = [
        line
        for line in silent.stderr.splitlines()
        if "FAIL:" in line and _HARNESSED_CASE in line
    ]
    assert harnessed, f"the silent case never failed: {silent.stderr!r}"
    reasons = [_reason_of(line) for line in harnessed]
    assert any(not reason for reason in reasons), (
        f"a case that dropped its cause still parsed as named: {harnessed!r}"
    )
    try:
        for reason in reasons:
            assert reason, "empty failure message"
    except AssertionError:
        pass
    else:
        raise AssertionError(f"the pin stayed green on a lost cause: {harnessed!r}")


def test_the_reason_parser_separates_the_case_name() -> None:
    """The drift assertion above is only as good as this parse."""
    named = (
        "openapi-snapshot-bodies: FAIL: test_committed_tree: "
        "['the baseline literals were recorded']"
    )
    assert _reason_of(named) == "['the baseline literals were recorded']"
    silent = "openapi-snapshot-bodies: FAIL: test_committed_tree: "
    assert not _reason_of(silent), "an empty cause parsed as a reason"
    bare = "openapi-snapshot-bodies: FAIL: something else entirely"
    assert _reason_of(bare) == "something else entirely"



# ---------------------------------------------------------------------------
# Failure-message contract (PR #176 continued)
#
# A guard that fails is only half a gate: it must also say *why*. Two byte
# shapes used to make every one of these OpenAPI guards go silent on a real
# drift:
#
#   * ``assert failures(...) == []`` -- a bare assert raises
#     ``AssertionError()`` whose ``args == ()`` and ``str`` is ``''``. The
#     ``failures()`` result (the actual reason) is discarded completely; it is
#     NOT recoverable from ``e.args[0]``.
#   * ``f"...: {exc or 'assertion failed'}"`` -- ``bool(AssertionError())`` is
#     True (exceptions define no ``__bool__``/``__len__``), so the fallback is
#     dead and ``f"{exc}"`` prints ``str(exc) == ''``. The line ends in a
#     colon and a space: ``FAIL: test_x:``.
#
# #176 fixed the runner of THIS file (``str(exc)``). This suite pins the whole
# surface: every bare ``== []`` assert replaced by a message-bearing form, and
# every remaining in-file runner using ``str(exc)``.
# ---------------------------------------------------------------------------

# Every in-file runner that catches AssertionError and formats it. All eight
# must convert ``exc`` with ``str`` before applying the fallback.
_RUNNERS: tuple[str, ...] = (
    "scripts/check_openapi_inline_body_integrity.py",
    "scripts/test_contracts_layer_self_containment.py",
    "scripts/test_openapi_422_unified_envelope.py",
    "scripts/test_openapi_baseline_sync.py",
    "scripts/test_openapi_behavior_contracts.py",
    "scripts/test_openapi_operation_id_floor.py",
    "scripts/test_openapi_snapshot_body_integrity.py",
    "scripts/test_openapi_snapshot_contract.py",
)

# This file's own source contains the defective byte shapes inside docstrings
# and ablation fixtures. Exclude it from the "committed tree" scans; its runner
# is still checked by ``test_every_runner_uses_str_on_the_exception`` through
# the live ``_str_fallback_count`` call below.
_SELF = Path(__file__).name


def _sources() -> dict[str, str]:
    return {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in _RUNNERS}


def _bare_assert_count(source: str) -> int:
    """Count ``assert <call> == []`` lines that carry no message."""
    import ast

    count = 0
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assert) or node.msg is not None:
            continue
        if not isinstance(node.test, ast.Compare):
            continue
        left = node.test.left
        if not isinstance(left, ast.Call):
            continue
        func = left.func
        if isinstance(func, ast.Name) and func.id == "failures":
            count += 1
    return count


def _report_line(source: str) -> str | None:
    """The real ``problems.append`` reporting line of an in-file runner."""
    import re

    match = re.search(
        r'problems\.append\(f"\{test\.__name__\}: [^"]*exc[^"]*"\)|'
        r'problems\.append\(f"\{case\.__name__\}: [^"]*exc[^"]*"\)',
        source,
    )
    return match.group(0) if match else None


def _dead_fallback_count(source: str) -> int:
    """Count reporting lines that format the exception object directly."""
    line = _report_line(source)
    return 1 if line and "{str(exc)" not in line and "{exc " in line else 0


def _str_fallback_count(source: str) -> int:
    """Count reporting lines that convert the exception with ``str``."""
    line = _report_line(source)
    return 1 if line and "{str(exc)" in line else 0


def test_no_bare_failure_asserts_remain() -> None:
    """The committed tree must not discard any ``failures()`` reason."""
    sources = _sources()
    offenders = [
        rel for rel, src in sources.items()
        if rel != _SELF and _bare_assert_count(src)
    ]
    assert not offenders, f"bare assert failures(...) == [] still present: {offenders}"


def test_no_dead_assertion_fallback_remains() -> None:
    """No runner may format the exception object directly."""
    sources = _sources()
    offenders = [
        rel for rel, src in sources.items()
        if rel != _SELF and _dead_fallback_count(src)
    ]
    assert not offenders, f"dead 'exc or' fallback still present: {offenders}"


def test_every_runner_uses_str_on_the_exception() -> None:
    """All eight in-file runners must make their fallback reachable."""
    sources = _sources()
    missing = [
        rel for rel, src in sources.items() if not _str_fallback_count(src)
    ]
    assert not missing, f"runner missing str(exc) fallback: {missing}"
    # The live source of this runner itself must carry exactly one reachable
    # fallback and zero dead ones (its own docstring/ablations aside).
    live = (ROOT / "scripts" / _SELF).read_text(encoding="utf-8")
    assert _str_fallback_count(live) == 1, "this runner lost its str(exc) fallback"
    assert _dead_fallback_count(live) == 0, "this runner regressed to exc or"


def test_a_bare_assert_is_caught() -> None:
    """Reintroducing one bare assert must turn the pin red."""
    sources = _sources()
    host = "scripts/test_openapi_422_unified_envelope.py"
    mutant = sources[host].replace(
        "assert not (found := failures(*_load())), found",
        "assert failures(*_load()) == []",
        1,
    )
    assert mutant != sources[host]
    assert _bare_assert_count(mutant) == 1


def test_a_dead_fallback_is_caught() -> None:
    """Reintroducing the ``exc or`` object fallback must turn the pin red."""
    sources = _sources()
    host = "scripts/test_openapi_422_unified_envelope.py"
    line = _report_line(sources[host])
    assert line is not None
    dead = line.replace("{str(exc) or 'assertion failed'}", "{exc or 'assertion failed'}")
    mutant = sources[host].replace(line, dead, 1)
    assert mutant != sources[host]
    assert _dead_fallback_count(mutant) == 1


def test_a_drift_report_is_not_empty() -> None:
    """A real drift must produce a non-empty failure message.

    Copy the guard and its three inputs into a temporary tree, inject a
    ``GeneDetail -> GeneListResponse`` retype there, and assert the runner's
    ``FAIL:`` line carries the reason. The working tree is never mutated.
    """
    import shutil
    import subprocess
    import tempfile

    guard = "scripts/test_openapi_snapshot_body_integrity.py"
    inputs = (
        guard,
        "packages/api-client/openapi.json",
        "packages/api-client/src/generated/openapi.d.ts",
        "scripts/smoke.sh",
    )
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp)
        for rel in inputs:
            dest = tree / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, dest)
        cmd = [sys.executable, str(tree / guard)]

        clean = subprocess.run(
            cmd, cwd=tree, capture_output=True, text=True, timeout=180, check=False
        )
        assert clean.returncode == 0, clean.stderr

        generated = tree / "packages/api-client/src/generated/openapi.d.ts"
        original = generated.read_text(encoding="utf-8")
        assert "GeneDetail" in original
        generated.write_text(
            original.replace("GeneDetail", "GeneListResponse", 1), encoding="utf-8"
        )
        drift = subprocess.run(
            cmd, cwd=tree, capture_output=True, text=True, timeout=180, check=False
        )

    assert drift.returncode == 1
    lines = [ln for ln in drift.stderr.splitlines() if "FAIL:" in ln]
    assert lines, "drift produced no FAIL line"
    for line in lines:
        reason = line.split("FAIL:", 1)[1].split(": ", 1)[-1].strip()
        assert reason, f"empty failure message: {line!r}"


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
            problems.append(f"{test.__name__}: {str(exc) or 'assertion failed'}")
    if problems:
        for problem in problems:
            print(f"openapi-error-envelope: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"openapi-error-envelope: OK ({len(tests)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
