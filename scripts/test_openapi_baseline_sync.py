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
no parent commit, so it skips door 2 by construction. Door 2 cases instead
build a *real* parent commit in a temporary object directory: the guard's own
``resolve``, ``show`` and ``changed_in`` run unmodified against it, so ``moved``
is a real ``git diff`` between two real commits, never a set of paths a test
handed the guard. New sources and both artifacts still come from the committed
working tree. No ref, index or object of the repository is written.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
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
    assert len(cases) >= 14, cases
    assert guard.failures(tree=_tree()) == []


def _source_with_total(value: int) -> str:
    """The body guard's real source with only ``_CLIENT_BODY_TOTAL`` moved."""
    total = guard.pinned_literal(guard.BODY_GUARD, "_CLIENT_BODY_TOTAL")
    source = (ROOT / BODY_PATH).read_text(encoding="utf-8")
    moved = source.replace(
        f"_CLIENT_BODY_TOTAL = {total}", f"_CLIENT_BODY_TOTAL = {value}", 1
    )
    assert moved != source
    return moved


def _source_with_bumped_error_baseline() -> str:
    """The envelope guard's real source with only the 500 count moved."""
    source = (ROOT / ENVELOPE_PATH).read_text(encoding="utf-8")
    pinned = guard.pinned_literal(guard.ENVELOPE_GUARD, "_ERROR_RESPONSE_BASELINE")
    was = json.dumps(pinned, sort_keys=True)
    pinned["500"] = pinned["500"] + 1
    line = f"_ERROR_RESPONSE_BASELINE = {was}"
    assert line in source
    return source.replace(
        line, f"_ERROR_RESPONSE_BASELINE = {json.dumps(pinned)}", 1
    )


def _artifact_with_a_newline(path: str) -> str:
    """Real artifact bytes that differ from HEAD without changing any pin."""
    return (ROOT / path).read_text(encoding="utf-8") + "\n"


@contextlib.contextmanager
def _real_history(changes: dict[str, str | None], *, empty_tree: bool = False):
    """Yield a real parent commit whose tree differs from HEAD by ``changes``.

    The commit and its blobs live in a temporary object directory, with the
    repository's own objects as an alternate. ``guard.git`` is redirected at
    that store for the duration of the case, so ``resolve``, ``show`` and
    ``changed_in`` remain the production readers: ``moved`` is a real ``git
    diff`` between two real commits, never a set of paths a test handed the
    guard. No ref, index or object of the repository is written, and the
    working tree is untouched. ``empty_tree`` models a shallow clone where
    the old source is unavailable.
    """

    def fixture_git(*args: str, env: dict[str, str], stdin: str | None = None) -> str:
        result = subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=ROOT, env=env, input=stdin, capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise AssertionError(
                f"history fixture: git {' '.join(args)}: {result.stderr.strip()}"
            )
        return result.stdout

    _, out = guard.git("rev-parse", "--path-format=absolute", "--git-path", "objects")
    objects = out.strip()
    alternates = [objects]
    info = Path(objects) / "info" / "alternates"
    if info.exists():
        alternates += [
            line.strip()
            for line in info.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "objects"
        store.mkdir()
        env = dict(
            os.environ,
            GIT_OBJECT_DIRECTORY=str(store),
            GIT_ALTERNATE_OBJECT_DIRECTORIES=":".join(alternates),
            GIT_INDEX_FILE=str(Path(tmp) / "index"),
            GIT_AUTHOR_NAME="baseline-sync-fixture",
            GIT_AUTHOR_EMAIL="fixture@invalid",
            GIT_COMMITTER_NAME="baseline-sync-fixture",
            GIT_COMMITTER_EMAIL="fixture@invalid",
        )
        head = fixture_git("rev-parse", "HEAD", env=env).strip()
        if empty_tree:
            tree = fixture_git("mktree", env=env, stdin="").strip()
        else:
            fixture_git("read-tree", head, env=env)
            for path, text in changes.items():
                if text is None:
                    fixture_git("update-index", "--force-remove", path, env=env)
                else:
                    blob = fixture_git(
                        "hash-object", "-w", "--stdin", env=env, stdin=text
                    ).strip()
                    fixture_git(
                        "update-index", "--cacheinfo", f"100644,{blob},{path}", env=env
                    )
            tree = fixture_git("write-tree", env=env).strip()
        base = fixture_git(
            "commit-tree", tree, "-p", head, "-m", "synthetic baseline history", env=env
        ).strip()

        real_git = guard.git

        def redirected(*args: str) -> tuple[int, str]:
            result = subprocess.run(
                ["git", "-c", "commit.gpgsign=false", *args],
                cwd=ROOT, env=env, capture_output=True, text=True, check=False,
            )
            return result.returncode, result.stdout

        guard.git = redirected
        try:
            yield base
        finally:
            guard.git = real_git


def test_a_literal_moved_without_the_artifacts_is_rejected() -> None:
    """Door 2, the one edit door 1 cannot see.

    The real parent commit pins 808 and HEAD pins 807; each agrees with its own
    artifacts, so the semantic door is silent. Only a real ``git diff`` between
    the two commits says no artifact moved with the pin.
    """
    total = guard.pinned_literal(guard.BODY_GUARD, "_CLIENT_BODY_TOTAL")
    with _real_history({BODY_PATH: _source_with_total(total + 1)}) as base:
        found = guard.failures(base=base)
    assert _any(found, "_CLIENT_BODY_TOTAL moved"), found
    assert _any(found, "but none of"), found
    assert not _any(found, "committed artifacts"), found


def test_a_literal_moved_with_the_artifacts_passes() -> None:
    """The door is satisfiable: a regenerate moving pin + artifacts is green.

    Both artifacts are really changed in the parent commit, so the guard's own
    ``changed_in`` reports them. The green is earned by git, not injected.
    """
    total = guard.pinned_literal(guard.BODY_GUARD, "_CLIENT_BODY_TOTAL")
    with _real_history(
        {
            BODY_PATH: _source_with_total(total + 1),
            SNAPSHOT_PATH: _artifact_with_a_newline(SNAPSHOT_PATH),
            GENERATED_PATH: _artifact_with_a_newline(GENERATED_PATH),
        }
    ) as base:
        found = guard.failures(base=base)
    assert found == [], found


def test_the_history_door_respects_each_gates_own_artifacts() -> None:
    """The error baseline pins the snapshot; moving only the client is not enough."""
    with _real_history(
        {
            ENVELOPE_PATH: _source_with_bumped_error_baseline(),
            GENERATED_PATH: _artifact_with_a_newline(GENERATED_PATH),
        }
    ) as base:
        found = guard.failures(base=base)
    assert _any(found, "_ERROR_RESPONSE_BASELINE moved"), found


def test_a_reader_that_invents_artifact_moves_is_rejected() -> None:
    """The suite fails closed when the *real* ``changed_in`` stops reading git.

    The previous suite overrode ``changed_in`` with a planted set in every
    history case, so replacing the production reader with ``return set(paths)``
    left all 13 checks green: a pin-only edit would pass as if a regenerate had
    happened. With real commits behind every case, that ablation must be RED.
    The positive control restores the reader and shows the same commit is RED
    again, proving the green came from git and not from a stubbable helper.
    """
    total = guard.pinned_literal(guard.BODY_GUARD, "_CLIENT_BODY_TOTAL")
    with _real_history({BODY_PATH: _source_with_total(total + 1)}) as base:
        assert _any(guard.failures(base=base), "_CLIENT_BODY_TOTAL moved")
        saved = guard.changed_in
        guard.changed_in = lambda _commit, _since, paths: set(paths)
        try:
            found = guard.failures(base=base)
        finally:
            guard.changed_in = saved
        assert found == [], found
        assert _any(guard.failures(base=base), "_CLIENT_BODY_TOTAL moved")


def test_an_unchanged_literal_needs_no_artifact_move() -> None:
    """The door is not a tripwire: a baseline that did not move says nothing."""
    with _real_history({}) as base:
        found = guard.failures(base=base)
    assert found == [], found


def test_a_shallow_clone_without_an_old_source_is_not_a_failure() -> None:
    """No old source means no history to compare; door 2 steps aside."""
    with _real_history({}, empty_tree=True) as base:
        found = guard.failures(base=base)
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
            problems.append(f"{case.__name__}: {str(exc) or 'assertion failed'}")
    if problems:
        for problem in problems:
            print(f"openapi-baseline-sync-tests: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"openapi-baseline-sync-tests: OK ({len(cases)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
