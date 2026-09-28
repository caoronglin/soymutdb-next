"""Release pointer lifecycle tasks.

Currently this is a minimal consumer for the ``release_pointer_changed``
outbox event.  It acknowledges the pointer transition and logs the event so
the transactional outbox never dispatches an empty task name.

Later phases may extend this task to invalidate release-aware caches, refresh
the static pointer, or notify subscribers; the event payload is intentionally
plain JSON so it can grow without a schema break.
"""

from __future__ import annotations

import logging
from typing import Any

from soymutdb_worker.main import celery_app
from soymutdb_worker.shared import RELEASE_POINTER_CHANGED_TASK
from soymutdb_worker.utils.wecom_bot import send_table as send_wecom_table

logger = logging.getLogger(__name__)


@celery_app.task(
    name=RELEASE_POINTER_CHANGED_TASK,
    queue="default",
)
def refresh_release_pointer(**kwargs: Any) -> dict[str, Any]:
    """Acknowledge an active-release pointer transition.

    Args are forwarded as-is for audit/logging.  The task intentionally does
    not perform network I/O; cache invalidation can be added behind the same
    contract once release-aware caches exist.
    """
    release_id = kwargs.get("release_id")
    previous_release_id = kwargs.get("previous_release_id")
    logger.info(
        "release_pointer_changed",
        release_id=release_id,
        previous_release_id=previous_release_id,
        request_id=kwargs.get("request_id"),
    )
    # Optional group-bot notice. The payload contains release identifiers only;
    # the admin URL remains the authenticated source of the full release table.
    send_wecom_table(
        "SoyMutDB 发布版本已切换",
        [
            ("当前版本", release_id or "—"),
            ("上一版本", previous_release_id or "—"),
            ("事件", "active_release_changed"),
        ],
    )
    return kwargs
