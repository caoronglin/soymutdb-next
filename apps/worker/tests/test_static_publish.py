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


def test_build_static_tree_writes_fresh_tree_and_manifest(tmp_path: Path) -> None:
    from soymutdb_worker.tasks.static_publish_impl import build_static_tree

    # Redirect DIST_ROOT via monkeypatch (module constant used inside paths).
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "soymutdb_worker.tasks.static_publish_impl.DIST_ROOT", tmp_path / "releases"
    )

    tree, digest = build_static_tree(
        release_id=7, page_definition_version=3, snapshot={"about": {}}
    )
    assert tree.is_dir()
    assert (tree / "manifest.json").is_file()
    assert (tree / "index.html").is_file()
    assert (tree / "data" / "content.json").is_file()

    ev = verify_manifest(tree, digest)
    assert ev.ok is True

    # A second build for a different release produces a different digest dir.
    tree2, digest2 = build_static_tree(
        release_id=8, page_definition_version=3, snapshot={"about": {}}
    )
    assert tree != tree2


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
