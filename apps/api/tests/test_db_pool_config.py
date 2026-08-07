"""Unit tests for PostgreSQL engine pool configuration (no DB required).

These tests assert that the async engine is created lazily and that its pool
parameters (pool_size / max_overflow / timeout / recycle / pre-ping) come
from ``Settings``, keeping the connection budget contract in one place.
"""

from __future__ import annotations

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
    assert database._engine is None
    assert database._redis is None


def test_pool_parameters_follow_default_settings() -> None:
    """Default settings map to the connection-budget pool values."""
    pool = _build_engine_pool(Settings(_env_file=None, app_env="dev"))
    attrs = _pool_attrs(pool)

    assert attrs == {
        "pool_size": 5,  # db_pool_size
        "max_overflow": 5,  # db_max_overflow
        "timeout": 30,  # db_pool_timeout
        "recycle": 1800,  # db_pool_recycle
        "pre_ping": True,  # db_pool_pre_ping
    }


def test_pool_parameters_follow_custom_settings() -> None:
    """Custom ``SOYMUTDB_DB_POOL_*`` values reach the engine pool."""
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
