"""Synchronous SQLAlchemy session factory for Celery worker tasks.

Celery tasks run in sync threads, so we use a plain (non-async) engine.
The ``DATABASE_URL`` environment variable is read at first use.

The API's ``app`` package (containing ORM models) is resolved via
``PYTHONPATH`` or by searching relative to the project root, so that
``from app.models import …`` works from worker code.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from soymutdb_worker.config import get_setting

# ---------------------------------------------------------------------------
# Ensure the API's ``app`` package is importable
# ---------------------------------------------------------------------------

_API_APP_RESOLVED = False


def _resolve_api_app() -> None:
    """Add the API ``app`` directory to ``sys.path`` if not already present."""
    global _API_APP_RESOLVED
    if _API_APP_RESOLVED:
        return
    _API_APP_RESOLVED = True

    # Allow explicit env override (e.g. from Docker Compose)
    api_path = get_setting("API_APP_PATH", "")
    if api_path and Path(api_path).is_dir():
        sys.path.insert(0, str(Path(api_path).parent))
        return

    # Try to find it relative to the worker's known location.
    # Expected layout:
    #   <project_root>/apps/worker/src/soymutdb_worker/utils/db.py
    #   <project_root>/apps/api/app/
    try:
        this_file = Path(__file__).resolve()
        # Walk up to find the project root (has both apps/api and apps/worker)
        for parent in this_file.parents:
            if (parent / "apps" / "api" / "app").is_dir():
                sys.path.insert(0, str(parent / "apps" / "api"))
                return
            # Also check if we are already at the project root
            if (parent / "apps" / "worker").is_dir() and (parent / "apps" / "api").is_dir():
                sys.path.insert(0, str(parent / "apps" / "api"))
                return
    except Exception:
        pass


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
        # Connection budget: small pool per worker process (2+4).  Tune via
        # SOYMUTDB_WORKER_DB_POOL_SIZE / SOYMUTDB_WORKER_DB_MAX_OVERFLOW;
        # keep the fleet total within postgres max_connections budget (see
        # docker-compose.yml postgres service comment).
        _engine = create_engine(
            get_database_url(),
            pool_size=int(get_setting("WORKER_DB_POOL_SIZE", "2")),
            max_overflow=int(get_setting("WORKER_DB_MAX_OVERFLOW", "4")),
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
            session.query(...)
    """
    _resolve_api_app()
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
