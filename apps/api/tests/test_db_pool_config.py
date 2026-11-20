"""Unit tests for PostgreSQL engine pool configuration (no DB required).

These tests assert that the async engine is created lazily and that its pool
parameters (pool_size / max_overflow / timeout / recycle / pre-ping) come
from ``Settings``, keeping the connection budget contract in one place.
They also cover the statement-timeout ``connect_args`` and the Redis socket
timeouts.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

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
    assert settings.db_pool_use_lifo is True
    assert settings.redis_max_connections == 64
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
        "server_settings": {"statement_timeout": "30000", "jit": "off"}
    }


def test_statement_timeout_zero_still_sends_jit_setting(monkeypatch) -> None:
    """``db_statement_timeout=0`` omits only the timeout, not ``jit``."""
    monkeypatch.delenv("SOYMUTDB_DATABASE_URL", raising=False)
    captured = _capture_engine_kwargs(
        monkeypatch,
        Settings(_env_file=None, app_env="dev", db_statement_timeout=0),
    )

    assert captured["connect_args"] == {"server_settings": {"jit": "off"}}


def test_jit_disabled_by_default_at_connection_level(monkeypatch) -> None:
    """JIT is turned off on every pooled connection, not per transaction.

    The stats path opens a second session through the shared session factory,
    so a ``SET LOCAL`` on the request session would not reach it; the setting
    must therefore be part of ``server_settings``.
    """
    monkeypatch.delenv("SOYMUTDB_DATABASE_URL", raising=False)
    captured = _capture_engine_kwargs(
        monkeypatch, Settings(_env_file=None, app_env="dev")
    )

    assert captured["connect_args"]["server_settings"]["jit"] == "off"


def test_jit_can_be_enabled_per_deployment(monkeypatch) -> None:
    """``db_jit_enabled=True`` stops overriding the server's JIT default."""
    monkeypatch.delenv("SOYMUTDB_DATABASE_URL", raising=False)
    captured = _capture_engine_kwargs(
        monkeypatch,
        Settings(_env_file=None, app_env="dev", db_jit_enabled=True),
    )

    assert "jit" not in captured["connect_args"]["server_settings"]


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
    assert captured["max_connections"] == 64
    assert captured["socket_keepalive"] is True


def test_redis_pool_size_follows_settings(monkeypatch) -> None:
    """The Redis pool bound is configurable instead of unbounded."""
    captured: dict = {}
    database._redis = None

    def _fake_from_url(url, **kwargs):
        captured.update(kwargs)
        return MagicMock(spec=Redis)

    monkeypatch.setattr(database, "from_url", _fake_from_url)
    original_settings = database.settings
    database.settings = Settings(
        _env_file=None, app_env="dev", redis_max_connections=8
    )
    try:
        database.get_redis()
    finally:
        database._redis = None
        database.settings = original_settings

    assert captured["max_connections"] == 8


def test_pool_use_lifo_is_configurable(monkeypatch) -> None:
    """LIFO checkout is on by default and can be disabled."""
    monkeypatch.delenv("SOYMUTDB_DATABASE_URL", raising=False)

    default_pool = _build_engine_pool(Settings(_env_file=None, app_env="dev"))
    # QueuePool forwards the flag to its queue, which is where it is stored;
    # the pool object itself never keeps a ``_use_lifo`` attribute.
    assert getattr(default_pool, "_pool").use_lifo is True

    fifo_pool = _build_engine_pool(
        Settings(_env_file=None, app_env="dev", db_pool_use_lifo=False)
    )
    assert getattr(fifo_pool, "_pool").use_lifo is False


@pytest.mark.asyncio
async def test_clickhouse_client_can_be_awaited_repeatedly_without_reusing_coroutine(
    monkeypatch,
) -> None:
    """Repeated dependency resolution returns the same usable client."""
    client = MagicMock()
    factory = AsyncMock(return_value=client)
    clickhouse_connect = pytest.importorskip("clickhouse_connect", reason="Historical driver only")

    monkeypatch.setattr(clickhouse_connect, "get_async_client", factory)
    database._clickhouse_client = None

    try:
        first = await database.get_clickhouse_client()
        second = await database.get_clickhouse_client()
    finally:
        database._clickhouse_client = None

    assert first is client
    assert second is client
    factory.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_db_closes_clickhouse_client() -> None:
    """Application shutdown closes and clears the ClickHouse client.

    The double is specced from the real ``AsyncClient`` on purpose: a plain
    ``MagicMock`` happily invents any attribute, so a shutdown path calling a
    method the driver does not expose stays green in unit tests and only
    raises ``AttributeError`` against a live client. ``spec_set`` fails here
    instead, which keeps this test honest about the client's real surface.
    """
    AsyncClient = pytest.importorskip("clickhouse_connect.driver.asyncclient").AsyncClient
    client = MagicMock(spec_set=AsyncClient)
    database._clickhouse_client = client

    try:
        await database.close_db()
    finally:
        database._clickhouse_client = None

    client.close.assert_awaited_once()
    assert database._clickhouse_client is None


@pytest.mark.asyncio
async def test_close_db_still_disposes_postgres_and_redis() -> None:
    """Fixing the ClickHouse teardown must not drop the other disposals."""
    engine = MagicMock(spec_set=AsyncEngine)
    engine.dispose = AsyncMock()
    redis = MagicMock(spec_set=Redis)
    redis.aclose = AsyncMock()
    database._engine = engine
    database._session_factory = object()
    database._redis = redis
    database._clickhouse_client = None

    try:
        await database.close_db()
    finally:
        database._engine = None
        database._session_factory = None
        database._redis = None
        database._clickhouse_client = None

    engine.dispose.assert_awaited_once()
    redis.aclose.assert_awaited_once()
    assert database._engine is None
    assert database._session_factory is None
    assert database._redis is None
    assert database._clickhouse_client is None
