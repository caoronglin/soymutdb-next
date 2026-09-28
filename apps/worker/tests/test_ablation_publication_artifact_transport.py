"""Guards for the build-artifact transport into the publication worker.

The pipeline previously had no way to hand a real SSG build to the worker, which
is why ``build_static_tree`` synthesised a placeholder. The request now records
an immutable ``build_artifact_url`` that travels in the outbox payload, and the
worker materialises it into a build directory.

Two safety properties are asserted here as well, because the artifact is fetched
from storage rather than authored locally:

* the download is bounded, so a bad URL cannot fill the worker's disk;
* an archive cannot escape the staging directory (``../`` members, absolute
  paths, symlinks/hardlinks/device nodes are refused).

Unit-level: HTTP and the filesystem are local; no broker or network.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from soymutdb_worker.tasks.static_publish_impl import (
    ArtifactFetchError,
    materialize_artifact,
)


def _tarball(path: Path, members: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return path


def _raw_tarball(path: Path, entries: list[tuple[tarfile.TarInfo, bytes | None]]) -> Path:
    """Build a tarball with explicit (possibly hostile) member metadata."""
    with tarfile.open(path, "w:gz") as tar:
        for info, content in entries:
            tar.addfile(info, io.BytesIO(content) if content is not None else None)
    return path


# ---------------------------------------------------------------------------
# 1. No artifact reference -> no publication (never a synthetic tree).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "   "])
def test_no_artifact_url_returns_none_so_the_build_fails_closed(value):
    assert materialize_artifact(value) is None


# ---------------------------------------------------------------------------
# 2. Local directories and archives.
# ---------------------------------------------------------------------------


def test_a_local_directory_is_used_directly(tmp_path: Path) -> None:
    build = tmp_path / "build"
    build.mkdir()
    (build / "index.html").write_text("hi", "utf-8")

    assert materialize_artifact(str(build)) == build
    assert materialize_artifact(f"file://{build}") == build


def test_a_tarball_is_extracted(tmp_path: Path) -> None:
    archive = _tarball(
        tmp_path / "site.tar.gz",
        {"index.html": b"<html>ok</html>", "assets/app.js": b"export {};"},
    )

    out = materialize_artifact(f"file://{archive}", workdir=tmp_path / "work")

    assert out is not None
    assert (out / "index.html").read_bytes() == b"<html>ok</html>"
    assert (out / "assets" / "app.js").is_file()


def test_a_plain_file_that_is_not_an_archive_is_refused(tmp_path: Path) -> None:
    stray = tmp_path / "artifact.zip"
    stray.write_bytes(b"PK\x03\x04 not a tar")

    with pytest.raises(ArtifactFetchError, match="neither a directory nor a tar"):
        materialize_artifact(str(stray), workdir=tmp_path / "work")


def test_a_missing_reference_is_an_explicit_error(tmp_path: Path) -> None:
    with pytest.raises(ArtifactFetchError, match="does not exist"):
        materialize_artifact(str(tmp_path / "nope"))


# ---------------------------------------------------------------------------
# 3. Archive extraction cannot escape the staging directory.
# ---------------------------------------------------------------------------


def test_traversal_member_is_refused(tmp_path: Path) -> None:
    info = tarfile.TarInfo("../escaped.txt")
    content = b"pwned"
    info.size = len(content)
    archive = _raw_tarball(tmp_path / "evil.tar.gz", [(info, content)])

    with pytest.raises(ArtifactFetchError, match="escapes the target directory"):
        materialize_artifact(str(archive), workdir=tmp_path / "work")

    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path / "work" / "escaped.txt").exists()


def test_absolute_member_is_refused(tmp_path: Path) -> None:
    info = tarfile.TarInfo("/tmp/soymutdb-absolute-escape.txt")
    content = b"pwned"
    info.size = len(content)
    archive = _raw_tarball(tmp_path / "abs.tar.gz", [(info, content)])

    with pytest.raises(ArtifactFetchError, match="escapes the target directory"):
        materialize_artifact(str(archive), workdir=tmp_path / "work")


def test_symlink_member_is_refused(tmp_path: Path) -> None:
    info = tarfile.TarInfo("link")
    info.type = tarfile.SYMTYPE
    info.linkname = "/etc/passwd"
    archive = _raw_tarball(tmp_path / "link.tar.gz", [(info, None)])

    with pytest.raises(ArtifactFetchError, match="unsupported member"):
        materialize_artifact(str(archive), workdir=tmp_path / "work")


# ---------------------------------------------------------------------------
# 4. The download is bounded.
# ---------------------------------------------------------------------------


def test_oversized_download_is_refused(tmp_path: Path, monkeypatch) -> None:
    import soymutdb_worker.tasks.static_publish_impl as impl

    monkeypatch.setattr(impl, "MAX_ARTIFACT_BYTES", 1024)

    class _Response:
        def __init__(self) -> None:
            self._chunks = [b"x" * 512] * 8  # 4 KiB total

        def read(self, _n: int) -> bytes:
            return self._chunks.pop(0) if self._chunks else b""

        def __enter__(self):
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    with mock.patch.object(impl.urllib.request, "urlopen", lambda *a, **k: _Response()):
        with pytest.raises(ArtifactFetchError, match="byte ceiling"):
            impl.materialize_artifact("https://artifacts.example/big.tar.gz")


def test_download_failure_is_reported_as_an_artifact_error(tmp_path: Path) -> None:
    import soymutdb_worker.tasks.static_publish_impl as impl

    def _boom(*args: Any, **kwargs: Any):
        raise OSError("connection refused")

    with mock.patch.object(impl.urllib.request, "urlopen", _boom):
        with pytest.raises(ArtifactFetchError, match="could not fetch"):
            impl.materialize_artifact("https://artifacts.example/site.tar.gz")


def test_a_successful_http_download_is_extracted(tmp_path: Path) -> None:
    import soymutdb_worker.tasks.static_publish_impl as impl

    archive = _tarball(tmp_path / "remote.tar.gz", {"index.html": b"<html>remote</html>"})
    payload = archive.read_bytes()

    class _Response:
        def __init__(self) -> None:
            self._chunks = [payload]

        def read(self, _n: int) -> bytes:
            return self._chunks.pop(0) if self._chunks else b""

        def __enter__(self):
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    with mock.patch.object(impl.urllib.request, "urlopen", lambda *a, **k: _Response()):
        out = impl.materialize_artifact(
            "https://artifacts.example/site.tar.gz", workdir=tmp_path / "work"
        )

    assert out is not None
    assert "remote" in (out / "index.html").read_text("utf-8")


# ---------------------------------------------------------------------------
# 5. run_publication prefers an explicit dir, else the artifact URL.
# ---------------------------------------------------------------------------


class _Store:
    def __init__(self) -> None:
        self.transitions: list[tuple[int, str]] = []

    def transition(self, publication_id: int, status: str, **kwargs: Any) -> bool:
        self.transitions.append((publication_id, status))
        return True

    def should_promote(self, publication_id: int) -> bool:
        return True

    def record_published(self, publication_id: int, **kwargs: Any) -> bool:
        self.transitions.append((publication_id, "published"))
        return True


class _Adapter:
    target = "local"

    def __init__(self) -> None:
        self.promoted = 0

    def stage(self, publication_id: int, artifact: Path):
        from soymutdb_worker.publication.base import DeploymentRef

        return DeploymentRef(
            target="local", ref="r", manifest_digest="d" * 64, artifact_path=str(artifact)
        )

    def verify(self, deployment):
        from soymutdb_worker.publication.base import ValidationEvidence

        return ValidationEvidence(ok=True, digest_verified=True)

    def promote(self, deployment) -> str:
        self.promoted += 1
        return "remote:1"


def test_run_publication_fetches_the_artifact_when_no_build_dir_is_given(
    tmp_path: Path, monkeypatch
) -> None:
    import soymutdb_worker.tasks.static_publish_impl as impl

    build = tmp_path / "build"
    build.mkdir()
    (build / "index.html").write_text("<!doctype html><html>real</html>", "utf-8")

    monkeypatch.setattr(impl, "DIST_ROOT", tmp_path / "releases")
    store, adapter = _Store(), _Adapter()
    seen: dict[str, Any] = {}

    def _materialize(url: str, **kwargs: Any) -> Path:
        seen["url"] = url
        return build

    monkeypatch.setattr(impl, "materialize_artifact", _materialize)

    with mock.patch.object(impl, "PublicationStateStore", lambda: store), mock.patch.object(
        impl, "get_adapter", lambda target: adapter
    ):
        result = impl.run_publication(
            {
                "publication_id": 1,
                "target": "local",
                "release_id": 1,
                "build_artifact_url": "https://artifacts.example/site.tar.gz",
            }
        )

    assert result["status"] == "published"
    assert seen["url"] == "https://artifacts.example/site.tar.gz"
    assert adapter.promoted == 1
