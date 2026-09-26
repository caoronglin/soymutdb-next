"""Prometheus metrics collection."""

from __future__ import annotations

import os

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    make_asgi_app,
    multiprocess,
)

# The multiprocess metric store must exist before any metric is defined:
# prometheus_client opens a memory-mapped file in PROMETHEUS_MULTIPROC_DIR when a
# multiprocess Gauge/Counter is constructed. The API image's CMD creates it, but
# a management command, a probe, or the runtime smoke that imports `app.main`
# directly would otherwise crash with
# `FileNotFoundError: .../gauge_mostrecent_1.db`.
if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
    os.makedirs(os.environ["PROMETHEUS_MULTIPROC_DIR"], exist_ok=True)

# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #

REQUEST_COUNT = Counter(
    "soymutdb_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "soymutdb_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)

CLICKHOUSE_QUERY_COUNT = Counter(
    "soymutdb_clickhouse_queries_total",
    "Total ClickHouse queries",
    ["operation"],
)

CLICKHOUSE_QUERY_LATENCY = Histogram(
    "soymutdb_clickhouse_query_duration_seconds",
    "ClickHouse query latency in seconds",
    ["operation"],
)

BLAST_JOBS_TOTAL = Counter(
    "soymutdb_blast_jobs_total",
    "Total BLAST jobs submitted",
    ["program", "status"],
)

EXPORT_JOBS_TOTAL = Counter(
    "soymutdb_export_jobs_total",
    "Total export jobs",
    ["format", "status"],
)

CACHE_LOOKUPS_TOTAL = Counter(
    "soymutdb_cache_lookups_total",
    "Redis cache lookups by stable cache name and outcome",
    ["cache", "outcome"],
)
CACHE_WRITE_FAILURES_TOTAL = Counter(
    "soymutdb_cache_write_failures_total",
    "Redis cache write failures",
    ["cache"],
)
DB_POOL_CONNECTIONS = Gauge(
    "soymutdb_db_pool_connections",
    "Per-API-process SQLAlchemy connection pool state",
    ["state"],
)
OUTBOX_EVENTS = Gauge(
    "soymutdb_outbox_events",
    "Transactional outbox rows by lifecycle status",
    ["status"],
    multiprocess_mode="mostrecent",
)
OUTBOX_OLDEST_UNSENT_AGE_SECONDS = Gauge(
    "soymutdb_outbox_oldest_unsent_age_seconds",
    "Age in seconds of the oldest non-sent outbox row",
    multiprocess_mode="mostrecent",
)
OUTBOX_DELIVERY_EXHAUSTED_TOTAL = Counter(
    "soymutdb_outbox_delivery_exhausted_total",
    "Terminal outbox deliveries that exhausted their retry budget",
)
OUTBOX_DISPATCH_TOTAL = Counter(
    "soymutdb_outbox_dispatch_total",
    "Transactional outbox delivery attempts by outcome",
    ["outcome"],
)


def update_db_pool_metrics() -> None:
    """Snapshot an already-initialized SQLAlchemy pool without opening it."""
    from .database import get_db_pool_status

    status = get_db_pool_status()
    if status is None:
        return
    for state, value in status.items():
        DB_POOL_CONNECTIONS.labels(state=state).set(value)


def get_metrics_app() -> object:
    """Return an ASGI exporter, aggregating every Uvicorn worker."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return make_asgi_app(registry=registry)
    return make_asgi_app()
