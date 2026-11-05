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
from app.core.ratelimit import (
    FALLBACK_MAX_KEYS,
    ExternalArticlePreviewRateLimiter,
    LoginRateLimiter,
)


@dataclass
class FakeRedis:
    """Small async Redis double implementing the Lua command contract."""

    values: dict[str, int]

    def __init__(self) -> None:
        self.values = {}
        self.keys: list[str] = []

    async def eval(self, _script: str, _numkeys: int, key: str, window: int) -> list[int]:
        self.keys.append(key)
        count = self.values.get(key, 0) + 1
        self.values[key] = count
        return [count, window]


class FailingRedis:
    async def eval(self, *_args, **_kwargs):
        raise ConnectionError("redis is unavailable")


def _settings(
    *,
    app_env: str,
    maximum: int = 2,
    ip_maximum: int = 50,
    preview_maximum: int = 2,
    preview_window: int = 300,
) -> Settings:
    return Settings(
        app_env=app_env,
        database_url="postgresql+asyncpg://user:password@example.com/database",
        redis_url="redis://redis.example.com:6379/0",
        s3_endpoint="https://s3.example.com",
        s3_access_key="test-access-key",
        s3_secret_key="test-secret-key",
        jwt_secret="test-jwt-secret-that-is-longer-than-32-characters",
        analytics_ip_salt="test-analytics-ip-salt-that-is-longer-than-32-characters",
        cors_origins=["https://example.com"],
        login_rate_limit_window=60,
        login_rate_limit_max=maximum,
        login_ip_rate_limit_max=ip_maximum,
        external_article_preview_rate_limit_window=preview_window,
        external_article_preview_rate_limit_max=preview_maximum,
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
    # Two budgets per attempt (pair + IP); the failing call consumes the pair
    # counter and raises before the IP counter runs.
    assert len(redis.keys) == 5


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

    pair_keys = [key for key in redis.keys if key.startswith("soymutdb:login:ratelimit:")]
    assert pair_keys[0] == pair_keys[1]
    assert pair_keys[1] != pair_keys[2]
    assert pair_keys[0] != pair_keys[3]


@pytest.mark.asyncio
async def test_external_preview_limit_is_scoped_to_editor_and_ip() -> None:
    redis = FakeRedis()
    limiter = ExternalArticlePreviewRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: _settings(app_env="prod", preview_maximum=2),
        clock=lambda: 120.5,
    )

    await limiter.enforce(user_id="editor-1", client_ip="192.0.2.10")
    await limiter.enforce(user_id="editor-1", client_ip="192.0.2.10")

    with pytest.raises(RateLimitExceededError) as raised:
        await limiter.enforce(user_id="editor-1", client_ip="192.0.2.10")

    # Fixed windows align to the epoch, so this is the remaining 180 seconds
    # of the configured 300-second window at the injected clock value.
    assert raised.value.retry_after == 180
    assert redis.keys[0].startswith(
        "soymutdb:external-article-preview:ratelimit:user:editor-1:ip:192.0.2.10:"
    )


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
async def test_dev_fallback_map_stays_bounded_for_distinct_identities() -> None:
    """A Redis outage must not let distinct identities grow the heap.

    All keys in this flood belong to one fixed window, so pruning previous
    windows is not enough: only an unconditional cap bounds the map. The
    login-family limiters used a hardcoded 2048 with no such cap.
    """
    limiter = LoginRateLimiter(
        redis_getter=lambda: FailingRedis(),
        settings_getter=lambda: _settings(
            app_env="dev",
            maximum=FALLBACK_MAX_KEYS + 500,
            ip_maximum=FALLBACK_MAX_KEYS + 500,
        ),
        clock=lambda: 120.5,
    )

    for index in range(FALLBACK_MAX_KEYS + 500):
        await limiter.enforce(
            username=f"user-{index}",
            client_ip=f"198.51.100.{index % 250}.{index // 250}",
        )

    assert len(limiter._fallback_counts) <= FALLBACK_MAX_KEYS


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


@pytest.mark.asyncio
async def test_rotating_usernames_from_one_ip_is_bounded_by_the_ip_budget() -> None:
    """Credential stuffing across many accounts must not reset the budget.

    The pair key alone gives every (username, IP) pair a fresh counter, so an
    attacker rotating usernames would never hit the per-pair maximum. The
    per-IP dimension is what bounds the source address.
    """
    redis = FakeRedis()
    limiter = LoginRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: _settings(app_env="prod", maximum=10, ip_maximum=3),
        clock=lambda: 120.5,
    )

    for index in range(3):
        await limiter.enforce(username=f"victim-{index}", client_ip="198.51.100.7")

    with pytest.raises(RateLimitExceededError) as raised:
        await limiter.enforce(username="victim-3", client_ip="198.51.100.7")
    assert "network" in str(raised.value)


@pytest.mark.asyncio
async def test_ip_budget_is_isolated_per_source_address() -> None:
    redis = FakeRedis()
    limiter = LoginRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: _settings(app_env="prod", maximum=10, ip_maximum=1),
        clock=lambda: 120.5,
    )

    await limiter.enforce(username="alice", client_ip="198.51.100.8")
    await limiter.enforce(username="alice", client_ip="198.51.100.9")
    with pytest.raises(RateLimitExceededError):
        await limiter.enforce(username="bob", client_ip="198.51.100.8")


@pytest.mark.asyncio
async def test_same_username_from_different_ips_keeps_independent_pair_budgets() -> None:
    redis = FakeRedis()
    limiter = LoginRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: _settings(app_env="prod", maximum=1, ip_maximum=10),
        clock=lambda: 120.5,
    )

    await limiter.enforce(username="alice", client_ip="198.51.100.10")
    await limiter.enforce(username="alice", client_ip="198.51.100.11")
    with pytest.raises(RateLimitExceededError):
        await limiter.enforce(username="alice", client_ip="198.51.100.10")
