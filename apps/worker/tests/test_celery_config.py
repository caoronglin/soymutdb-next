"""Celery broker/backend separation and result-expiry configuration tests.

The worker app reads ``SOYMUTDB_CELERY_*`` at import time; these tests use
``importlib.reload`` so each case observes a fresh module state.  No real
Redis connection is made.
"""

from __future__ import annotations

import importlib

import soymutdb_worker.main as worker_main

_MODULE = "soymutdb_worker.main"


def _reload_worker():
    """Re-import the worker module so it re-reads environment variables."""
    return importlib.reload(importlib.import_module(_MODULE))


def test_defaults_broker_and_result_backend_are_separate(monkeypatch) -> None:
    """Without overrides the broker and backend must target different DBs."""
    monkeypatch.delenv("SOYMUTDB_CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("SOYMUTDB_CELERY_RESULT_BACKEND", raising=False)
    monkeypatch.delenv("SOYMUTDB_CELERY_RESULT_EXPIRES", raising=False)
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("CELERY_RESULT_BACKEND", raising=False)
    monkeypatch.delenv("CELERY_RESULT_EXPIRES", raising=False)

    mod = _reload_worker()

    assert mod.BROKER_URL == "redis://localhost:6379/1"
    assert mod.RESULT_BACKEND == "redis://localhost:6379/2"
    assert mod.BROKER_URL != mod.RESULT_BACKEND
    assert mod.celery_app.conf.broker_url == mod.BROKER_URL
    assert mod.celery_app.conf.result_backend == mod.RESULT_BACKEND


def test_soymutdb_prefixed_env_overrides_broker_backend_and_expiry(
    monkeypatch,
) -> None:
    """The canonical ``SOYMUTDB_CELERY_*`` names must take effect."""
    monkeypatch.setenv("SOYMUTDB_CELERY_BROKER_URL", "redis://broker.internal:6379/0")
    monkeypatch.setenv(
        "SOYMUTDB_CELERY_RESULT_BACKEND", "redis://broker.internal:6379/1"
    )
    monkeypatch.setenv("SOYMUTDB_CELERY_RESULT_EXPIRES", "86400")

    mod = _reload_worker()

    assert mod.BROKER_URL == "redis://broker.internal:6379/0"
    assert mod.RESULT_BACKEND == "redis://broker.internal:6379/1"
    assert mod.celery_app.conf.result_expires == 86400


def test_legacy_unprefixed_env_fallback(monkeypatch) -> None:
    """Unprefixed ``CELERY_*`` names still work as a legacy fallback."""
    monkeypatch.delenv("SOYMUTDB_CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("SOYMUTDB_CELERY_RESULT_BACKEND", raising=False)
    monkeypatch.delenv("SOYMUTDB_CELERY_RESULT_EXPIRES", raising=False)
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://legacy:6379/0")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://legacy:6379/1")
    monkeypatch.setenv("CELERY_RESULT_EXPIRES", "172800")

    mod = _reload_worker()

    assert mod.BROKER_URL == "redis://legacy:6379/0"
    assert mod.RESULT_BACKEND == "redis://legacy:6379/1"
    assert mod.celery_app.conf.result_expires == 172800


def test_default_result_expires_is_seven_days(monkeypatch) -> None:
    """Default result TTL must sit inside the recommended 1-7 day window."""
    monkeypatch.delenv("SOYMUTDB_CELERY_RESULT_EXPIRES", raising=False)
    monkeypatch.delenv("CELERY_RESULT_EXPIRES", raising=False)

    mod = _reload_worker()

    assert worker_main.RESULT_EXPIRES == 604800
    assert 86400 <= mod.celery_app.conf.result_expires <= 7 * 86400


def test_native_retention_is_loaded_and_scheduled_hourly() -> None:
    mod = _reload_worker()
    assert "soymutdb_worker.tasks.native_retention" in mod.celery_app.conf.include
    assert mod.celery_app.conf.beat_schedule["cleanup-native-retention"] == {
        "task": "soymutdb_worker.tasks.native_retention.cleanup",
        "schedule": 3600,
    }


def test_analyses_tasks_route_to_dedicated_queue(monkeypatch) -> None:
    """fastp/scanpy analyses tasks must route to the ``analyses`` queue."""
    mod = _reload_worker()

    assert mod.celery_app.conf.task_routes["soymutdb_worker.tasks.analyses.*"] == {
        "queue": "analyses"
    }
    assert mod._queue_of_task("soymutdb_worker.tasks.analyses.run_fastp") == "analyses"
    assert mod._queue_of_task("soymutdb_worker.tasks.analyses.run_scanpy") == "analyses"


def test_page_builder_publish_task_is_included_and_defaults_queue(monkeypatch) -> None:
    mod = _reload_worker()
    module_name = "soymutdb_worker.tasks.page_builder_publish"

    assert module_name in mod.celery_app.conf.include
    importlib.reload(importlib.import_module(module_name))
    task_name = "soymutdb_worker.tasks.page_builder_publish.publish_definition"
    assert task_name in mod.celery_app.tasks
    assert mod._queue_of_task(task_name) == "default"


def test_analyses_queue_is_distinct_from_existing_queues(monkeypatch) -> None:
    """The analyses route must not shadow any previously registered queue."""
    mod = _reload_worker()

    route = mod.celery_app.conf.task_routes["soymutdb_worker.tasks.analyses.*"]
    queue = route["queue"]
    assert queue == "analyses"
    existing = {
        mod.celery_app.conf.task_routes["soymutdb_worker.tasks.ingest.*"]["queue"],
        mod.celery_app.conf.task_routes["soymutdb_worker.tasks.blast.*"]["queue"],
        mod.celery_app.conf.task_routes["soymutdb_worker.tasks.export.*"]["queue"],
        mod.celery_app.conf.task_routes["soymutdb_worker.tasks.stats.*"]["queue"],
        mod.celery_app.conf.task_routes["soymutdb_worker.tasks.cleanup.*"]["queue"],
    }
    assert queue not in existing
