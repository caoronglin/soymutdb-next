"""Synchronous SQLAlchemy session factory for Celery worker tasks.

Celery tasks run in sync threads, so we use a plain (non-async) engine.
The ``DATABASE_URL`` environment variable is read at first use.

The worker no longer imports the API's ``app`` package: task payloads come
from the shared ``soymutdb_jobs`` contract and all table access goes through
the narrow repositories in :mod:`soymutdb_worker.repositories`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from soymutdb_worker.config import get_setting

# ---------------------------------------------------------------------------
# Engine / session factory (lazy, singleton)
# ---------------------------------------------------------------------------

_engine = None
_Session: sessionmaker[Session] | None = None


def get_database_url() -> str:
    """Return the PostgreSQL DSN from environment."""
    url = get_setting(
        "DATABASE_URL",
        "postgresql://soymutdb:soymutdb_dev_password@localhost:5432/soymutdb",
    )
    # If the URL uses the async scheme (``+asyncpg``), strip it for sync.
    if "+asyncpg" in url:
        url = url.replace("+asyncpg", "+psycopg2")
    if "+psycopg" in url and "+psycopg2" not in url:
        url = url.replace("+psycopg", "+psycopg2")
    return url


def get_engine():
    """Return the global sync engine, creating it on first call."""
    global _engine
    if _engine is None:
        # Celery prefork creates this lazy engine independently in each child.
        # A synchronous child executes one task at a time, so 1+0 is the safe
        # default; multiplying a larger pool by fleet concurrency can exhaust
        # PostgreSQL even when every container appears to have a small pool.
        # Tune only with the fleet-wide budget in docker-compose.yml.
        _engine = create_engine(
            get_database_url(),
            pool_size=int(get_setting("WORKER_DB_POOL_SIZE", "1")),
            max_overflow=int(get_setting("WORKER_DB_MAX_OVERFLOW", "0")),
            pool_recycle=int(get_setting("WORKER_DB_POOL_RECYCLE", "1800")),
            pool_timeout=int(get_setting("WORKER_DB_POOL_TIMEOUT", "30")),
            pool_pre_ping=True,
            echo=get_setting("DB_ECHO", "false").lower() == "true",
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the global session factory."""
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _Session


@contextmanager
def get_db() -> Iterator[Session]:
    """Yield a sync SQLAlchemy session as a context-manager generator.

    Usage::

        with get_db() as session:
            session.execute(...)
    """
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def close_engine() -> None:
    """Dispose the engine (call on worker shutdown)."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
        _engine = None
        _Session = None
