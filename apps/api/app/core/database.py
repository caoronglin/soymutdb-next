"""Database infrastructure: SQLAlchemy async engine, Redis, legacy ClickHouse.

The PostgreSQL engine and Redis are the runtime stores and are exposed as
lazily-initialised singletons with FastAPI dependency-injection helpers so that
tests can override them. The ClickHouse client is retained only for the
historical backfill/test surface; no runtime query path uses it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis, from_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# SQLAlchemy async (PostgreSQL)
# ---------------------------------------------------------------------------

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the global async engine, creating it on first call."""
    global _engine
    if _engine is None:
        # Connection-level server settings.  ``jit`` is configured here
        # rather than via ``SET LOCAL`` because aggregate queries run in
        # sessions opened by helpers (e.g. the variant service); only the
        # connection setting reaches every session the pool hands out.
        server_settings: dict[str, str] = {}
        if settings.db_statement_timeout > 0:
            server_settings["statement_timeout"] = str(
                settings.db_statement_timeout * 1000
            )
        if not settings.db_jit_enabled:
            server_settings["jit"] = "off"
        connect_args: dict[str, Any] = {}
        if server_settings:
            connect_args["server_settings"] = server_settings
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            pool_pre_ping=settings.db_pool_pre_ping,
            pool_use_lifo=settings.db_pool_use_lifo,
            echo=settings.db_echo,
            future=True,
            connect_args=connect_args,
        )
    return _engine


def get_db_pool_status() -> dict[str, int] | None:
    """Return a non-I/O snapshot when the async engine already exists."""
    if _engine is None:
        return None
    pool = _engine.sync_engine.pool
    required = ("size", "checkedin", "checkedout", "overflow")
    if not all(callable(getattr(pool, name, None)) for name in required):
        return None
    return {
        "capacity": settings.db_pool_size + settings.db_max_overflow,
        "size": int(pool.size()),
        "checked_in": int(pool.checkedin()),
        "checked_out": int(pool.checkedout()),
        # QueuePool reports negative overflow until its base pool is populated.
        "overflow": max(0, int(pool.overflow())),
    }


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the global session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an :class:`AsyncSession`."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# ClickHouse (async client; legacy backfill/test surface only)
# ---------------------------------------------------------------------------


_clickhouse_client: Any | None = None


async def get_clickhouse_client() -> Any:
    """Return a singleton async ClickHouse client.

    ``clickhouse_connect.get_async_client`` is a **coroutine factory**: this
    function awaits the coroutine factory once and reuses the client, so each
    call returns a fresh awaitable while preserving the existing call shape.
    """
    global _clickhouse_client
    if _clickhouse_client is None:
        # Legacy backfill tooling only. Native API queries never load this
        # optional driver or maintain a second analytics connection.
        import clickhouse_connect

        _clickhouse_client = await clickhouse_connect.get_async_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_database,
            secure=settings.clickhouse_secure,
            connect_timeout=settings.clickhouse_connect_timeout,
            send_receive_timeout=settings.clickhouse_send_receive_timeout,
            # Single-row telemetry inserts are buffered by ClickHouse instead
            # of creating one MergeTree part per request. Telemetry is
            # best-effort, so the HTTP call does not wait for the flush.
            settings={
                "async_insert": 1,
                "wait_for_async_insert": 0,
                "async_insert_max_data_size": 1_000_000,
                "async_insert_busy_timeout_ms": 1_000,
            },
        )
    return _clickhouse_client


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


_redis: Redis | None = None


def get_redis() -> Redis:
    """Return the global Redis client (async).

    Bounded socket timeouts make cache degradation fast when Redis is down:
    ``get``/``setex`` failures are swallowed by the cache helper which then
    falls back to a direct database query.
    """
    global _redis
    if _redis is None:
        _redis = from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=settings.redis_socket_timeout,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            socket_keepalive=True,
            max_connections=settings.redis_max_connections,
            health_check_interval=30,
        )
    return _redis


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def close_db() -> None:
    """Dispose all database connections (called on application shutdown)."""
    global _engine, _session_factory, _redis, _clickhouse_client
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
    if _redis is not None:
        await _redis.aclose()
        _redis = None
    if _clickhouse_client is not None:
        # ``clickhouse_connect``'s async client exposes ``close()`` (an
        # awaitable), not ``aclose()``; calling the latter raised
        # ``AttributeError`` during application shutdown.
        await _clickhouse_client.close()
        _clickhouse_client = None
