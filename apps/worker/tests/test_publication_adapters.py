"""Tests for the Phase 3 publication adapters (local / github_pages / cf_pages)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from soymutdb_worker.publication import (
    get_adapter,
    manifest_digest_of_file,
    verify_manifest,
)
from soymutdb_worker.publication.local import LocalAdapter


def _make_artifact(tmp_path: Path) -> tuple[Path, str]:
    artifact = tmp_path / "artifact"
    artifact.mkdir(parents=True, exist_ok=True)
    (artifact / "index.html").write_text("<html></html>", "utf-8")
    (artifact / "404.html").write_text("<html></html>", "utf-8")
    files = {
        "index.html": hashlib.sha256((artifact / "index.html").read_bytes()).hexdigest(),
        "404.html": hashlib.sha256((artifact / "404.html").read_bytes()).hexdigest(),
    }
    manifest = {
        "schema_version": 1,
        "release_id": 1,
        "page_definition_version": None,
        "application": "soymutdb-next",
        "files": files,
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    (artifact / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2), "utf-8"
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return artifact, digest


def test_registry_resolves_all_targets():
    assert get_adapter("local").target == "local"
    assert get_adapter("github_pages").target == "github_pages"
    assert get_adapter("cloudflare_pages").target == "cloudflare_pages"
    with pytest.raises(ValueError):
        get_adapter("unknown")


def test_manifest_digest_is_stable():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "manifest.json"
        p.write_text('{"a":1,"b":2}', "utf-8")
        d1 = manifest_digest_of_file(p)
        d2 = manifest_digest_of_file(p)
        assert d1 == d2
        assert len(d1) == 64


def test_local_stage_fails_leave_old_symlink_unchanged(tmp_path):
    root = tmp_path / "pub"
    adapter = LocalAdapter(str(root))
    artifact, digest = _make_artifact(tmp_path)

    # First successful promote.
    d1 = adapter.stage(1, artifact)
    ev = adapter.verify(d1)
    assert ev.ok and ev.digest_verified
    remote1 = adapter.promote(d1)
    current = root / "current"
    assert current.is_symlink()

    # A tampered artifact (verify fails) must not change ``current``.
    tampered, _ = _make_artifact(tmp_path / "tampered")
    (tampered / "index.html").write_text("tampered", "utf-8")
    d2 = adapter.stage(2, tampered)
    ev2 = adapter.verify(d2)
    assert ev2.ok is False
    # Never promoted → current still points at the first version directory.
    assert current.resolve() == Path(remote1)


def test_local_stage_verify_promote(tmp_path):
    root = tmp_path / "pub"
    adapter = LocalAdapter(str(root))
    artifact, digest = _make_artifact(tmp_path)

    d = adapter.stage(42, artifact)
    assert d.manifest_digest == digest
    ev = adapter.verify(d)
    assert ev.ok is True
    remote = adapter.promote(d)
    assert (root / "current").resolve() == Path(remote)


def test_local_rollback_restores_previous(tmp_path):
    root = tmp_path / "pub"
    adapter = LocalAdapter(str(root))
    (tmp_path / "a").mkdir(parents=True, exist_ok=True)
    (tmp_path / "b").mkdir(parents=True, exist_ok=True)
    a1, _ = _make_artifact(tmp_path / "a" / "sub")
    a2, _ = _make_artifact(tmp_path / "b" / "sub")

    r1 = adapter.promote(adapter.stage(1, a1))
    r2 = adapter.promote(adapter.stage(2, a2))
    assert (root / "current").resolve() == Path(r2)

    adapter.rollback(r1)
    assert (root / "current").resolve() == Path(r1)


def test_verify_manifest_detects_hash_mismatch(tmp_path):
    artifact, digest = _make_artifact(tmp_path)
    # Tamper with a file.
    (artifact / "index.html").write_text("tampered", "utf-8")
    ev = verify_manifest(artifact, digest)
    assert ev.ok is False
    assert ev.digest_verified is True  # manifest itself unchanged
