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


def build_static_tree(
    *,
    release_id: int,
    page_definition_version: int | None,
    snapshot: dict | None,
) -> tuple[Path, str]:
    """Generate a fresh immutable static tree under
    ``dist/releases/<release-id>/<digest>/``.

    In the absence of a live SSG chain (offline/CI), synthesises a minimal
    tree from the supplied snapshot; a real deployment runs the SSG scripts
    and then calls :func:`build_manifest`.
    """
    release_dir = DIST_ROOT / "releases" / str(release_id)
    release_dir.mkdir(parents=True, exist_ok=True)
    staged = release_dir / "staging"
    if staged.exists():
        shutil.rmtree(staged)
    staged.mkdir(parents=True)
    if snapshot is not None:
        (staged / "data").mkdir(parents=True, exist_ok=True)
        (staged / "data" / "content.json").write_text(
            json.dumps(snapshot, sort_keys=True), "utf-8"
        )
    # A minimal index so ``verify_manifest`` has at least one tracked file.
    (staged / "index.html").write_text(
        "<!doctype html><html><head><title>SoyMutDB</title></head>"
        f"<body>release {release_id}</body></html>",
        "utf-8",
    )
    digest = build_manifest(
        staged, release_id=release_id, page_definition_version=page_definition_version
    )
    final = DIST_ROOT / "releases" / str(release_id) / digest
    if final.exists():
        shutil.rmtree(final)
    staged.rename(final)
    return final, digest


def run_publication(kwargs: dict[str, Any]) -> dict[str, Any]:
    publication_id = kwargs["publication_id"]
    target = kwargs["target"]
    release_id = kwargs["release_id"]
    page_definition_version = kwargs.get("page_definition_version")

    store = PublicationStateStore()
    store.transition(publication_id, "building")

    try:
        artifact, digest = build_static_tree(
            release_id=release_id,
            page_definition_version=page_definition_version,
            snapshot=kwargs.get("snapshot"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        store.transition(publication_id, "failed", error_message=str(exc))
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
