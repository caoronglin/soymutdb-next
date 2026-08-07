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
