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
from sqlalchemy.ext.asyncio import (
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
from app.models.base import Base  # noqa: E402
from app.models import *  # noqa: E402,F401,F403

# Try to import testcontainers; skip tests if unavailable
try:
    from testcontainers.postgres import PostgresContainer

    HAS_TESTCONTAINERS = True
except ImportError:
    HAS_TESTCONTAINERS = False


# ---------------------------------------------------------------------------
# Session-scoped PostgreSQL container
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_container():
    """Start a PostgreSQL container for the test session.

    Uses testcontainers-postgres which provides a real PostgreSQL instance
    (required because models use JSONB, UUID, and pgcrypto).
    """
    if not HAS_TESTCONTAINERS:
        pytest.skip("testcontainers-postgres not installed")

    with PostgresContainer("postgres:16-alpine") as pg:
        # Build asyncpg URL from the container's JDBC-style URL
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        db = pg.dbname
        user = pg.username
        password = pg.password
        async_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"
        yield async_url


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


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

    yield engine

    # Drop all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session with rollback isolation."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session
        # Clean up after each test
        await session.rollback()


# ---------------------------------------------------------------------------
# FastAPI app and HTTP client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app(db_session: AsyncSession):
    """Create a test FastAPI app with overridden dependencies."""
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

    # Override the database dependency
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

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
