"""Docker-free unit tests for readiness mode semantics."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from starlette.responses import Response

from app.api.v1.health import readiness


def _db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=None)
    return db


@pytest.mark.asyncio
async def test_baseline_readiness_only_gates_postgres() -> None:
    response = Response()

    with (
        patch(
            "app.api.v1.health.get_settings",
            return_value=SimpleNamespace(deployment_mode="baseline"),
        ),
        patch("app.api.v1.health.ClickHouseService") as clickhouse,
        patch("app.api.v1.health.get_redis") as get_redis,
    ):
        result = await readiness(response, _db())

    assert response.status_code == 200
    assert result["status"] == "ok"
    assert result["checks"]["postgres"]["healthy"] is True
    assert result["checks"]["clickhouse"]["status"] == "disabled"
    assert result["checks"]["redis"]["status"] == "disabled"
    clickhouse.assert_not_called()
    get_redis.assert_not_called()


@pytest.mark.asyncio
async def test_extended_readiness_fails_when_clickhouse_is_down() -> None:
    response = Response()
    clickhouse = Mock()
    clickhouse.return_value.ping = AsyncMock(return_value=False)

    with (
        patch(
            "app.api.v1.health.get_settings",
            return_value=SimpleNamespace(deployment_mode="extended"),
        ),
        patch("app.api.v1.health.ClickHouseService", clickhouse),
        patch("app.api.v1.health.get_redis") as get_redis,
    ):
        get_redis.return_value.ping = AsyncMock(return_value=True)
        result = await readiness(response, _db())

    assert response.status_code == 503
    assert result["status"] == "degraded"
    assert result["checks"]["clickhouse"]["required"] is True


@pytest.mark.asyncio
async def test_extended_readiness_fails_when_redis_is_down() -> None:
    response = Response()
    with (
        patch(
            "app.api.v1.health.get_settings",
            return_value=SimpleNamespace(deployment_mode="extended"),
        ),
        patch("app.api.v1.health.ClickHouseService") as clickhouse,
        patch("app.api.v1.health.get_redis") as get_redis,
    ):
        clickhouse.return_value.ping = AsyncMock(return_value=True)
        get_redis.return_value.ping = AsyncMock(return_value=False)
        result = await readiness(response, _db())

    assert response.status_code == 503
    assert result["status"] == "degraded"
    assert result["checks"]["redis"]["required"] is True
