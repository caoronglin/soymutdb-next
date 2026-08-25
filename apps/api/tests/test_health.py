"""Tests for health API endpoints (/api/v1/health/*).

Covers: liveness probe, readiness probe (with dependency-unavailable scenarios).
All routes use the ``/api/v1/`` prefix.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

HEALTH_PREFIX = "/api/v1/health"


@pytest.mark.asyncio
class TestLiveness:
    """Tests for GET /api/v1/health/live."""

    async def test_liveness_ok(self, client):
        """Liveness probe returns 200 when the process is alive."""
        response = await client.get(f"{HEALTH_PREFIX}/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    async def test_liveness_no_auth_required(self, client):
        """Liveness probe should not require authentication."""
        response = await client.get(f"{HEALTH_PREFIX}/live")
        assert response.status_code == 200


@pytest.mark.asyncio
class TestReadiness:
    """Tests for GET /api/v1/health/ready."""

    async def test_readiness_healthy(self, client):
        """Readiness probe returns 200 when all dependencies are up."""
        # Mock ClickHouse service to return healthy
        with patch(
            "app.services.clickhouse_service.ClickHouseService.ping",
            new_callable=AsyncMock,
            return_value=True,
        ), patch("app.api.v1.health.get_redis") as get_redis, patch(
            "app.api.v1.health.get_db"
        ):
            get_redis.return_value.ping = AsyncMock(return_value=True)
            response = await client.get(f"{HEALTH_PREFIX}/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["checks"]["postgres"]["healthy"] is True
        assert data["checks"]["clickhouse"]["healthy"] is True
        assert data["checks"]["redis"]["healthy"] is True

    async def test_readiness_baseline_reports_optional_services_without_failing(
        self, client, monkeypatch
    ):
        """Baseline readiness only gates PostgreSQL and diagnoses optional services."""
        from app.api.v1 import health
        from app.core.config import Settings

        monkeypatch.setattr(
            health, "get_settings", lambda: Settings(_env_file=None, deployment_mode="baseline")
        )
        with patch("app.api.v1.health.get_redis") as get_redis, patch(
            "app.api.v1.health.ClickHouseService.ping", new_callable=AsyncMock, return_value=False
        ):
            get_redis.return_value.ping = AsyncMock(
                side_effect=ConnectionError("redis unavailable")
            )
            response = await client.get(f"{HEALTH_PREFIX}/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["checks"]["postgres"]["healthy"] is True
        assert data["checks"]["clickhouse"] == {
            "healthy": None, "required": False, "status": "disabled"
        }
        assert data["checks"]["redis"] == {
            "healthy": None, "required": False, "status": "disabled"
        }

    async def test_readiness_clickhouse_down(self, client):
        """Readiness probe returns 503 when ClickHouse is unavailable."""
        with patch(
            "app.services.clickhouse_service.ClickHouseService.ping",
            new_callable=AsyncMock,
            return_value=False,
        ):
            response = await client.get(f"{HEALTH_PREFIX}/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["clickhouse"]["healthy"] is False

    async def test_readiness_clickhouse_exception(self, client):
        """Readiness probe returns 503 when ClickHouse raises an exception."""
        with patch(
            "app.services.clickhouse_service.ClickHouseService.ping",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Connection refused"),
        ):
            response = await client.get(f"{HEALTH_PREFIX}/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["checks"]["clickhouse"]["healthy"] is False

    async def test_readiness_no_auth_required(self, client):
        """Readiness probe should not require authentication."""
        with patch(
            "app.services.clickhouse_service.ClickHouseService.ping",
            new_callable=AsyncMock,
            return_value=True,
        ):
            response = await client.get(f"{HEALTH_PREFIX}/ready")
        assert response.status_code in (200, 503)
