"""Health gates for the native PostgreSQL store and optional Redis broker."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.v1 import health


@pytest.fixture(autouse=True)
def extended_mode(monkeypatch):
    monkeypatch.setattr(health, "get_settings", lambda: SimpleNamespace(deployment_mode="extended"))


async def test_liveness_needs_no_auth(client):
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_native_readiness_healthy(client, monkeypatch):
    redis = SimpleNamespace(ping=AsyncMock(return_value=True))
    monkeypatch.setattr(health, "get_redis", lambda: redis)
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {
        "postgres": {"healthy": True}, "redis": {"healthy": True, "required": True},
    }


async def test_baseline_only_requires_postgres(client, monkeypatch):
    monkeypatch.setattr(health, "get_settings", lambda: SimpleNamespace(deployment_mode="baseline"))
    getter = AsyncMock(side_effect=AssertionError("Baseline must not probe Redis"))
    monkeypatch.setattr(health, "get_redis", getter)
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {
        "postgres": {"healthy": True},
        "redis": {"healthy": None, "required": False, "status": "disabled"},
    }
    getter.assert_not_called()


@pytest.mark.parametrize("failure", [False, ConnectionError("broker unavailable")])
async def test_extended_redis_failure_is_not_ready(client, monkeypatch, failure):
    ping = AsyncMock(side_effect=failure) if isinstance(failure, Exception) else AsyncMock(
        return_value=failure,
    )
    monkeypatch.setattr(health, "get_redis", lambda: SimpleNamespace(ping=ping))
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["redis"]["healthy"] is False
    assert "clickhouse" not in response.json()["checks"]


async def test_postgres_failure_is_not_ready_and_hides_connection_details(client, app, monkeypatch):
    from app.core.database import get_db

    async def broken_db():
        yield SimpleNamespace(execute=AsyncMock(side_effect=ConnectionError("secret-host:5432")))

    app.dependency_overrides[get_db] = broken_db
    redis = SimpleNamespace(ping=AsyncMock(return_value=True))
    monkeypatch.setattr(health, "get_redis", lambda: redis)
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["postgres"]["healthy"] is False
    assert "secret-host" not in response.text
