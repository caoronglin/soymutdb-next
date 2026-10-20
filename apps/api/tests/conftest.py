"""Pytest configuration and shared fixtures.

Fixes vs. quartz reference:
- Uses **testcontainers-postgres** instead of SQLite (the models use
  PostgreSQL-specific types like JSONB and UUID that SQLite cannot create).
- All fixtures are async (asyncpg / httpx.AsyncClient).
- Database is automatically created and destroyed per test session.
- Provides ``db_session``, ``client``, and test data factories.
- All routes use the ``/api/v1/`` prefix.
- All password fields use ``password_hash`` (not ``hashed_password``).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Set test environment variables BEFORE importing app modules
os.environ.setdefault("SOYMUTDB_DATABASE_URL", "")
os.environ.setdefault("SOYMUTDB_JWT_SECRET", "test_jwt_secret_for_testing_only")
os.environ.setdefault("SOYMUTDB_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("SOYMUTDB_REFRESH_TOKEN_EXPIRE_DAYS", "1")

from app.core.database import get_db  # noqa: E402
from app.core.security import RoleName  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.auth import Role  # noqa: E402
from app.models import *  # noqa: E402,F401,F403

# Try to import testcontainers; skip tests if unavailable
try:
    from testcontainers.postgres import PostgresContainer

    HAS_TESTCONTAINERS = True
except ImportError:
    HAS_TESTCONTAINERS = False


async def _seed_test_roles(connection: AsyncConnection) -> None:
    """Seed the RBAC catalog normally supplied by the Alembic migration.

    Testcontainers starts from ``Base.metadata.create_all()``, not Alembic, so
    it otherwise misses the role rows that public registration requires.

    The insert is idempotent on purpose. ``SOYMUTDB_TEST_DATABASE_URL`` points
    at a database that outlives a single session, and a session that is killed
    (OOM, SIGKILL, a closed laptop) never reaches the ``drop_all`` teardown.
    Without the conflict guard every later session then fails at setup with
    ``duplicate key value violates unique constraint "roles_name_key"``, which
    reads like a code defect and is not one.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    await connection.execute(
        pg_insert(Role)
        .values([{"name": role.value} for role in RoleName])
        .on_conflict_do_nothing(index_elements=[Role.__table__.c.name])
    )


# ---------------------------------------------------------------------------
# Session-scoped PostgreSQL database
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_container():
    """Provide an isolated PostgreSQL URL for the test session.

    ``SOYMUTDB_TEST_DATABASE_URL`` opts into an explicitly provisioned local
    PostgreSQL database (for example, a Mamba-hosted instance). Otherwise the
    default remains a disposable testcontainers PostgreSQL instance. Both
    paths use the same per-session schema setup and teardown in ``test_engine``.
    """
    external_url = os.environ.get("SOYMUTDB_TEST_DATABASE_URL")
    if external_url:
        if not external_url.startswith("postgresql+asyncpg://"):
            raise pytest.UsageError(
                "SOYMUTDB_TEST_DATABASE_URL must use the postgresql+asyncpg:// scheme"
            )
        yield external_url
        return

    if not HAS_TESTCONTAINERS:
        pytest.skip(
            "testcontainers-postgres not installed; set SOYMUTDB_TEST_DATABASE_URL "
            "to use an explicit PostgreSQL test database"
        )

    with PostgresContainer("postgres:18.6-alpine") as pg:
        # Build asyncpg URL from the container's JDBC-style URL
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        db = pg.dbname
        user = pg.username
        password = pg.password
        async_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"
        yield async_url


# NOTE: no custom `event_loop` fixture. pytest-asyncio >= 1.0 manages its own
# loops; the shared engine must live on the same loop as the tests, so
# pyproject.toml sets asyncio_default_fixture_loop_scope/test_loop_scope =
# "session" (single loop for the whole session).


# ---------------------------------------------------------------------------
# Database engine and session
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def test_engine(postgres_container: str):
    """Create the test database engine and schema."""
    engine = create_async_engine(
        postgres_container,
        echo=False,
        future=True,
    )

    # Create all tables from model metadata
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _seed_test_roles(conn)

    yield engine

    # Drop all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_connection(test_engine) -> AsyncGenerator[AsyncConnection, None]:
    """Function-scoped connection holding one outer transaction per test."""
    async with test_engine.connect() as connection:
        outer_transaction = await connection.begin()
        yield connection
        await outer_transaction.rollback()


@pytest_asyncio.fixture
async def db_session(db_connection) -> AsyncGenerator[AsyncSession, None]:
    """Create a test session whose commits stay inside an outer transaction."""
    session_factory = async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async with session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# FastAPI app and HTTP client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app(db_connection):
    """Create a test FastAPI app with overridden dependencies.

    Request sessions join the same outer transaction as ``db_session``
    (savepoint mode), so fixtures can seed data the API can see. Requests
    must be awaited sequentially — asyncpg rejects concurrent operations
    on one connection.
    """
    from fastapi import FastAPI

    from app.api.v1.router import api_router
    from app.core.exceptions import (
        SoyMutDBError,
        http_exception_handler,
        soy_mut_db_exception_handler,
        unhandled_exception_handler,
        validation_exception_handler,
    )
    from fastapi.exceptions import RequestValidationError
    from fastapi import HTTPException

    application = FastAPI(title="SoyMutDB Test API")
    application.include_router(api_router, prefix="/api/v1")

    # Register exception handlers
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.add_exception_handler(HTTPException, http_exception_handler)
    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    application.add_exception_handler(Exception, unhandled_exception_handler)

    # Override the database dependency: per-request savepoint session on the
    # shared outer transaction so in-test commits are visible to the API.
    session_factory = async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_get_db

    yield application

    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Create an async HTTP client for testing API endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Test data factories
# ---------------------------------------------------------------------------


class UserFactory:
    """Factory for creating test users via the API register endpoint."""

    @staticmethod
    def make_payload(
        email: str = "test@example.com",
        username: str = "testuser",
        password: str = "TestPass123!",
        full_name: str = "Test User",
        role_name: str = "viewer",
    ) -> dict:
        """Return a valid UserCreate payload."""
        return {
            "email": email,
            "username": username,
            "password": password,
            "full_name": full_name,
            "role_name": role_name,
        }


class GeneFactory:
    """Factory for creating test gene data."""

    @staticmethod
    def make_dict(
        gene_id: str = "Glyma.01G000100",
        name: str = "Test Gene",
        biotype: str = "protein_coding",
        chromosome: str = "Gm01",
        start: int = 1000,
        end: int = 5000,
        strand: str = "+",
    ) -> dict:
        return {
            "gene_id": gene_id,
            "name": name,
            "biotype": biotype,
            "chromosome": chromosome,
            "start": start,
            "end": end,
            "strand": strand,
        }


@pytest.fixture
def user_factory() -> type[UserFactory]:
    """Provide the UserFactory class."""
    return UserFactory


@pytest.fixture
def gene_factory() -> type[GeneFactory]:
    """Provide the GeneFactory class."""
    return GeneFactory


# ---------------------------------------------------------------------------
# Redis isolation for cache-aside paths
# ---------------------------------------------------------------------------


class _UnavailableRedis:
    """Redis stand-in that fails every call (forces cache degradation)."""

    async def get(self, *args, **kwargs):
        raise ConnectionError("redis unavailable in tests")

    async def setex(self, *args, **kwargs):
        raise ConnectionError("redis unavailable in tests")


@pytest.fixture(autouse=True)
def _redis_unavailable(monkeypatch):
    """Make the global cache-aside helper degrade to direct queries.

    Unit tests never touch a real Redis; ``app.services.cache.get_or_set``
    swallows Redis failures and falls back to the loader.  The cache helper
    itself is tested separately with an explicit mock Redis (see
    ``test_cache.py``), so this only neutralises the global client used by
    endpoints.
    """
    from app.services import cache as cache_module

    monkeypatch.setattr(cache_module, "get_redis", lambda: _UnavailableRedis())
