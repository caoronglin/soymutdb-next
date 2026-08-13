"""Database infrastructure: SQLAlchemy async engine, ClickHouse client, Redis.

All three backends are exposed as lazily-initialised singletons with FastAPI
dependency-injection helpers so that tests can override them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import clickhouse_connect
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
        # Statement timeout (asyncpg server_settings) so a slow query cannot
        # pin a pooled connection forever; pool budget unchanged (5+5 API).
        connect_args: dict[str, Any] = {}
        if settings.db_statement_timeout > 0:
            connect_args["server_settings"] = {
                "statement_timeout": str(settings.db_statement_timeout * 1000)
            }
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            pool_pre_ping=settings.db_pool_pre_ping,
            echo=settings.db_echo,
            future=True,
            connect_args=connect_args,
        )
    return _engine


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
# ClickHouse (async client)
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
        _clickhouse_client = await clickhouse_connect.get_async_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_database,
            secure=settings.clickhouse_secure,
            connect_timeout=settings.clickhouse_connect_timeout,
            send_receive_timeout=settings.clickhouse_send_receive_timeout,
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
        await _clickhouse_client.aclose()
        _clickhouse_client = None
