"""Tests for the worker Prometheus metrics module.

``prometheus_client`` caches ``PROMETHEUS_MULTIPROC_DIR`` at first import and
pytest deletes per-test ``tmp_path`` directories afterwards, which would break
later ``MultiProcessCollector`` calls.  A single process-wide directory is
therefore set at module import time (before any ``soymutdb_worker`` import).
"""

from __future__ import annotations

import os
from types import SimpleNamespace

_TEST_MP_DIR = "/tmp/soymutdb_prometheus_tests"
os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", _TEST_MP_DIR)
os.environ.setdefault("SOYMUTDB_WORKER_METRICS_PORT", "0")


def test_metrics_module_exposes_expected_metrics():
    from prometheus_client import CollectorRegistry, generate_latest, multiprocess

    from soymutdb_worker import metrics

    metrics.TASKS_TOTAL.labels(queue="blast").inc()
    metrics.TASK_FAILURES_TOTAL.labels(queue="blast").inc()
    metrics.TASK_DURATION.labels(queue="blast", state="success").observe(0.5)
    metrics.WORKER_UP.set(1)
    metrics.QUEUE_DEPTH.labels(queue="default").set(3)

    # In multi-process mode metrics live in per-pid files; aggregate them
    # the same way start_metrics_server() does.
    registry = CollectorRegistry()
    registry.register(multiprocess.MultiProcessCollector(registry))
    text = generate_latest(registry).decode()
    # prometheus-client 0.26 renders Counter names with the `_total` suffix
    # even though multiproc files store the base name.
    assert "soymutdb_worker_tasks_total" in text
    assert "soymutdb_worker_task_failures_total" in text
    assert "soymutdb_worker_task_duration_seconds" in text
    assert "soymutdb_worker_up" in text
    assert "soymutdb_worker_queue_depth" in text
    assert metrics.QUEUES == (
        "ingest",
        "export",
        "stats",
        "cleanup",
        "blast",
        "analyses",
        "default",
    )


def test_queue_depth_collector_only_accepts_redis_brokers():
    from soymutdb_worker import metrics

    assert metrics._is_redis_broker("redis://localhost:6379/1") is True
    assert metrics._is_redis_broker("rediss://localhost:6379/1") is True
    assert metrics._is_redis_broker("memory://") is False


def test_start_metrics_server_is_idempotent(monkeypatch):
    from soymutdb_worker import metrics

    # Another collected module may have imported metrics before this module's
    # environment setup. Always bind an ephemeral port in this test.
    monkeypatch.setattr(metrics, "METRICS_PORT", 0)
    metrics.start_metrics_server()
    assert metrics._started is True
    metrics.start_metrics_server()  # second call must be a no-op
    assert metrics._started is True
    metrics.WORKER_UP.set(0)  # leave no residue


def test_task_duration_signal_tracks_and_releases_task_id(monkeypatch):
    from soymutdb_worker import main

    monotonic_values = iter((10.0, 12.5))
    monkeypatch.setattr(main.time, "monotonic", lambda: next(monotonic_values))

    main._record_task_start(task_id="task-1")
    assert main._task_started_at["task-1"] == 10.0

    main._observe_task_duration(
        task_id="task-1",
        task=SimpleNamespace(name="soymutdb_worker.tasks.blast.run_blast"),
        state="SUCCESS",
    )
    assert "task-1" not in main._task_started_at


def test_queue_of_task_resolves_routing():
    """The queue resolver mirrors celery task_routes for known task names."""
    from soymutdb_worker import main

    assert main._queue_of_task("soymutdb_worker.tasks.blast.run_blast") == "blast"
    assert main._queue_of_task("soymutdb_worker.tasks.export.export_variants") == "export"
    assert main._queue_of_task("soymutdb_worker.tasks.ingest.import_vcf") == "ingest"
    assert main._queue_of_task("soymutdb_worker.tasks.cleanup.cleanup_temp_files") == "cleanup"
    assert main._queue_of_task("soymutdb_worker.tasks.stats.update_release_stats") == "stats"
    assert main._queue_of_task("soymutdb_worker.tasks.analyses.run_fastp") == "analyses"
    assert main._queue_of_task("some.unknown.task") == "default"
    assert main._queue_of_task("") == "unknown"
