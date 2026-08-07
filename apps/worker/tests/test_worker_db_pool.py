"""Worker sync-engine pool configuration tests (no DB connection made).

``create_engine`` is mocked so the pool parameters passed by
``soymutdb_worker.utils.db.get_engine`` can be asserted directly.
"""

from __future__ import annotations

from soymutdb_worker.utils import db as worker_db


def _capture_engine_kwargs(monkeypatch, env: dict[str, str] | None = None):
    """Build the engine with mocked ``create_engine`` and return its kwargs."""
    captured: dict = {}

    def fake_create_engine(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return object()

    for key in (
        "SOYMUTDB_WORKER_DB_POOL_SIZE",
        "SOYMUTDB_WORKER_DB_MAX_OVERFLOW",
        "SOYMUTDB_WORKER_DB_POOL_RECYCLE",
        "SOYMUTDB_WORKER_DB_POOL_TIMEOUT",
        "WORKER_DB_POOL_SIZE",
        "WORKER_DB_MAX_OVERFLOW",
        "WORKER_DB_POOL_RECYCLE",
        "WORKER_DB_POOL_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(worker_db, "create_engine", fake_create_engine)
    monkeypatch.setattr(worker_db, "_engine", None)
    try:
        worker_db.get_engine()
    finally:
        worker_db._engine = None
    return captured


def test_worker_engine_default_pool_is_small(monkeypatch) -> None:
    """Worker pools must default to 2+4 (fits the connection budget)."""
    kwargs = _capture_engine_kwargs(monkeypatch)

    assert kwargs["pool_size"] == 2
    assert kwargs["max_overflow"] == 4
    assert kwargs["pool_recycle"] == 1800
    assert kwargs["pool_timeout"] == 30
    assert kwargs["pool_pre_ping"] is True


def test_worker_engine_pool_follows_soymutdb_env(monkeypatch) -> None:
    """``SOYMUTDB_WORKER_DB_*`` values must reach the sync engine."""
    kwargs = _capture_engine_kwargs(
        monkeypatch,
        env={
            "SOYMUTDB_WORKER_DB_POOL_SIZE": "3",
            "SOYMUTDB_WORKER_DB_MAX_OVERFLOW": "6",
            "SOYMUTDB_WORKER_DB_POOL_RECYCLE": "900",
            "SOYMUTDB_WORKER_DB_POOL_TIMEOUT": "15",
        },
    )

    assert kwargs["pool_size"] == 3
    assert kwargs["max_overflow"] == 6
    assert kwargs["pool_recycle"] == 900
    assert kwargs["pool_timeout"] == 15
