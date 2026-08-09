"""Unit tests for PostgreSQL engine pool configuration (no DB required).

These tests assert that the async engine is created lazily and that its pool
parameters (pool_size / max_overflow / timeout / recycle / pre-ping) come
from ``Settings``, keeping the connection budget contract in one place.
They also cover the statement-timeout ``connect_args`` and the Redis socket
timeouts.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.core import database
from app.core.config import Settings


def _pool_attrs(pool) -> dict[str, int | bool]:
    """Read SQLAlchemy ``QueuePool`` internals via ``getattr``.

    The attribute names are private (``_pool``/``_max_overflow``/``_timeout``/
    ``_recycle``/``_pre_ping``) but stable across SQLAlchemy 2.x; ``getattr``
    keeps the assertions explicit without tripping static type checkers.
    """
    return {
        "pool_size": getattr(pool, "_pool").maxsize,
        "max_overflow": getattr(pool, "_max_overflow"),
        "timeout": getattr(pool, "_timeout"),
        "recycle": getattr(pool, "_recycle"),
        "pre_ping": getattr(pool, "_pre_ping"),
    }


def _build_engine_pool(settings: Settings):
    """Build the global engine with the given settings and return its pool."""
    original_settings = database.settings
    database.settings = settings
    database._engine = None
    try:
        engine = database.get_engine()
        return engine.pool
    finally:
        # The engine is created lazily (no connection opened), so simply
        # dropping the module-level reference is a safe reset.
        database._engine = None
        database.settings = original_settings


def test_engine_is_lazy_no_connection_on_import() -> None:
    """Importing the database module must not create an engine."""
    # Earlier tests in the same session may have built the engine/redis and
    # left the module globals set; snapshot and reset so this assertion is
    # order-independent (it only verifies import does not create them).
    engine, session_factory, redis = (
        database._engine,
        database._session_factory,
        database._redis,
    )
    database._engine = None
    database._session_factory = None
    database._redis = None
    try:
        assert database._engine is None
        assert database._redis is None
    finally:
        database._engine = engine
        database._session_factory = session_factory
        database._redis = redis


def test_pool_parameters_follow_default_settings(monkeypatch) -> None:
    """Default settings map to the connection-budget pool values."""
    # conftest.py sets SOYMUTDB_DATABASE_URL="" so the session-scoped
    # testcontainers URL applies to fixtures; drop it here so the class
    # default DSN is used and the engine URL parses.
    monkeypatch.delenv("SOYMUTDB_DATABASE_URL", raising=False)
    pool = _build_engine_pool(Settings(_env_file=None, app_env="dev"))
    attrs = _pool_attrs(pool)

    assert attrs == {
        "pool_size": 5,  # db_pool_size
        "max_overflow": 5,  # db_max_overflow
        "timeout": 30,  # db_pool_timeout
        "recycle": 1800,  # db_pool_recycle
        "pre_ping": True,  # db_pool_pre_ping
    }


def test_pool_parameters_follow_custom_settings(monkeypatch) -> None:
    """Custom ``SOYMUTDB_DB_POOL_*`` values reach the engine pool."""
    monkeypatch.delenv("SOYMUTDB_DATABASE_URL", raising=False)
    settings = Settings(
        _env_file=None,
        app_env="dev",
        db_pool_size=7,
        db_max_overflow=3,
        db_pool_timeout=15,
        db_pool_recycle=900,
        db_pool_pre_ping=False,
    )
    pool = _build_engine_pool(settings)
    attrs = _pool_attrs(pool)

    assert attrs == {
        "pool_size": 7,
        "max_overflow": 3,
        "timeout": 15,
        "recycle": 900,
        "pre_ping": False,
    }


def test_settings_expose_pool_defaults_and_celery_ttl() -> None:
    """Configuration surface documents the pool and Celery result TTL."""
    settings = Settings(_env_file=None, app_env="dev")

    assert settings.db_pool_size == 5
    assert settings.db_max_overflow == 5
    assert settings.db_pool_timeout == 30
    assert settings.db_pool_recycle == 1800
    assert settings.db_pool_pre_ping is True
    # Broker and result backend are separate Redis databases/instances.
    assert settings.celery_broker_url == "redis://localhost:6379/1"
    assert settings.celery_result_backend == "redis://localhost:6379/2"
    assert settings.celery_broker_url != settings.celery_result_backend
    # Result TTL default: 7 days, inside the recommended 1-7 day window.
    assert settings.celery_result_expires == 604800


def _capture_engine_kwargs(monkeypatch, settings: Settings) -> dict:
    """Build the engine via a patched ``create_async_engine`` and return kwargs."""
    captured: dict = {}

    def _fake_create_async_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(database, "create_async_engine", _fake_create_async_engine)
    original_settings = database.settings
    database.settings = settings
    database._engine = None
    try:
        database.get_engine()
    finally:
        database._engine = None
        database.settings = original_settings
    return captured


def test_statement_timeout_sent_as_server_setting(monkeypatch) -> None:
    """Default 30s statement timeout reaches asyncpg ``server_settings``."""
    monkeypatch.delenv("SOYMUTDB_DATABASE_URL", raising=False)
    captured = _capture_engine_kwargs(
        monkeypatch, Settings(_env_file=None, app_env="dev")
    )

    assert captured["connect_args"] == {
        "server_settings": {"statement_timeout": "30000"}
    }


def test_statement_timeout_zero_disables_connect_args(monkeypatch) -> None:
    """``db_statement_timeout=0`` sends no server settings at all."""
    monkeypatch.delenv("SOYMUTDB_DATABASE_URL", raising=False)
    captured = _capture_engine_kwargs(
        monkeypatch,
        Settings(_env_file=None, app_env="dev", db_statement_timeout=0),
    )

    assert captured["connect_args"] == {}


def test_redis_client_has_bounded_socket_timeouts(monkeypatch) -> None:
    """Redis socket timeouts keep cache degradation fast and bounded."""
    from redis.asyncio import Redis

    captured: dict = {}
    database._redis = None

    def _fake_from_url(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return MagicMock(spec=Redis)

    monkeypatch.setattr(database, "from_url", _fake_from_url)
    try:
        database.get_redis()
    finally:
        database._redis = None

    assert captured["socket_timeout"] == 2.0
    assert captured["socket_connect_timeout"] == 2.0
    assert captured["decode_responses"] is True
