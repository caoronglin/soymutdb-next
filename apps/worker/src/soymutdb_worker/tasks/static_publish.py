"""Immutable multi-target static publication worker task (Phase 3).

Replaces the Phase 1 placeholder with the full pipeline:

1. build     — generate a fresh static tree + manifest (invoked via the SSG
   scripts / subprocess or an in-process builder), landing in
   ``dist/releases/<release-id>/<digest>/``.
2. validate  — verify manifest and static-tree invariants.
3. promote   — dispatch the target adapter (stage -> verify -> promote),
   guarded by the target lease / latest-request check so a stale job never
   replaces a newer release.

All API state changes go through :class:`PublicationStateStore` (narrow
SQLAlchemy Core access).  The task is idempotent: a redelivered event re-runs
build/validate safely and only promotes when still the latest request.
"""

from __future__ import annotations

import logging
from typing import Any

from soymutdb_worker.main import celery_app
from soymutdb_worker.shared import STATIC_PUBLISH_TASK

logger = logging.getLogger(__name__)


@celery_app.task(
    name=STATIC_PUBLISH_TASK,
    queue="stats",
)
def build_static_release(**kwargs: Any) -> dict[str, Any]:
    """Build, validate, and publish an immutable static release.

    Args are the outbox-contract kwargs produced by ``request_publication``:
    ``publication_id``, ``target``, ``release_id``, ``page_definition_version``,
    ``request_id`` — plus ``build_dir``, the directory a real SSG run produced.

    ``build_dir`` is **required**. The API does not supply it yet (the transport
    for a worker that does not share a filesystem with the SSG run is still
    unimplemented), so a publication currently fails closed with
    ``MissingBuildOutput`` instead of publishing a synthetic placeholder page.
    That is deliberate: a failed publication is recoverable, a "successful" one
    that serves nothing is not.
    """
    from soymutdb_worker.tasks.static_publish_impl import run_publication

    return run_publication(kwargs)
