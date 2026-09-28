"""Tests for the Phase 3 static-publish build pipeline (no live DB)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from soymutdb_worker.publication import verify_manifest
from soymutdb_worker.tasks.publication_store import (
    _TRANSITIONS,
    PublicationStateStore,
)


def test_transition_matrix_matches_state_machine() -> None:
    # Forward path.
    assert "building" in _TRANSITIONS["requested"]
    assert "validating" in _TRANSITIONS["building"]
    assert "deploying" in _TRANSITIONS["validating"]
    assert "published" in _TRANSITIONS["deploying"]
    assert "superseded" in _TRANSITIONS["deploying"]
    # Terminal states allow nothing.
    assert _TRANSITIONS["failed"] == set()
    assert _TRANSITIONS["rolled_back"] == set()
    assert _TRANSITIONS["superseded"] == set()
    # published -> rolled_back only.
    assert _TRANSITIONS["published"] == {"rolled_back"}


def test_build_manifest_is_deterministic(tmp_path: Path) -> None:
    from soymutdb_worker.tasks.static_publish_impl import build_manifest

    a = tmp_path / "a"
    a.mkdir()
    (a / "index.html").write_text("<html></html>", "utf-8")
    d1 = build_manifest(a, release_id=1, page_definition_version=None)
    d2 = build_manifest(a, release_id=1, page_definition_version=None)
    assert d1 == d2
    assert len(d1) == 64


def _ssg_output(root: Path, *, label: str = "real") -> Path:
    """A stand-in for a real SSG build directory."""
    build = root / f"build-{label}"
    (build / "assets").mkdir(parents=True, exist_ok=True)
    (build / "index.html").write_text(
        f"<!doctype html><html><body>{label} site</body></html>", "utf-8"
    )
    (build / "assets" / "app.js").write_text("export {};\n", "utf-8")
    (build / "data").mkdir(parents=True, exist_ok=True)
    (build / "data" / "content.json").write_text('{"about": {}}', "utf-8")
    return build


def test_build_static_tree_uses_the_real_build_output(tmp_path: Path) -> None:
    from soymutdb_worker.tasks.static_publish_impl import build_static_tree

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "soymutdb_worker.tasks.static_publish_impl.DIST_ROOT", tmp_path / "releases"
    )
    build = _ssg_output(tmp_path, label="real")

    tree, digest = build_static_tree(
        release_id=7, page_definition_version=3, build_dir=build
    )

    assert tree.is_dir()
    assert (tree / "manifest.json").is_file()
    # The artifact is the build output, byte-for-byte, plus the manifest.
    assert "real site" in (tree / "index.html").read_text("utf-8")
    assert (tree / "assets" / "app.js").is_file()
    assert (tree / "data" / "content.json").is_file()

    ev = verify_manifest(tree, digest)
    assert ev.ok is True

    # A second build for a different release produces a different digest dir.
    tree2, _digest2 = build_static_tree(
        release_id=8, page_definition_version=3, build_dir=build
    )
    assert tree != tree2


def test_build_static_tree_refuses_a_synthetic_tree(tmp_path: Path) -> None:
    """Ablation: the synthetic single-page fallback must not come back.

    The previous implementation published a one-page placeholder whenever no
    build chain existed, so a request could report ``published`` while serving
    nothing. There is deliberately no fallback now.
    """
    from soymutdb_worker.tasks.static_publish_impl import (
        MissingBuildOutput,
        build_static_tree,
    )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "soymutdb_worker.tasks.static_publish_impl.DIST_ROOT", tmp_path / "releases"
    )

    with pytest.raises(MissingBuildOutput, match="No SSG build output"):
        build_static_tree(
            release_id=7, page_definition_version=3, build_dir=None
        )


def test_build_static_tree_refuses_a_missing_or_empty_directory(tmp_path: Path) -> None:
    from soymutdb_worker.tasks.static_publish_impl import (
        MissingBuildOutput,
        build_static_tree,
    )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "soymutdb_worker.tasks.static_publish_impl.DIST_ROOT", tmp_path / "releases"
    )

    with pytest.raises(MissingBuildOutput, match="not a directory"):
        build_static_tree(
            release_id=7, page_definition_version=None, build_dir=tmp_path / "nope"
        )

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(MissingBuildOutput, match="missing required file"):
        build_static_tree(
            release_id=7, page_definition_version=None, build_dir=empty
        )


def test_state_store_transition_guards_status() -> None:
    store = PublicationStateStore()

    # Mock get_db to return a fake session whose execute returns a row.
    class _FakeSession:
        def __init__(self, status):
            self.status = status

        def execute(self, stmt, *args, **kwargs):
            return _FakeResult(self.status)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeResult:
        def __init__(self, status):
            self.status = status

        def first(self):
            return (self.status,)

        def __getattr__(self, name):
            if name == "rowcount":
                return 1
            raise AttributeError(name)

    with mock.patch(
        "soymutdb_worker.tasks.publication_store.get_db"
    ) as get_db:
        get_db.return_value = _FakeSession("building")
        # building -> validating is allowed.
        ok = store.transition(1, "validating", manifest_digest="d" * 64)
        assert ok is True

    # An invalid transition (requested -> published) must be rejected.
    with mock.patch(
        "soymutdb_worker.tasks.publication_store.get_db"
    ) as get_db:
        get_db.return_value = _FakeSession("requested")
        assert store.transition(1, "published") is False
