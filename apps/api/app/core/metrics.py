"""Prometheus metrics collection."""

from __future__ import annotations

from prometheus_client import Counter, Histogram, make_asgi_app

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


def get_metrics_app() -> object:
    """Return the Prometheus ASGI metrics app mounted at ``/metrics``."""
    return make_asgi_app()
