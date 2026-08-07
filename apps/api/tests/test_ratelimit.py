"""Unit tests for the Redis-backed login rate limiter."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from starlette.requests import Request

from app.core.config import Settings
from app.core.exceptions import (
    RateLimitExceededError,
    ServiceUnavailableError,
    soy_mut_db_exception_handler,
)
from app.core.ratelimit import LoginRateLimiter


@dataclass
class FakeRedis:
    """Small async Redis double implementing the Lua command contract."""

    values: dict[str, int]

    def __init__(self) -> None:
        self.values = {}
        self.keys: list[str] = []

    async def eval(self, _script: str, _numkeys: int, key: str, _window: int) -> list[int]:
        self.keys.append(key)
        count = self.values.get(key, 0) + 1
        self.values[key] = count
        return [count, 60]


class FailingRedis:
    async def eval(self, *_args, **_kwargs):
        raise ConnectionError("redis is unavailable")


def _settings(*, app_env: str, maximum: int = 2) -> Settings:
    return Settings(
        app_env=app_env,
        database_url="postgresql+asyncpg://user:password@example.com/database",
        redis_url="redis://redis.example.com:6379/0",
        s3_endpoint="https://s3.example.com",
        s3_access_key="test-access-key",
        s3_secret_key="test-secret-key",
        jwt_secret="test-jwt-secret-that-is-longer-than-32-characters",
        cors_origins=["https://example.com"],
        login_rate_limit_window=60,
        login_rate_limit_max=maximum,
    )


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
        }
    )


@pytest.mark.asyncio
async def test_fixed_window_allows_n_then_rejects_n_plus_one() -> None:
    redis = FakeRedis()
    limiter = LoginRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: _settings(app_env="prod", maximum=2),
        clock=lambda: 120.5,
    )

    await limiter.enforce(username="Alice", client_ip="192.0.2.10")
    await limiter.enforce(username="Alice", client_ip="192.0.2.10")

    with pytest.raises(RateLimitExceededError) as raised:
        await limiter.enforce(username="Alice", client_ip="192.0.2.10")

    assert raised.value.retry_after == 60
    assert len(redis.keys) == 3


@pytest.mark.asyncio
async def test_rate_limit_key_normalizes_username_and_distinguishes_ip() -> None:
    redis = FakeRedis()
    limiter = LoginRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: _settings(app_env="prod", maximum=10),
        clock=lambda: 120.5,
    )

    await limiter.enforce(username="  Alice ", client_ip="192.0.2.10")
    await limiter.enforce(username="alice", client_ip="192.0.2.10")
    await limiter.enforce(username="alice", client_ip="192.0.2.11")
    await limiter.enforce(username=None, client_ip="192.0.2.10")

    assert redis.keys[0] == redis.keys[1]
    assert redis.keys[1] != redis.keys[2]
    assert redis.keys[0] != redis.keys[3]


@pytest.mark.asyncio
async def test_dev_redis_failure_uses_process_local_fallback(caplog) -> None:
    limiter = LoginRateLimiter(
        redis_getter=lambda: FailingRedis(),
        settings_getter=lambda: _settings(app_env="dev", maximum=1),
        clock=lambda: 120.5,
    )

    await limiter.enforce(username="dev-user", client_ip="192.0.2.20")
    with pytest.raises(RateLimitExceededError):
        await limiter.enforce(username="dev-user", client_ip="192.0.2.20")

    assert "redis" in caplog.text.lower() or "unavailable" in caplog.text.lower()


@pytest.mark.asyncio
async def test_prod_redis_failure_fails_closed() -> None:
    limiter = LoginRateLimiter(
        redis_getter=lambda: FailingRedis(),
        settings_getter=lambda: _settings(app_env="prod", maximum=10),
        clock=lambda: 120.5,
    )

    with pytest.raises(ServiceUnavailableError):
        await limiter.enforce(username="prod-user", client_ip="192.0.2.21")


@pytest.mark.asyncio
async def test_rate_limit_exception_handler_sets_retry_after_header() -> None:
    error = RateLimitExceededError("Too many login attempts", retry_after=37)
    response = await soy_mut_db_exception_handler(_request(), error)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "37"
    body = json.loads(bytes(response.body))
    assert body["error"]["code"] == "rate_limit_exceeded"
