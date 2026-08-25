"""Prometheus metrics for SoyMutDB Celery workers.

Exposes a minimal ``/metrics`` HTTP endpoint (port 9808, container network
only — never published to the host) with:

  - ``soymutdb_worker_up``                  worker/beat process liveness
  - ``soymutdb_worker_tasks_total{queue}``  tasks finished successfully
  - ``soymutdb_worker_task_failures_total`` tasks that failed
  - ``soymutdb_worker_queue_depth{queue}``  broker backlog per queue (LLEN)

Prefork support
---------------
Celery's default ``prefork`` pool runs tasks in forked children, so plain
process-local counters would only ever reflect the process serving
``/metrics``.  We use ``prometheus_client`` multi-process mode instead:

  1. ``PROMETHEUS_MULTIPROC_DIR`` is set at import time (before any metric
     object is created), so counters/histograms written by prefork children
     land in per-pid ``*.db`` files.
  2. ``start_metrics_server()`` (invoked from the ``worker_ready`` /
     ``beat_init`` signals — i.e. in the main process, *after* children were
     forked) serves those files aggregated via ``MultiProcessCollector``.

The queue-depth collector thread also runs in the main process only.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import cast

# Must happen before prometheus_client creates any metric object.
_PROMETHEUS_MULTIPROC_DIR: str = os.environ.setdefault(
    "PROMETHEUS_MULTIPROC_DIR", "/tmp/prometheus_multiproc"
)

from prometheus_client import (  # noqa: E402
    CollectorRegistry,
    Counter,
    Gauge,
    multiprocess,
    start_http_server,
)

logger = logging.getLogger(__name__)

# Port for the /metrics endpoint (container network only; compose uses
# ``expose`` so it is never reachable from the host).
METRICS_PORT: int = int(os.environ.get("SOYMUTDB_WORKER_METRICS_PORT", "9808"))

# The six runtime queues (contract: packages/jobs-py + compose worker commands).
QUEUES: tuple[str, ...] = ("ingest", "export", "stats", "cleanup", "blast", "default")

# ---------------------------------------------------------------------------
# Metrics (registered on the default registry; writes go to multiproc files)
# ---------------------------------------------------------------------------
# Multi-process mode opens per-pid files as soon as a metric object is
# created, so the directory must exist before any metric is instantiated.
os.makedirs(_PROMETHEUS_MULTIPROC_DIR, exist_ok=True)

TASKS_TOTAL = Counter(
    "soymutdb_worker_tasks_total",
    "Number of Celery tasks finished successfully",
    ["queue"],
)

TASK_FAILURES_TOTAL = Counter(
    "soymutdb_worker_task_failures_total",
    "Number of Celery tasks that failed",
    ["queue"],
)

WORKER_UP = Gauge(
    "soymutdb_worker_up",
    "1 while the worker/beat process is running, 0 otherwise",
)

QUEUE_DEPTH = Gauge(
    "soymutdb_worker_queue_depth",
    "Number of messages waiting in the Celery broker queue (LLEN)",
    ["queue"],
)

_started = False
_start_lock = threading.Lock()


def _is_redis_broker(broker_url: str) -> bool:
    """Return whether queue-depth collection can use the Redis client."""
    return broker_url.partition(":")[0].lower() in {"redis", "rediss"}


def _collect_queue_depth(broker_url: str, interval: float = 15.0) -> None:
    """Background loop: publish broker queue depths every ``interval`` seconds.

    Runs in the main process.  A failed probe publishes ``-1`` so dashboards
    can distinguish "empty" (0) from "collector broken" (-1) without ever
    triggering the backlog alert.
    """
    try:
        import redis  # noqa: PLC0415 - deferred; redis is a hard dependency anyway
    except ImportError:  # pragma: no cover - defensive
        logger.warning("queue_depth_collector_disabled_redis_missing")
        return
    # ``Redis.from_url`` (sync client) keeps the type checker on the sync path.
    client = redis.Redis.from_url(broker_url, socket_connect_timeout=5, socket_timeout=5)
    while True:
        try:
            for queue in QUEUES:
                try:
                    depth = cast(int, client.llen(queue))
                    QUEUE_DEPTH.labels(queue=queue).set(depth)
                except Exception:
                    QUEUE_DEPTH.labels(queue=queue).set(-1)
        except Exception:
            logger.exception("queue_depth_collect_error")
        time.sleep(interval)


def start_metrics_server(broker_url: str | None = None) -> None:
    """Start the ``/metrics`` HTTP server and queue-depth collector (idempotent).

    Called from the ``worker_ready`` / ``beat_init`` signals so the server and
    the queue-depth thread live in the main process only (after prefork
    children have been forked — they inherit the ``PROMETHEUS_MULTIPROC_DIR``
    environment variable and write their own counters to per-pid files).
    """
    global _started
    with _start_lock:
        if _started:
            return
        os.makedirs(_PROMETHEUS_MULTIPROC_DIR, exist_ok=True)
        registry = CollectorRegistry()
        registry.register(multiprocess.MultiProcessCollector(registry))
        start_http_server(METRICS_PORT, registry=registry)
        WORKER_UP.set(1)
        if broker_url and _is_redis_broker(broker_url):
            thread = threading.Thread(
                target=_collect_queue_depth,
                args=(broker_url,),
                name="queue-depth-collector",
                daemon=True,
            )
            thread.start()
        elif broker_url:
            logger.warning(
                "queue_depth_collector_disabled_unsupported_broker",
                extra={"broker_scheme": broker_url.partition(":")[0].lower()},
            )
        _started = True
    logger.info("metrics_server_started", extra={"port": METRICS_PORT})


__all__ = [
    "METRICS_PORT",
    "QUEUES",
    "TASKS_TOTAL",
    "TASK_FAILURES_TOTAL",
    "WORKER_UP",
    "QUEUE_DEPTH",
    "start_metrics_server",
]
