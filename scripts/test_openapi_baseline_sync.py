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

Door 1 cases inject the tree through ``failures(tree=...)``. That injection has
no parent commit, so it skips door 2 by construction -- which is why this suite
also injects the *history*: ``show`` (old source), ``changed_in`` (artifact
diff) and ``resolve`` (HEAD) are replaced for the duration of a case, while the
new sources and both artifacts still come from the committed tree. Nothing here
writes to the repository or needs a real commit.
"""

from __future__ import annotations

import contextlib
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
    # Delete the *assignment*, not the first mention: since #190 the guard's
    # docstring names ``_CLIENT_BODY_TOTAL`` ~250 lines above the literal, so a
    # first-match replace there edits prose, the reader still finds the literal,
    # and the ablation would pass vacuously.
    lines = tree[BODY_PATH].splitlines(keepends=True)
    kept = [ln for ln in lines if not ln.startswith("_CLIENT_BODY_TOTAL = ")]
    assert len(kept) == len(lines) - 1
    tree[BODY_PATH] = "".join(kept)
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

    A suite where ``failures()`` always returns ``[]`` would be a rack of
    passing no-ops. The floor keeps a deletion loud, and the clean tree is
    asserted to be the *only* tree that produces no problems. Door 2 has its
    own cases because an injected ``tree=`` skips it entirely: without them,
    deleting the whole history door leaves this suite green.
    """
    cases = [name for name in globals() if name.startswith("test_")]
    assert len(cases) >= 13, cases
    assert guard.failures(tree=_tree()) == []


@contextlib.contextmanager
def _history(old_sources: dict[str, str], moved: set[str]):
    """Inject only the readers door 2 uses, so it runs without a real commit.

    ``failures(base=...)`` takes its new sources and both artifacts from the
    working tree; git is asked for three things only: the old source
    (``show``), the artifact diff (``changed_in``) and the HEAD id
    (``resolve``). Replacing those three is enough to build every history case
    on the committed tree itself. Restored in ``finally`` so no case leaks.
    """
    saved = (guard.resolve, guard.show, guard.changed_in)
    guard.resolve = lambda _ref: "synthetic-head"
    guard.show = lambda _commit, path: old_sources.get(path)
    guard.changed_in = lambda _commit, _since, _paths: set(moved)
    try:
        yield
    finally:
        guard.resolve, guard.show, guard.changed_in = saved


def _old_sources_with_total(value: int) -> dict[str, str]:
    tree = _tree()
    _set_total(tree, value)
    return tree


def test_a_literal_moved_without_the_artifacts_is_rejected() -> None:
    """Door 2, the one edit door 1 cannot see.

    The old source pins 808 and the committed tree pins 807; each agrees with
    its own artifacts, so the semantic door is silent. Only the history says
    the pin was bumped while neither artifact changed.
    """
    total = guard.pinned_literal(guard.BODY_GUARD, "_CLIENT_BODY_TOTAL")
    with _history(_old_sources_with_total(total + 1), moved=set()):
        found = guard.failures(base="synthetic-base")
    assert _any(found, "_CLIENT_BODY_TOTAL moved"), found
    assert _any(found, "but none of"), found
    assert not _any(found, "committed artifacts"), found


def test_a_literal_moved_with_the_artifacts_passes() -> None:
    """The door is satisfiable: a regenerate moving pin + artifacts is green."""
    total = guard.pinned_literal(guard.BODY_GUARD, "_CLIENT_BODY_TOTAL")
    with _history(_old_sources_with_total(total + 1),
                  moved={SNAPSHOT_PATH, GENERATED_PATH}):
        found = guard.failures(base="synthetic-base")
    assert found == [], found


def test_the_history_door_respects_each_gates_own_artifacts() -> None:
    """The error baseline pins the snapshot; moving only the client is not enough."""
    old = _tree()
    pinned = guard.pinned_literal(guard.ENVELOPE_GUARD, "_ERROR_RESPONSE_BASELINE")
    was = json.dumps(pinned, sort_keys=True)
    pinned["500"] = pinned["500"] + 1
    line = f"_ERROR_RESPONSE_BASELINE = {was}"
    assert line in old[ENVELOPE_PATH]
    old[ENVELOPE_PATH] = old[ENVELOPE_PATH].replace(
        line, f"_ERROR_RESPONSE_BASELINE = {json.dumps(pinned)}", 1
    )
    with _history(old, moved={GENERATED_PATH}):
        found = guard.failures(base="synthetic-base")
    assert _any(found, "_ERROR_RESPONSE_BASELINE moved"), found


def test_an_unchanged_literal_needs_no_artifact_move() -> None:
    """The door is not a tripwire: a baseline that did not move says nothing."""
    with _history(_tree(), moved=set()):
        found = guard.failures(base="synthetic-base")
    assert found == [], found


def test_a_shallow_clone_without_an_old_source_is_not_a_failure() -> None:
    """No old source means no history to compare; door 2 steps aside."""
    with _history({}, moved=set()):
        found = guard.failures(base="synthetic-base")
    assert found == [], found


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
