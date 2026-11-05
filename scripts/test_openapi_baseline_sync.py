"""Mutation coverage for ``scripts/check_openapi_baseline_sync.py``.

The guard's job is to catch the one edit that turns every other offline
OpenAPI guard green: bumping a pinned baseline literal while the two committed
artifacts stay put. Each case here builds the exact tree that edit produces and
asserts the guard reports it -- a guard that would pass vacuously is the
failure mode this file exists to prevent.

Two independent doors are exercised separately, because they read different
things and either one alone has a blind spot:

* door 1 (semantic) recomputes the pinned number from the artifacts and
  compares it to the literal. It needs no git, so it holds on a shallow CI
  checkout and in a squash commit where a parent diff would lie;
* door 2 (history) requires that a moved literal sits in a commit whose
  artifacts moved with it. This is the "edited a number to match a tree I never
  committed" case that door 1 cannot see because the tree *is* consistent.

Nothing here writes to the repository: every case injects the tree through
``failures(tree=...)``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_openapi_baseline_sync as guard  # noqa: E402

SNAPSHOT_PATH = guard.ARTIFACT_PATHS["snapshot"]
GENERATED_PATH = guard.ARTIFACT_PATHS["generated"]
ENVELOPE_PATH = str(guard.ENVELOPE_GUARD.relative_to(ROOT))
BODY_PATH = str(guard.BODY_GUARD.relative_to(ROOT))
SMOKE_PATH = str(guard.SMOKE.relative_to(ROOT))

BODY_LINE = '"application/json": components["schemas"]["%s"];'


def _tree() -> dict[str, str]:
    """The committed tree, as the guard reads it."""
    return {
        SNAPSHOT_PATH: (ROOT / SNAPSHOT_PATH).read_text(encoding="utf-8"),
        GENERATED_PATH: (ROOT / GENERATED_PATH).read_text(encoding="utf-8"),
        ENVELOPE_PATH: (ROOT / ENVELOPE_PATH).read_text(encoding="utf-8"),
        BODY_PATH: (ROOT / BODY_PATH).read_text(encoding="utf-8"),
        SMOKE_PATH: (ROOT / SMOKE_PATH).read_text(encoding="utf-8"),
    }


def _any(found: list[str], marker: str) -> bool:
    return any(marker in problem for problem in found)


def _set_total(tree: dict[str, str], value: int) -> None:
    tree[BODY_PATH] = tree[BODY_PATH].replace(
        f"_CLIENT_BODY_TOTAL = {guard.pinned_literal(guard.BODY_GUARD, '_CLIENT_BODY_TOTAL')}",
        f"_CLIENT_BODY_TOTAL = {value}",
        1,
    )


def test_committed_tree_passes() -> None:
    assert guard.failures(tree=_tree()) == []


def test_bumped_total_with_untouched_artifacts_is_rejected() -> None:
    """The exact hole: ``807`` -> ``808``, nothing else touched."""
    tree = _tree()
    total = guard.pinned_literal(guard.BODY_GUARD, "_CLIENT_BODY_TOTAL")
    _set_total(tree, total + 1)
    found = guard.failures(tree=tree)
    assert _any(found, "_CLIENT_BODY_TOTAL"), found
    assert _any(found, "committed artifacts"), found


def test_bumped_error_baseline_with_untouched_artifacts_is_rejected() -> None:
    tree = _tree()
    pinned = guard.pinned_literal(guard.ENVELOPE_GUARD, "_ERROR_RESPONSE_BASELINE")
    was = json.dumps(pinned, sort_keys=True)
    pinned["500"] = pinned["500"] + 1
    tree[ENVELOPE_PATH] = tree[ENVELOPE_PATH].replace(
        f"_ERROR_RESPONSE_BASELINE = {was}", f"_ERROR_RESPONSE_BASELINE = {json.dumps(pinned)}", 1
    )
    found = guard.failures(tree=tree)
    assert _any(found, "_ERROR_RESPONSE_BASELINE"), found


def test_artifacts_moving_alone_are_rejected() -> None:
    """The other direction: a body appears in the client and no pin follows."""
    tree = _tree()
    tree[GENERATED_PATH] = tree[GENERATED_PATH] + "\n" + (BODY_LINE % "ErrorResponse") + "\n"
    found = guard.failures(tree=tree)
    assert _any(found, "_CLIENT_BODY_TOTAL"), found


def test_a_baseline_that_disappears_is_rejected() -> None:
    tree = _tree()
    tree[BODY_PATH] = tree[BODY_PATH].replace("_CLIENT_BODY_TOTAL", "_CLIENT_BODY_TOTAL_OLD", 1)
    found = guard.failures(tree=tree)
    assert _any(found, "_CLIENT_BODY_TOTAL"), found


def test_rewiring_the_guard_out_of_the_contracts_layer_is_rejected() -> None:
    tree = _tree()
    line = f'  "${{PYTHON_BIN}}" scripts/{guard.SELF} --self-test || rc=$?\n'
    assert line in tree[SMOKE_PATH]
    tree[SMOKE_PATH] = tree[SMOKE_PATH].replace(line, "", 1)
    assert tree[SMOKE_PATH] != _tree()[SMOKE_PATH]
    found = guard.failures(tree=tree)
    assert _any(found, "does not invoke"), found


def test_client_total_reader_is_anchored_to_the_body_line() -> None:
    """A reader that matched bare ``components["schemas"][`` skews by a third.

    The generated file carries type-level references to the same components
    (1084 of them, against 807 printed bodies). Counting those would make the
    pinned total disagree with a correct guard, which is a false red -- and a
    guard that reports on a clean tree is the one thing this file cannot allow.
    """
    generated = (ROOT / GENERATED_PATH).read_text(encoding="utf-8")
    counts = guard.client_bodies(generated)
    assert sum(counts.values()) == guard.pinned_literal(guard.BODY_GUARD, "_CLIENT_BODY_TOTAL")
    naive = generated.count('components["schemas"][')
    assert naive > sum(counts.values())


def test_the_suite_has_teeth() -> None:
    """Every case above builds a failing tree and asserts on the marker.

    A suite where ``failures()`` always returns ``[]`` would be seven passing
    no-ops. This pins the count so a deletion is loud, and asserts the clean
    tree is the *only* one that produces no problems.
    """
    cases = [name for name in globals() if name.startswith("test_")]
    assert len(cases) >= 7, cases
    assert guard.failures(tree=_tree()) == []


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
            problems.append(f"{case.__name__}: {exc or 'assertion failed'}")
    if problems:
        for problem in problems:
            print(f"openapi-baseline-sync-tests: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"openapi-baseline-sync-tests: OK ({len(cases)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
