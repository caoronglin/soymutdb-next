"""Database infrastructure: SQLAlchemy async engine, ClickHouse client, Redis.

All three backends are exposed as lazily-initialised singletons with FastAPI
dependency-injection helpers so that tests can override them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
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
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            pool_pre_ping=settings.db_pool_pre_ping,
            echo=settings.db_echo,
            future=True,
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


@lru_cache(maxsize=1)
def get_clickhouse_client() -> Any:
    """Return a singleton async ClickHouse client.

    ``clickhouse_connect.get_async_client`` is a **coroutine factory**: this
    function returns a coroutine that must be awaited to obtain the client.
    Callers should ``await get_clickhouse_client()`` (and cache the result
    themselves, e.g. lazily on first use).
    """
    return clickhouse_connect.get_async_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_database,
        secure=settings.clickhouse_secure,
        connect_timeout=settings.clickhouse_connect_timeout,
        send_receive_timeout=settings.clickhouse_send_receive_timeout,
    )


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


_redis: Redis | None = None


def get_redis() -> Redis:
    """Return the global Redis client (async)."""
    global _redis
    if _redis is None:
        _redis = from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
    return _redis


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def close_db() -> None:
    """Dispose all database connections (called on application shutdown)."""
    global _engine, _session_factory, _redis
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
    if _redis is not None:
        await _redis.aclose()
        _redis = None
