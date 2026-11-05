"""Regression coverage for ``check_openapi_operation_parameter_floor.py``.

The guard pins the published operation-parameter surface to a hand-written
literal. These cases prove each failure direction on real committed bytes,
and that the wiring and the literal cannot quietly rot. Collected by the
contracts layer's ``tests=()`` array; stdlib-only, no Python 3.15 needed.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import io
import json
import sys
from pathlib import Path

from named_guard_diagnostics import describe_assertion
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_openapi_operation_parameter_floor as guard  # noqa: E402

SMOKE = (ROOT / "scripts" / "smoke.sh").read_text(encoding="utf-8")
TARGET_PATH = "/api/v1/genes/region-structure"
TARGET_NAME = "release_id"
NEW_NAME = "release_id_v2"
TARGET_OID = "get_region_structure_api_v1_genes_region_structure_get"


def _document() -> dict:
    return json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))


def _co_revert() -> tuple[str, str]:
    """Rename one query parameter in both halves -- the decisive drift."""
    document = _document()
    generated = guard.GENERATED.read_text(encoding="utf-8")
    changed = 0
    for parameter in document["paths"][TARGET_PATH]["get"]["parameters"]:
        if parameter.get("name") == TARGET_NAME and parameter.get("in") == "query":
            parameter["name"] = NEW_NAME
            changed += 1
            break
    assert changed == 1
    key = f"    {TARGET_OID}: {{"
    start = generated.find(key)
    end = generated.find("\n    };", start)
    block = generated[start:end]
    old = f"{TARGET_NAME}?: number | null;"
    assert old in block
    drifted = (
        generated[:start]
        + block.replace(old, f"{NEW_NAME}?: number | null;", 1)
        + generated[end:]
    )
    assert drifted != generated
    return json.dumps(document, indent=2), drifted


def test_committed_tree_passes() -> None:
    found = guard.failures()
    assert not found, found


def test_coordinated_co_revert_is_rejected() -> None:
    """Both halves agree with each other; only the literal can catch it."""
    snapshot, generated = _co_revert()
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("drifted" in problem for problem in found), found
    assert not any("disagree" in problem for problem in found), found


def test_one_sided_snapshot_drift_is_rejected() -> None:
    snapshot, _ = _co_revert()
    found = guard.failures(snapshot=snapshot)
    assert any("disagree" in problem for problem in found), found


def test_one_sided_generated_drift_is_rejected() -> None:
    _, generated = _co_revert()
    found = guard.failures(generated=generated)
    assert any("disagree" in problem for problem in found), found


def test_requiredness_flip_is_rejected() -> None:
    document = _document()
    for parameter in document["paths"][TARGET_PATH]["get"]["parameters"]:
        if parameter.get("name") == TARGET_NAME and parameter.get("in") == "query":
            parameter["required"] = True
            break
    found = guard.failures(snapshot=json.dumps(document, indent=2))
    assert any("drifted" in problem for problem in found), found
    assert any("disagree" in problem for problem in found), found


def test_coordinated_parameter_drop_is_rejected() -> None:
    document = _document()
    op = document["paths"][TARGET_PATH]["get"]
    op["parameters"] = [p for p in op["parameters"] if p.get("name") != TARGET_NAME]
    generated = guard.GENERATED.read_text(encoding="utf-8").replace(
        f"                {TARGET_NAME}?: number | null;\n", "", 1
    )
    found = guard.failures(snapshot=json.dumps(document, indent=2), generated=generated)
    assert any("parameter count" in problem for problem in found), found
    assert any("drifted" in problem for problem in found), found


def test_hand_bumped_literals_are_not_enough() -> None:
    assert any("drifted" in f for f in guard.failures(digest="0" * 64))
    assert any("parameter count" in f for f in guard.failures(expected_count=999))
    assert any("operation count" in f for f in guard.failures(expected_operations=999))


def test_invalid_location_is_rejected() -> None:
    document = _document()
    for parameter in document["paths"][TARGET_PATH]["get"]["parameters"]:
        if parameter.get("name") == TARGET_NAME and parameter.get("in") == "query":
            parameter["in"] = "body"
            break
    found = guard.failures(snapshot=json.dumps(document, indent=2))
    assert any("invalid in" in problem for problem in found), found


def test_duplicate_parameter_is_rejected() -> None:
    document = _document()
    document["paths"][TARGET_PATH]["get"]["parameters"].append(
        {"name": TARGET_NAME, "in": "query", "required": False, "schema": {"type": "integer"}}
    )
    found = guard.failures(snapshot=json.dumps(document, indent=2))
    assert any("duplicate" in problem for problem in found), found


def test_the_fixed_point_is_a_hand_written_literal() -> None:
    """Re-deriving the digest from the artifacts would make the pin vacuous."""
    tree = ast.parse(Path(guard.__file__).read_text(encoding="utf-8"))
    assigned = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert "_PARAMETER_DIGEST" in assigned
    assert "_EXPECTED_PARAMETER_COUNT" in assigned
    document = _document()
    assert guard._digest(guard._snapshot_parameters(document)) == guard._PARAMETER_DIGEST
    assert len(guard._snapshot_parameters(document)) == guard._EXPECTED_PARAMETER_COUNT
    assert len(guard._snapshot_identity(document)) == guard._EXPECTED_OPERATION_COUNT


def test_wiring_cannot_be_dropped_silently() -> None:
    """The standalone --self-test call must exist in the contracts layer."""
    line = f'"${{PYTHON_BIN}}" scripts/{guard.SELF} --self-test || rc=$?'
    assert line in SMOKE, "guard is not wired into smoke_contracts()"
    assert any("does not invoke" in f for f in guard.failures(smoke=""))


def test_self_test_mutation_cases_all_pass() -> None:
    """The in-file ablations must stay load-bearing under collection."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = guard.self_test()
    assert rc == 0, buf.getvalue()
    out = buf.getvalue()
    emitted = [
        line
        for line in out.splitlines()
        if line.startswith("PASS self-test:") or line.startswith("FAIL self-test:")
    ]
    assert emitted, out
    reported = [
        int(line.split()[1])
        for line in out.splitlines()
        if line.startswith("self-test: ") and "cases" in line
    ]
    assert len(reported) == 1 and reported[0] == len(emitted), out


def test_the_co_revert_re_pin_pair_is_load_bearing() -> None:
    """Both limbs must live in the guard's self-test, from a second file.

    A coordinated retype of both artifacts is invisible to every consistency
    door; the only thing that can see it is the independent digest. So an
    un-re-pinned tree must be named and a same-commit re-pin must stay green.
    Pinning both here means a single-file edit cannot drop the evidence and
    its own assertion together.
    """
    source = Path(guard.__file__).read_text(encoding="utf-8")
    assert "with its digest re-pinned" in source
    assert "expect_clean=True" in source
    assert 'kwargs.pop("expect_clean", False)' in source
    # Behavioural: re-derive the re-pinned digest from the planted tree and
    # assert the guard says clean, while the same tree without the re-pin is
    # named as drift. Uses the guard's own helpers, not a second literal.
    snapshot, generated = _co_revert()
    document = json.loads(snapshot)
    rows = (
        guard._snapshot_map(document)
        if hasattr(guard, "_snapshot_map")
        else guard._snapshot_parameters(document)
    )
    fresh = guard.failures(snapshot=snapshot, generated=generated, digest=guard._digest(rows))
    assert not fresh, fresh
    stale = guard.failures(snapshot=snapshot, generated=generated)
    assert any("drifted" in problem for problem in stale), stale


def _run_all() -> int:
    cases = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    problems: list[str] = []
    for case in cases:
        try:
            case()
        except AssertionError as exc:
            problems.append(f"{case.__name__}: {describe_assertion(exc, case)}")
    if problems:
        for problem in problems:
            print(f"openapi-operation-parameter-floor-tests: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"openapi-operation-parameter-floor-tests: OK ({len(cases)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
