"""Regression coverage for ``scripts/check_openapi_operation_id_floor.py``.

The guard pins the published ``operationId`` surface to a hand-written
literal. These cases prove each failure direction on real committed bytes,
and that the wiring and the literal cannot quietly rot. Collected by the
contracts layer's ``tests=()`` array; stdlib-only, no Python 3.15 needed.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_openapi_operation_id_floor as guard  # noqa: E402

SMOKE = (ROOT / "scripts" / "smoke.sh").read_text(encoding="utf-8")


def _co_revert() -> tuple[str, str]:
    """Retype one operationId in both halves -- the decisive drift."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    generated = guard.GENERATED.read_text(encoding="utf-8")
    old = "liveness_api_v1_health_live_get"
    changed = 0
    for item in document["paths"].values():
        for method, operation in item.items():
            if method in guard.METHODS and isinstance(operation, dict):
                if operation.get("operationId") == old:
                    operation["operationId"] = old + "_v2"
                    changed += 1
    assert changed == 1
    drifted = generated.replace(
        f'operations["{old}"]', f'operations["{old}_v2"]', 1
    ).replace(f"    {old}: {{", f"    {old}_v2: {{", 1)
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
    assert any("does not" not in problem for problem in found), found


def test_one_sided_snapshot_drift_is_rejected() -> None:
    import copy

    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    old = "liveness_api_v1_health_live_get"
    doc = copy.deepcopy(document)
    for item in doc["paths"].values():
        for method, operation in item.items():
            if method in guard.METHODS and isinstance(operation, dict):
                if operation.get("operationId") == old:
                    operation["operationId"] = old + "_v2"
                    break
    found = guard.failures(snapshot=json.dumps(doc, indent=2))
    assert any("paths interface" in problem for problem in found), found


def test_generated_reference_drift_alone_is_rejected() -> None:
    generated = guard.GENERATED.read_text(encoding="utf-8")
    old = "liveness_api_v1_health_live_get"
    found = guard.failures(
        generated=generated.replace(f'operations["{old}"]', f'operations["{old}_v2"]', 1)
    )
    assert any("retyped" in problem for problem in found), found


def test_interface_key_dropped_is_rejected() -> None:
    generated = guard.GENERATED.read_text(encoding="utf-8")
    old = "liveness_api_v1_health_live_get"
    found = guard.failures(
        generated=generated.replace(f"    {old}: {{", "    dropped_symbol: {", 1)
    )
    assert any("interface keys" in problem for problem in found), found


def test_operation_dropped_is_rejected() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    del document["paths"]["/api/v1/health/live"]["get"]
    found = guard.failures(snapshot=json.dumps(document, indent=2))
    assert any("operation count" in problem for problem in found), found


def test_hand_bumped_literals_are_not_enough() -> None:
    assert any("drifted" in f for f in guard.failures(digest="0" * 64))
    assert any("count" in f for f in guard.failures(expected_count=999))


def test_duplicate_operation_id_is_rejected() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    old = "liveness_api_v1_health_live_get"
    for item in document["paths"].values():
        for method, operation in item.items():
            if method in guard.METHODS and isinstance(operation, dict):
                if operation.get("operationId") != old:
                    operation["operationId"] = old
                    break
        else:
            continue
        break
    found = guard.failures(snapshot=json.dumps(document, indent=2))
    assert any("not unique" in problem for problem in found), found


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
    assert "_OPERATION_ID_DIGEST" in assigned
    assert "_EXPECTED_OPERATION_COUNT" in assigned
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    assert guard._digest(guard._snapshot_map(document)) == guard._OPERATION_ID_DIGEST


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


def _swap_first_two_paths(text: str) -> str:
    """Swap the first two whole top-level path blocks, preserving all bytes."""
    import re

    starts = list(re.finditer(r'^    "(/[^"]+)": \{$', text, re.M))
    a, b, c = starts[0].start(), starts[1].start(), starts[2].start()
    return text[:a] + text[b:c] + text[a:b] + text[c:]


def test_committed_path_orders_match_both_independent_literals() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    snap_paths = guard._snapshot_paths(document)
    gen_paths = guard._generated_paths(guard.GENERATED.read_text(encoding="utf-8"))
    assert snap_paths == gen_paths
    assert len(snap_paths) == guard._EXPECTED_PATH_COUNT
    assert (
        guard._path_order_digest(snap_paths, "soymutdb-snapshot-path-order/v1")
        == guard._PATH_ORDER_DIGEST
    )
    assert (
        guard._path_order_digest(gen_paths, "soymutdb-client-path-order/v1")
        == guard._CLIENT_PATH_ORDER_DIGEST
    )


def test_the_order_literals_are_module_level_strings() -> None:
    tree = ast.parse(Path(guard.__file__).read_text(encoding="utf-8"))
    assigned = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned[target.id] = node.value
    for name in ("_PATH_ORDER_DIGEST", "_CLIENT_PATH_ORDER_DIGEST"):
        assert name in assigned, name
        value = ast.literal_eval(assigned[name])
        assert isinstance(value, str) and len(value) == 64
    assert guard._EXPECTED_PATH_COUNT == 238


def test_a_coordinated_path_block_swap_is_rejected() -> None:
    """The decisive permutation: same pair set, same counts, only order moves."""
    snapshot = guard.SNAPSHOT.read_text(encoding="utf-8")
    generated = guard.GENERATED.read_text(encoding="utf-8")
    swapped_snapshot = _swap_first_two_paths(snapshot)
    swapped_generated = _swap_first_two_paths(generated)
    found = guard.failures(
        snapshot=swapped_snapshot, generated=swapped_generated
    )
    assert any("_PATH_ORDER_DIGEST" in problem for problem in found), found
    assert any("_CLIENT_PATH_ORDER_DIGEST" in problem for problem in found), found
    # The sorted operationId digest and the three-way agreement stay silent:
    # this drift is invisible to every non-sequence door.
    assert not any("operationId surface drifted" in p for p in found), found
    assert not any("does not reference" in p for p in found), found


def test_a_coordinated_path_swap_with_both_digests_re_pinned_stays_green() -> None:
    snapshot = guard.SNAPSHOT.read_text(encoding="utf-8")
    generated = guard.GENERATED.read_text(encoding="utf-8")
    swapped_snapshot = _swap_first_two_paths(snapshot)
    swapped_generated = _swap_first_two_paths(generated)
    document = json.loads(swapped_snapshot)
    found = guard.failures(
        snapshot=swapped_snapshot,
        generated=swapped_generated,
        path_order_digest=guard._path_order_digest(
            guard._snapshot_paths(document), "soymutdb-snapshot-path-order/v1"
        ),
        client_path_order_digest=guard._path_order_digest(
            guard._generated_paths(swapped_generated),
            "soymutdb-client-path-order/v1",
        ),
    )
    assert not found, found


def test_re_pinning_only_one_order_digest_stays_red() -> None:
    snapshot = guard.SNAPSHOT.read_text(encoding="utf-8")
    generated = guard.GENERATED.read_text(encoding="utf-8")
    swapped_snapshot = _swap_first_two_paths(snapshot)
    swapped_generated = _swap_first_two_paths(generated)
    document = json.loads(swapped_snapshot)
    found = guard.failures(
        snapshot=swapped_snapshot,
        generated=swapped_generated,
        path_order_digest=guard._path_order_digest(
            guard._snapshot_paths(document), "soymutdb-snapshot-path-order/v1"
        ),
    )
    assert any("_CLIENT_PATH_ORDER_DIGEST" in problem for problem in found), found


def test_one_sided_path_reorders_are_named() -> None:
    snapshot = guard.SNAPSHOT.read_text(encoding="utf-8")
    generated = guard.GENERATED.read_text(encoding="utf-8")
    snap_only = guard.failures(snapshot=_swap_first_two_paths(snapshot))
    gen_only = guard.failures(generated=_swap_first_two_paths(generated))
    assert any("order disagrees" in p for p in snap_only), snap_only
    assert any("order disagrees" in p for p in gen_only), gen_only


def test_path_order_count_and_digest_doors_are_load_bearing() -> None:
    assert any("path count" in p for p in guard.failures(expected_path_count=999))
    assert any("_PATH_ORDER_DIGEST" in p for p in guard.failures(path_order_digest="0" * 64))
    assert any(
        "_CLIENT_PATH_ORDER_DIGEST" in p
        for p in guard.failures(client_path_order_digest="0" * 64)
    )


def test_the_path_order_self_test_plants_are_load_bearing() -> None:
    source = Path(guard.__file__).read_text(encoding="utf-8")
    assert "a coordinated path-block swap in both halves" in source
    assert "with both order digests re-pinned" in source
    assert "only the snapshot order digest re-pinned" in source
    assert 'kwargs.pop("expect_clean", False)' in source

def _swap_two_methods() -> str:
    """Byte-preserving swap of two adjacent methods under one path."""
    from collections import OrderedDict

    document = json.loads(
        guard.SNAPSHOT.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict
    )
    victim = next(
        path
        for path, item in document["paths"].items()
        if sum(1 for key in item if key in guard.METHODS) >= 2
    )
    order = [key for key in document["paths"][victim] if key in guard.METHODS]
    first, second = order[0], order[1]
    rebuilt: "OrderedDict[str, object]" = OrderedDict()
    for key, value in document["paths"][victim].items():
        if key == first:
            rebuilt[second] = document["paths"][victim][second]
        elif key == second:
            rebuilt[first] = document["paths"][victim][first]
        else:
            rebuilt[key] = value
    document["paths"][victim] = rebuilt
    drifted = json.dumps(document, indent=2)
    assert drifted != guard.SNAPSHOT.read_text(encoding="utf-8")
    return drifted


def test_method_swap_is_rejected() -> None:
    """The decisive drift: every sorted pair door stays silent on a reorder."""
    found = guard.failures(snapshot=_swap_two_methods())
    assert any("_METHOD_SEQUENCE_DIGEST" in problem for problem in found), found


def test_method_swap_with_honest_repin_stays_green() -> None:
    """A reviewed reorder re-pins the positional literal in the same commit."""
    drifted = _swap_two_methods()
    rows = guard.method_sequence_rows(json.loads(drifted))
    fresh = guard.failures(
        snapshot=drifted,
        method_sequence_digest=guard._method_sequence_digest(rows),
    )
    assert not fresh, fresh
    stale = guard.failures(snapshot=drifted)
    assert any("_METHOD_SEQUENCE_DIGEST" in problem for problem in stale), stale


def test_method_row_count_door_is_load_bearing() -> None:
    found = guard.failures(expected_method_rows=999)
    assert any("_EXPECTED_METHOD_ROWS" in problem for problem in found), found


def test_method_sequence_digest_is_an_independent_literal() -> None:
    """The pin must be a module-level string constant, not a derived value."""
    source = Path(guard.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    assert "_METHOD_SEQUENCE_DIGEST" in names
    assert "_EXPECTED_METHOD_ROWS" in names
    assert "method_sequence_rows(" in source
    assert "def _method_sequence_digest" in source
    docstring = ast.get_docstring(tree) or ""
    for literal in ("_METHOD_SEQUENCE_DIGEST", "_EXPECTED_METHOD_ROWS"):
        assert literal in docstring, f"guard docstring omits {literal}"


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
            problems.append(f"{case.__name__}: {str(exc) or 'assertion failed'}")
    if problems:
        for problem in problems:
            print(f"openapi-operation-id-floor-tests: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"openapi-operation-id-floor-tests: OK ({len(cases)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
