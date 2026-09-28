"""Guards for the publication staging contract (no network).

Two defects motivated these:

* ``GithubPagesAdapter.stage`` returned a ``DeploymentRef`` with an **empty**
  ``metadata`` dict, while ``promote`` reads ``metadata["publication_id"]`` and
  ``metadata["artifact_url"]``. The dispatched ``workflow_dispatch`` therefore
  carried empty inputs and the ``pages.yml`` run could not identify what to
  deploy.
* ``run_publication`` checked the latest-request pointer only *before*
  ``stage/verify``, which involves network I/O; a newer request landing in that
  window was overwritten by the now-stale artifact.

Everything here is unit-level: HTTP is monkeypatched, no broker or network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from soymutdb_worker.publication.github_pages import GithubPagesAdapter
from soymutdb_worker.tasks.static_publish_impl import build_manifest

_TEMPLATE = "https://artifacts.example/soymutdb/{publication_id}/{digest}.tar.gz"


def _artifact(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text("<!doctype html><html></html>", "utf-8")
    build_manifest(root, release_id=1, page_definition_version=None)
    return root


def _adapter(**overrides: Any) -> GithubPagesAdapter:
    kwargs: dict[str, Any] = {
        "token": "tok",
        "repository": "org/repo",
        "artifact_url_template": _TEMPLATE,
    }
    kwargs.update(overrides)
    return GithubPagesAdapter(**kwargs)


# ---------------------------------------------------------------------------
# 1. stage() records the ids the workflow needs.
# ---------------------------------------------------------------------------


def test_stage_populates_publication_id_and_artifact_url(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path / "a")

    ref = _adapter().stage(42, artifact)

    assert ref.metadata["publication_id"] == "42"
    assert ref.metadata["artifact_url"].startswith(
        "https://artifacts.example/soymutdb/42/"
    )
    assert ref.metadata["artifact_url"].endswith(".tar.gz")
    # The digest in the URL is the same one the workflow is asked to verify.
    assert ref.manifest_digest in ref.metadata["artifact_url"]
    assert ref.metadata["manifest_digest"] == ref.manifest_digest


def test_stage_refuses_to_dispatch_without_an_artifact_url(tmp_path: Path) -> None:
    """Ablation: empty metadata produced a workflow run with empty inputs."""
    artifact = _artifact(tmp_path / "a")

    with pytest.raises(RuntimeError, match="artifact URL template"):
        _adapter(artifact_url_template=None).stage(42, artifact)


def test_stage_marks_the_ref_with_the_target_and_identity(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path / "a")

    ref = _adapter().stage(7, artifact)

    assert ref.target == "github_pages"
    assert ref.ref.startswith("github:7:")
    assert ref.artifact_path == str(artifact)


# ---------------------------------------------------------------------------
# 2. promote() dispatches exactly the staged identity.
# ---------------------------------------------------------------------------


def test_promote_dispatches_the_staged_identity(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path / "a")
    adapter = _adapter()
    ref = adapter.stage(42, artifact)

    dispatched: dict[str, Any] = {}

    def _post(url: str, *, headers: dict, body: dict) -> dict:
        dispatched["url"] = url
        dispatched["body"] = body
        return {}

    runs = [
        {"workflow_runs": [{"id": 99, "status": "in_progress"}]},
        {"workflow_runs": [{"id": 99, "status": "completed", "conclusion": "success"}]},
    ]

    def _get(url: str, *, headers: dict) -> dict:
        return runs.pop(0)

    with mock.patch(
        "soymutdb_worker.publication.github_pages.post_json", _post
    ), mock.patch(
        "soymutdb_worker.publication.github_pages.request_json", _get
    ), mock.patch(
        "soymutdb_worker.publication.github_pages.time.sleep", lambda _s: None
    ):
        remote_id = adapter.promote(ref)

    inputs = dispatched["body"]["inputs"]
    assert inputs["publication_id"] == "42"
    assert inputs["artifact_url"] == ref.metadata["artifact_url"]
    assert inputs["manifest_digest"] == ref.manifest_digest
    # No empty input may be dispatched.
    assert all(value for value in inputs.values()), inputs
    assert remote_id == "run:99"


def test_promote_fails_loudly_when_the_workflow_fails(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path / "a")
    adapter = _adapter()
    ref = adapter.stage(42, artifact)

    with mock.patch(
        "soymutdb_worker.publication.github_pages.post_json", lambda *a, **k: {}
    ), mock.patch(
        "soymutdb_worker.publication.github_pages.request_json",
        lambda *a, **k: {
            "workflow_runs": [{"id": 1, "status": "completed", "conclusion": "failure"}]
        },
    ), mock.patch(
        "soymutdb_worker.publication.github_pages.time.sleep", lambda _s: None
    ):
        with pytest.raises(RuntimeError, match="concluded failure"):
            adapter.promote(ref)


# ---------------------------------------------------------------------------
# 3. The promote-time latest-request re-check.
# ---------------------------------------------------------------------------


class _RecordingStore:
    """State store stub that flips the latest-request answer after staging."""

    def __init__(self, *, promote_after_stage: bool) -> None:
        self.transitions: list[tuple[int, str]] = []
        self._promote_after_stage = promote_after_stage
        self.should_promote_calls = 0

    def transition(self, publication_id: int, status: str, **kwargs: Any) -> bool:
        self.transitions.append((publication_id, status))
        return True

    def should_promote(self, publication_id: int) -> bool:
        self.should_promote_calls += 1
        # First call (before staging) says yes; the second (immediately before
        # promote) reflects a newer request when configured to.
        if self.should_promote_calls == 1:
            return True
        return not self._promote_after_stage

    def record_published(self, publication_id: int, **kwargs: Any) -> bool:
        self.transitions.append((publication_id, "published"))
        self.published_kwargs = kwargs
        return True


class _StubAdapter:
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


def _run(kwargs: dict[str, Any], store: _RecordingStore, adapter: _StubAdapter):
    import soymutdb_worker.tasks.static_publish_impl as impl

    with mock.patch.object(impl, "PublicationStateStore", lambda: store), mock.patch.object(
        impl, "get_adapter", lambda target: adapter
    ), mock.patch.object(
        impl, "build_static_tree", lambda **kw: (Path("/tmp/artifact"), "d" * 64)
    ):
        return impl.run_publication(kwargs)


def test_promote_is_skipped_when_a_newer_request_arrived_during_staging() -> None:
    """Ablation: without the second check the stale artifact is promoted."""
    store = _RecordingStore(promote_after_stage=True)
    adapter = _StubAdapter()

    result = _run(
        {"publication_id": 1, "target": "local", "release_id": 1},
        store,
        adapter,
    )

    assert result["status"] == "superseded"
    assert adapter.promoted == 0
    # The second check happened.
    assert store.should_promote_calls == 2
    assert (1, "superseded") in store.transitions


def test_promote_proceeds_when_this_is_still_the_latest_request() -> None:
    store = _RecordingStore(promote_after_stage=False)
    adapter = _StubAdapter()

    result = _run(
        {"publication_id": 1, "target": "local", "release_id": 1},
        store,
        adapter,
    )

    assert result["status"] == "published"
    assert adapter.promoted == 1


def test_a_publication_without_build_output_is_recorded_as_failed() -> None:
    """No synthetic artifact: a request with no SSG output must fail.

    This drives the *real* ``build_static_tree`` (only the state store and the
    adapter are stubbed), so it is the end-to-end shape of the fail-closed
    behaviour: no build output -> ``failed``, nothing promoted.
    """
    import soymutdb_worker.tasks.static_publish_impl as impl

    store = _RecordingStore(promote_after_stage=False)
    adapter = _StubAdapter()

    with mock.patch.object(impl, "PublicationStateStore", lambda: store), mock.patch.object(
        impl, "get_adapter", lambda target: adapter
    ):
        result = impl.run_publication(
            {"publication_id": 2, "target": "local", "release_id": 1}
        )

    assert result["status"] == "failed"
    assert "build output" in result["error"]
    assert adapter.promoted == 0
    assert (2, "failed") in store.transitions


# ---------------------------------------------------------------------------
# 4. The Cloudflare uploader sends bytes, not paths.
# ---------------------------------------------------------------------------


def test_cloudflare_collect_files_returns_readable_paths(tmp_path: Path) -> None:
    from soymutdb_worker.publication.cloudflare_pages import _collect_files

    artifact = _artifact(tmp_path / "cf")
    (artifact / "assets").mkdir(exist_ok=True)
    (artifact / "assets" / "app.js").write_text("export {};\n", "utf-8")

    files = _collect_files(artifact)

    # Paths (so bytes can be read), relative-ordered, manifest excluded.
    assert all(isinstance(p, Path) for p in files)
    assert [p.relative_to(artifact).as_posix() for p in files] == [
        "assets/app.js",
        "index.html",
    ]
    assert all(p.is_file() for p in files)


def test_cloudflare_upload_sends_real_file_bytes(tmp_path: Path) -> None:
    """Ablation: the body used to carry absolute path strings, no content."""
    from soymutdb_worker.publication import cloudflare_pages as cf

    artifact = _artifact(tmp_path / "cf")
    marker = "UNIQUE-ARTIFACT-BYTES-12345"
    (artifact / "index.html").write_text(
        f"<!doctype html><html>{marker}</html>", "utf-8"
    )
    files = cf._collect_files(artifact)

    captured: dict[str, Any] = {}

    def _post(url: str, *, headers: dict, fields: dict, files: list, timeout: int = 300):
        captured["url"] = url
        captured["fields"] = fields
        captured["files"] = files
        return {"result": {"id": "dep-1"}}

    with mock.patch.object(cf, "post_multipart", _post):
        deployment_id = cf._upload("https://api.example/x", {}, {"files": {}}, files, artifact)

    assert deployment_id == "dep-1"
    assert captured["files"], "expected file parts"
    # Every part carries content bytes and a content type, never a path.
    for field_name, filename, content, content_type in captured["files"]:
        assert field_name == "files"
        assert isinstance(content, bytes) and content
        assert content_type
        assert not filename.startswith("/"), filename
    payloads = [part[2] for part in captured["files"]]
    assert any(marker.encode() in payload for payload in payloads)
    # The manifest travels as a field, not as a path list.
    assert "files" in json.loads(captured["fields"]["manifest"]) or "manifest" in captured["fields"]


def test_multipart_encoding_includes_file_content_and_boundary() -> None:
    from soymutdb_worker.publication.http import _encode_multipart

    body = _encode_multipart(
        {"manifest": '{"a":1}'},
        [("files", "index.html", b"<html>hi</html>", "text/html; charset=utf-8")],
        "BOUNDARY123",
    )

    assert b"--BOUNDARY123" in body
    assert body.rstrip().endswith(b"--BOUNDARY123--")
    assert b'name="manifest"' in body
    assert b'filename="index.html"' in body
    assert b"Content-Type: text/html; charset=utf-8" in body
    assert b"<html>hi</html>" in body
