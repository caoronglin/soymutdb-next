"""Notification tasks and trigger helpers (D2).

Two layers:

- :func:`create_notification` — a Celery task (queue ``default``) that
  writes one notification row through the narrow
  :class:`~soymutdb_worker.repositories.NotifyStore`.  It is idempotent:
  the store keys on ``user_id + link`` (the link uniquely identifies the
  originating job), so a redelivered event never duplicates a
  notification.
- :func:`notify_completed` / :func:`notify_failed` — helper functions
  called from the job tasks right after ``mark_succeeded`` /
  ``mark_failed``.  They resolve the job's owner from the job row (jobs
  without a ``user_id`` are skipped), build the title/body/link, insert
  the notification (synchronously, same narrow store), and optionally
  fire a plyer desktop notification.

The helpers are intentionally fault-tolerant: any failure (job row gone,
DB hiccup, plyer missing) is logged at warning level and never fails the
underlying job task.
"""

from __future__ import annotations

import logging
import uuid

from celery import Task

from soymutdb_worker.main import celery_app
from soymutdb_worker.repositories import NotifyStore
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.notify import desktop_notify

logger = logging.getLogger(__name__)

#: Canonical task name (queue ``default`` via ``task_default_queue``).
CREATE_NOTIFICATION_TASK = "soymutdb_worker.tasks.notifications.create_notification"

#: App route per job kind — the link the user opens from the bell.
_JOB_ROUTES: dict[str, str] = {
    "blast": "/blast/jobs",
    "fastp": "/analyses",
    "scanpy": "/analyses",
    "gwas": "/gwas/jobs",
}

#: Human label per job kind (worker-side copy; the UI translates types).
_JOB_LABELS: dict[str, str] = {
    "blast": "BLAST",
    "fastp": "FASTP QC",
    "scanpy": "Scanpy",
    "gwas": "GWAS",
}

#: Max error excerpt persisted in the notification body.
_MAX_ERROR_BODY = 200


# ---------------------------------------------------------------------------
# Notification type vocabulary (mirrors the API's string types)
# ---------------------------------------------------------------------------

_JOB_TYPES = {
    ("blast", True): "blast_completed",
    ("blast", False): "blast_failed",
    ("fastp", True): "analysis_completed",
    ("fastp", False): "analysis_failed",
    ("scanpy", True): "analysis_completed",
    ("scanpy", False): "analysis_failed",
    ("gwas", True): "gwas_completed",
    ("gwas", False): "gwas_failed",
}


def _short(job_id: str) -> str:
    """Truncated job id for message bodies (uuid prefixes are enough)."""
    return job_id[:8]


def _build_message(
    kind: str,
    job_id: str,
    *,
    succeeded: bool,
    error: str | None = None,
) -> tuple[str, str]:
    """Return ``(title, body)`` for a job outcome notification."""
    label = _JOB_LABELS.get(kind, kind)
    if succeeded:
        title = f"{label} job completed"
        body = f"{label} job {_short(job_id)}… finished successfully."
    else:
        title = f"{label} job failed"
        body = f"{label} job {_short(job_id)}… failed."
        if error:
            body = f"{body} {error[:_MAX_ERROR_BODY]}"
    return title, body


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------


def _insert_notification(
    *,
    user_id: str,
    type: str,
    title: str,
    body: str,
    link: str | None = None,
) -> bool:
    """Shared idempotent insert (used by the task and the helpers)."""
    with get_db() as session:
        return NotifyStore(session).create(
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            link=link,
        )


@celery_app.task(
    bind=True,
    name=CREATE_NOTIFICATION_TASK,
    queue="default",
)
def create_notification(
    self: Task,
    *,
    user_id: str,
    type: str,
    title: str,
    body: str,
    link: str | None = None,
) -> bool:
    """Write one notification row (idempotent on user + link)."""
    return _insert_notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        link=link,
    )


# ---------------------------------------------------------------------------
# Trigger helpers (called from job tasks after mark_succeeded/mark_failed)
# ---------------------------------------------------------------------------


def notify_completed(job_id: str | uuid.UUID, *, kind: str) -> None:
    """Notify the job owner that *kind* job *job_id* finished successfully."""
    _dispatch(str(job_id), kind=kind, succeeded=True)


def notify_failed(
    job_id: str | uuid.UUID,
    *,
    kind: str,
    error: str | None = None,
) -> None:
    """Notify the job owner that *kind* job *job_id* failed."""
    _dispatch(str(job_id), kind=kind, succeeded=False, error=error)


def _dispatch(
    job_id: str,
    *,
    kind: str,
    succeeded: bool,
    error: str | None = None,
) -> None:
    """Resolve the owner, insert the row, and optionally desktop-notify.

    Never raises: notifications are best-effort.  A missing job row /
    missing ``user_id`` silently skips (anonymous jobs get no
    notification).
    """
    try:
        with get_db() as session:
            store = NotifyStore(session)
            user_id = store.get_job_user_id(job_id, kind)
            if not user_id:
                logger.info(
                    "notify: job %s (%s) has no owner; skipping notification",
                    job_id,
                    kind,
                )
                return
            ntype = _JOB_TYPES[(kind, succeeded)]
            title, body = _build_message(kind, job_id, succeeded=succeeded, error=error)
            link = f"{_JOB_ROUTES[kind]}/{job_id}"
            inserted = store.create(
                user_id=user_id,
                type=ntype,
                title=title,
                body=body,
                link=link,
            )
            if inserted:
                logger.info(
                    "notify: %s notification created for user %s (job %s)",
                    ntype,
                    user_id,
                    job_id,
                )
            else:
                logger.info(
                    "notify: duplicate %s notification for job %s (skipped)",
                    ntype,
                    job_id,
                )
    except Exception as exc:  # never fail the job task over notifications
        logger.warning(
            "notify: failed to dispatch %s notification for job %s: %s",
            "completed" if succeeded else "failed",
            job_id,
            exc,
        )
        return

    # Optional desktop channel (plyer) — best-effort, gated by env flag.
    try:
        label = _JOB_LABELS.get(kind, kind)
        title, body = _build_message(kind, job_id, succeeded=succeeded, error=error)
        desktop_notify(f"[SoyMutDB] {title}", body)
    except Exception:  # pragma: no cover - defensive
        logger.warning("notify: desktop notification failed for job %s", job_id, exc_info=True)
