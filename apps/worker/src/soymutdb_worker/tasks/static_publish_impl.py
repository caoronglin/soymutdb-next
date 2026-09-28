"""Build/validate/publish pipeline behind the static_publish Celery task.

Kept separate from the decorated task so tests can exercise ``run_publication``
without a broker.  The state machine mirrors
``app.services.publication_service`` (``building`` -> ``validating`` ->
``deploying`` -> ``published`` | ``failed`` | ``superseded``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from soymutdb_worker.config import get_setting
from soymutdb_worker.publication import get_adapter

from .publication_store import PublicationStateStore

logger = logging.getLogger(__name__)

#: Root for locally staged immutable trees (worker-side).
DIST_ROOT = Path(get_setting("PUBLICATION_DIST_ROOT", "/tmp/soymutdb-releases"))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(
    artifact_dir: Path,
    *,
    release_id: int,
    page_definition_version: int | None,
) -> str:
    """Write ``manifest.json`` into *artifact_dir* and return its digest.

    The manifest records every relative path + SHA-256, plus release/page/app
    metadata, so it is the single source of truth for immutability checks.
    """
    files: dict[str, str] = {}
    for p in sorted(artifact_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(artifact_dir).as_posix()
        if rel == "manifest.json":
            continue
        files[rel] = _sha256_file(p)
    # The digest is computed over the immutable content only (metadata +
    # files), EXCLUDING the wall-clock ``generated_at`` so the same source
    # always yields the same digest (deterministic manifests).
    digest_input = {
        "schema_version": 1,
        "release_id": release_id,
        "page_definition_version": page_definition_version,
        "application": "soymutdb-next",
        "files": files,
    }
    manifest = {**digest_input, "generated_at": _utcnow_iso()}
    canonical = json.dumps(digest_input, sort_keys=True, separators=(",", ":"))
    (artifact_dir / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", "utf-8"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utcnow_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


class MissingBuildOutput(RuntimeError):
    """Raised when a publication has no real SSG output to publish."""


#: Files without which an artifact cannot be a published site.
_REQUIRED_ARTIFACT_FILES = ("index.html",)


def build_static_tree(
    *,
    release_id: int,
    page_definition_version: int | None,
    build_dir: str | Path | None,
) -> tuple[Path, str]:
    """Stage a *real* SSG build output under ``dist/releases/<release-id>/``.

    ``build_dir`` is the directory an SSG run produced. It is **required**: the
    previous implementation synthesised a single ``index.html`` from an optional
    snapshot whenever no build chain existed, which meant a request could report
    ``published`` while deploying a one-page placeholder — a release that looks
    successful and serves nothing.

    There is deliberately no synthetic fallback. A missing/empty build directory,
    or one without the required entry documents, raises
    :class:`MissingBuildOutput` so the caller records ``failed`` instead of
    promoting an empty tree.
    """
    if build_dir is None or str(build_dir).strip() == "":
        raise MissingBuildOutput(
            "No SSG build output was supplied for this publication; refusing to "
            "publish a synthetic one-page artifact. Wire the site build into the "
            "publication request (outbox `build_dir`) before promoting."
        )
    source = Path(build_dir)
    if not source.is_dir():
        raise MissingBuildOutput(f"SSG build output {source} is not a directory")
    present = {p.name for p in source.iterdir() if p.is_file()}
    missing = [name for name in _REQUIRED_ARTIFACT_FILES if name not in present]
    if missing:
        raise MissingBuildOutput(
            f"SSG build output {source} is missing required file(s): "
            f"{', '.join(sorted(missing))}"
        )

    release_dir = DIST_ROOT / "releases" / str(release_id)
    release_dir.mkdir(parents=True, exist_ok=True)
    staged = release_dir / "staging"
    if staged.exists():
        shutil.rmtree(staged)
    # Copy the build output verbatim; the manifest below is the only file this
    # function adds, so the artifact is byte-identical to the SSG result.
    shutil.copytree(source, staged, symlinks=False)

    digest = build_manifest(
        staged, release_id=release_id, page_definition_version=page_definition_version
    )
    final = DIST_ROOT / "releases" / str(release_id) / digest
    if final.exists():
        shutil.rmtree(final)
    staged.rename(final)
    return final, digest


#: Upper bound on a fetched build artifact, so a bad URL cannot fill the disk.
MAX_ARTIFACT_BYTES = int(get_setting("PUBLICATION_MAX_ARTIFACT_BYTES", 512 * 1024 * 1024))


class ArtifactFetchError(RuntimeError):
    """Raised when the build artifact cannot be materialised."""


def materialize_artifact(
    artifact_url: str | None,
    *,
    workdir: Path | None = None,
) -> Path | None:
    """Fetch *artifact_url* and return a directory containing the build output.

    Returns ``None`` when no URL was supplied, so the caller's
    :func:`build_static_tree` raises ``MissingBuildOutput`` and the publication
    is recorded ``failed`` — the pipeline never substitutes a synthetic tree.

    Supported forms:

    * ``http(s)://…`` — downloaded with a hard byte ceiling, then extracted.
    * ``file:///…`` — a directory (used directly) or an archive (extracted).
    * a plain absolute path — same as ``file://``, for a co-located target.

    Archives may be ``.tar``/``.tar.gz``/``.tgz``. Anything else is treated as an
    already-extracted directory reference and refused if it is not one, so a
    misconfigured URL fails loudly instead of publishing nothing.
    """
    if artifact_url is None or not str(artifact_url).strip():
        return None
    ref = str(artifact_url).strip()
    work = workdir or Path(tempfile.mkdtemp(prefix="soymutdb-artifact-"))
    # A caller-supplied work directory may not exist yet; the download below
    # opens a file inside it, so create it rather than failing with ENOENT.
    work.mkdir(parents=True, exist_ok=True)

    lowered = ref.lower()
    if lowered.startswith(("http://", "https://")):
        archive = work / "artifact.download"
        _download_bounded(ref, archive)
        return _extract_or_directory(archive, work)

    if lowered.startswith("file://"):
        ref = ref[len("file://"):]

    source = Path(ref)
    if source.is_dir():
        # Already-extracted output (co-located target).
        return source
    if source.is_file():
        return _extract_or_directory(source, work)
    raise ArtifactFetchError(f"build artifact {artifact_url!r} does not exist")


def _download_bounded(url: str, destination: Path) -> None:
    """Stream *url* to *destination*, refusing anything over the byte ceiling."""
    written = 0
    try:
        with urllib.request.urlopen(url, timeout=300) as resp:  # noqa: S310 - explicit scheme check by caller
            with open(destination, "wb") as fh:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_ARTIFACT_BYTES:
                        raise ArtifactFetchError(
                            f"build artifact exceeds the {MAX_ARTIFACT_BYTES} byte ceiling"
                        )
                    fh.write(chunk)
    except ArtifactFetchError:
        raise
    except Exception as exc:
        raise ArtifactFetchError(f"could not fetch build artifact: {exc}") from exc


def _extract_or_directory(source: Path, work: Path) -> Path:
    """Extract a tar archive into *work*, or return *source* if it is a dir.

    The archive type is sniffed from the *content* (``tarfile.is_tarfile``)
    rather than the filename: an artifact URL is frequently extension-less, and
    an extension check would reject a perfectly valid download.
    """
    if source.is_dir():
        return source
    if not tarfile.is_tarfile(source):
        raise ArtifactFetchError(
            f"build artifact {source.name!r} is neither a directory nor a tar archive"
        )
    target = work / "extracted"
    target.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(source, "r:*") as tar:
            _safe_extract(tar, target)
    except ArtifactFetchError:
        raise
    except Exception as exc:
        raise ArtifactFetchError(f"could not extract build artifact: {exc}") from exc
    return target


def _safe_extract(tar: tarfile.TarFile, target: Path) -> None:
    """Extract *tar* into *target*, rejecting path traversal and links.

    A build artifact is fetched from storage, but an archive with ``../`` members
    or absolute paths would still escape the staging directory, so members are
    validated before extraction rather than trusted.
    """
    resolved_target = target.resolve()
    for member in tar.getmembers():
        if member.issym() or member.islnk() or member.isdev():
            raise ArtifactFetchError(
                f"build artifact contains an unsupported member: {member.name!r}"
            )
        member_path = (target / member.name).resolve()
        if not str(member_path).startswith(str(resolved_target)):
            raise ArtifactFetchError(
                f"build artifact member escapes the target directory: {member.name!r}"
            )
    tar.extractall(target, filter="data")


def run_publication(kwargs: dict[str, Any]) -> dict[str, Any]:
    publication_id = kwargs["publication_id"]
    target = kwargs["target"]
    release_id = kwargs["release_id"]
    page_definition_version = kwargs.get("page_definition_version")

    store = PublicationStateStore()
    store.transition(publication_id, "building")

    try:
        # Prefer an explicit local build directory (co-located SSG); otherwise
        # fetch the immutable artifact the request recorded. Either way the
        # result is real build output or an exception.
        build_dir = kwargs.get("build_dir")
        if not build_dir and kwargs.get("build_artifact_url"):
            build_dir = materialize_artifact(kwargs["build_artifact_url"])
        artifact, digest = build_static_tree(
            release_id=release_id,
            page_definition_version=page_definition_version,
            build_dir=build_dir,
        )
    except Exception as exc:
        store.transition(publication_id, "failed", error_message=str(exc))
        logger.warning(
            "static_publish_build_failed publication_id=%s error=%s",
            publication_id,
            exc,
        )
        return {"publication_id": publication_id, "status": "failed", "error": str(exc)}

    store.transition(
        publication_id,
        "validating",
        manifest_digest=digest,
        artifact_url=str(artifact),
    )

    # Stale-job guard: never promote if a newer request superseded this one.
    if not store.should_promote(publication_id):
        store.transition(publication_id, "superseded")
        logger.info(
            "static_publish_superseded",
            publication_id=publication_id,
            target=target,
        )
        return {"publication_id": publication_id, "status": "superseded"}

    adapter = get_adapter(target)
    store.transition(publication_id, "deploying")

    try:
        deployment = adapter.stage(publication_id, artifact)
        evidence = adapter.verify(deployment)
        if not evidence.ok:
            raise RuntimeError(f"validation failed: {evidence.error}")
        # Re-check the latest-request pointer immediately before promoting. The
        # earlier check happened before staging, which can involve network I/O;
        # a newer request landing in that window would otherwise be overwritten
        # by this now-stale artifact.
        if not store.should_promote(publication_id):
            store.transition(publication_id, "superseded")
            logger.info(
                "static_publish_superseded_at_promote publication_id=%s",
                publication_id,
            )
            return {"publication_id": publication_id, "status": "superseded"}
        remote_id = adapter.promote(deployment)
    except Exception as exc:
        store.transition(publication_id, "failed", error_message=str(exc))
        return {"publication_id": publication_id, "status": "failed", "error": str(exc)}

    store.record_published(publication_id, remote_id=remote_id, evidence=evidence.detail)
    logger.info(
        "static_publish_published",
        publication_id=publication_id,
        target=target,
        remote_id=remote_id,
    )
    return {
        "publication_id": publication_id,
        "status": "published",
        "remote_id": remote_id,
        "digest": digest,
    }
