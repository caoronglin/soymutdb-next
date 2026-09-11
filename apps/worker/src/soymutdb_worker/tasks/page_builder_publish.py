"""Durable Page Builder version publication task.

The API validates a version and atomically records a task-shaped outbox event.
This worker performs the narrow lifecycle transition only; multi-target static
artifact deployment remains the explicit StaticPublication workflow.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from soymutdb_worker.main import celery_app
from soymutdb_worker.shared import PAGE_BUILDER_PUBLISH_TASK
from soymutdb_worker.tables import page_definition_versions
from soymutdb_worker.utils.db import get_db


@celery_app.task(name=PAGE_BUILDER_PUBLISH_TASK, queue="default")
def publish_definition(*, page_id: str, version_id: str) -> dict[str, Any]:
    """Transition one validated Page Builder version to published.

    The row is locked before transition. Redelivery after a successful commit
    is a no-op, while missing or non-requested versions fail loudly instead of
    making an invalid lifecycle transition.
    """
    page_uuid = uuid.UUID(page_id)
    version_uuid = uuid.UUID(version_id)
    now = datetime.now(UTC)

    with get_db() as session:
        current = session.execute(
            select(page_definition_versions.c.status)
            .where(
                page_definition_versions.c.id == version_uuid,
                page_definition_versions.c.page_id == page_uuid,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if current is None:
            raise ValueError(f"Page definition version {version_id} not found")
        if current == "published":
            return {
                "page_id": page_id,
                "version_id": version_id,
                "status": "published",
                "changed": False,
            }
        if current != "requested":
            raise ValueError(
                f"Page definition version {version_id} is {current!r}, expected requested"
            )

        result = session.execute(
            update(page_definition_versions)
            .where(
                page_definition_versions.c.id == version_uuid,
                page_definition_versions.c.page_id == page_uuid,
                page_definition_versions.c.status == "requested",
            )
            .values(status="published", published_at=now, updated_at=now)
        )
        if result.rowcount != 1:
            raise RuntimeError(f"Concurrent publication conflict for version {version_id}")

    return {
        "page_id": page_id,
        "version_id": version_id,
        "status": "published",
        "changed": True,
    }


__all__ = ["publish_definition"]
