"""SoyMutDB Celery worker application.

Fixes vs. quartz reference:
- beat_schedule: ``soymutdb_worker.tasks.exports.cleanup_old_exports`` →
  ``soymutdb_worker.tasks.export.cleanup_old_exports`` (module is ``export``,
  not ``exports``).
- autodiscover: removed non-existent ``indexing`` module; ``notifications``
  was re-added in D2 (notification centre task, queue ``default``).
- task_routes: expanded to the seven runtime queues (ingest, export, stats,
  cleanup, blast, analyses, default).
"""

from __future__ import annotations

import fnmatch

from celery import Celery
from celery.signals import beat_init, task_failure, task_success, worker_ready

from soymutdb_worker import metrics as worker_metrics
from soymutdb_worker.config import get_setting

# ---------------------------------------------------------------------------
# Broker / backend configuration
# ---------------------------------------------------------------------------

BROKER_URL = get_setting("CELERY_BROKER_URL", "redis://localhost:6379/1")
RESULT_BACKEND = get_setting("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
# Celery result TTL (seconds): SOYMUTDB_CELERY_RESULT_EXPIRES / CELERY_RESULT_EXPIRES,
# default 7 days (within the recommended 1-7 day window).  Production compose
# sets the canonical SOYMUTDB_ name explicitly.
RESULT_EXPIRES = int(get_setting("CELERY_RESULT_EXPIRES", "604800"))

celery_app = Celery(
    "soymutdb_worker",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=[
        "soymutdb_worker.tasks.blast",
        "soymutdb_worker.tasks.export",
        "soymutdb_worker.tasks.ingest",
        "soymutdb_worker.tasks.stats",
        "soymutdb_worker.tasks.cleanup",
        "soymutdb_worker.tasks.expression",
        "soymutdb_worker.tasks.homolog",
        "soymutdb_worker.tasks.gwas",
        "soymutdb_worker.tasks.static_pages",
        "soymutdb_worker.tasks.analyses",
        "soymutdb_worker.tasks.email",
    ],
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Task execution limits
    task_track_started=True,
    task_time_limit=3600 * 24,  # 24 hours hard limit
    task_soft_time_limit=3600 * 23,  # 23 hours soft limit
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    # Result expiry (configurable TTL; 1-7 days recommended)
    result_expires=RESULT_EXPIRES,
    # Reliability
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Beat schedule (fixed module references)
    beat_schedule={
        "update-release-stats": {
            "task": "soymutdb_worker.tasks.stats.update_release_stats",
            "schedule": 3600,  # every hour
        },
        "cleanup-old-exports": {
            "task": "soymutdb_worker.tasks.export.cleanup_old_exports",
            "schedule": 86400,  # daily
        },
        "cleanup-expired-blast-jobs": {
            "task": "soymutdb_worker.tasks.cleanup.cleanup_expired_blast_jobs",
            "schedule": 3600,  # every hour
        },
        "cleanup-temp-files": {
            "task": "soymutdb_worker.tasks.cleanup.cleanup_temp_files",
            "schedule": 3600 * 6,  # every 6 hours
        },
    },
    # 8 queue routes
    task_routes={
        "soymutdb_worker.tasks.ingest.*": {"queue": "ingest"},
        "soymutdb_worker.tasks.expression.*": {"queue": "ingest"},
        "soymutdb_worker.tasks.homolog.*": {"queue": "ingest"},
        "soymutdb_worker.tasks.blast.*": {"queue": "blast"},
        "soymutdb_worker.tasks.export.*": {"queue": "export"},
        "soymutdb_worker.tasks.stats.*": {"queue": "stats"},
        "soymutdb_worker.tasks.static_pages.*": {"queue": "stats"},
        "soymutdb_worker.tasks.cleanup.*": {"queue": "cleanup"},
        "soymutdb_worker.tasks.analyses.*": {"queue": "analyses"},
        "soymutdb_worker.tasks.gwas.*": {"queue": "analyses"},
        # Email tasks intentionally have NO route: they run on the default queue.
    },
    task_default_queue="default",
)

# ---------------------------------------------------------------------------
# Task auto-discovery
# ---------------------------------------------------------------------------

# Only discover modules that actually exist (removed indexing; notifications
# restored in D2).
celery_app.autodiscover_tasks(
    [
        "soymutdb_worker.tasks.ingest",
        "soymutdb_worker.tasks.blast",
        "soymutdb_worker.tasks.export",
        "soymutdb_worker.tasks.stats",
        "soymutdb_worker.tasks.cleanup",
        "soymutdb_worker.tasks.email",
        "soymutdb_worker.tasks.expression",
        "soymutdb_worker.tasks.homolog",
        "soymutdb_worker.tasks.gwas",
        "soymutdb_worker.tasks.notifications",
        "soymutdb_worker.tasks.static_pages",
    ]
)


# ---------------------------------------------------------------------------
# Prometheus metrics hooks
# ---------------------------------------------------------------------------
# Signal handlers live in the main process.  ``task_success`` / ``task_failure``
# fire inside the prefork child that ran the task; thanks to
# ``PROMETHEUS_MULTIPROC_DIR`` (set in soymutdb_worker.metrics at import time)
# their counters land in per-pid files aggregated by the /metrics endpoint.
# ---------------------------------------------------------------------------


def _queue_of_task(task_name: str) -> str:
    """Resolve the routing queue of a task from ``task_routes``."""
    if not task_name:
        return "unknown"
    for pattern, opts in celery_app.conf.task_routes.items():
        if fnmatch.fnmatch(task_name, pattern):
            return opts.get("queue", "default")
    return "default"


@worker_ready.connect
def _start_metrics_on_worker_ready(**kwargs: object) -> None:
    worker_metrics.start_metrics_server(broker_url=BROKER_URL)


@beat_init.connect
def _start_metrics_on_beat_init(**kwargs: object) -> None:
    worker_metrics.start_metrics_server(broker_url=BROKER_URL)


@task_success.connect
def _observe_task_success(sender: str | None = None, **kwargs: object) -> None:
    worker_metrics.TASKS_TOTAL.labels(queue=_queue_of_task(sender or "")).inc()


@task_failure.connect
def _observe_task_failure(sender: str | None = None, **kwargs: object) -> None:
    worker_metrics.TASK_FAILURES_TOTAL.labels(queue=_queue_of_task(sender or "")).inc()


if __name__ == "__main__":
    celery_app.start()
