"""Regression tests for the wired global request rate limiter.

The contract under test is section S-2 of
``docs/superpowers/plans/2026-09-15-phase-1-baseline-security-plan.md``:
graded budgets (anonymous read / write), the trusted peer IP, the
``/health`` + ``/metrics`` exemptions, the bounded in-process fallback and
the production fail-fast.  The limiter used to be *defined* but never
registered (audit D-11), so these tests also pin the wiring itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from starlette.requests import Request

from app import main
from app.core import middleware as middleware_module
from app.core.config import Settings, get_settings
from app.core.exceptions import RateLimitExceededError, ServiceUnavailableError
from app.core.metrics import REQUEST_COUNT
from app.core.middleware import RateLimitMiddleware
from app.core.ratelimit import (
    FALLBACK_MAX_KEYS,
    RequestRateLimiter,
    resolve_trusted_peer_ip,
)
from app.core.security import create_access_token

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class FakeRedis:
    """Async Redis double implementing the fixed-window Lua contract."""

    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.keys: list[str] = []

    async def eval(self, _script: str, _numkeys: int, key: str, window: int) -> list[int]:
        self.keys.append(key)
        count = self.values.get(key, 0) + 1
        self.values[key] = count
        return [count, window]


class FailingRedis:
    """Redis double that is always unavailable."""

    async def eval(self, *_args, **_kwargs):
        raise ConnectionError("redis is unavailable")


@dataclass
class StubSettings:
    """Minimal settings double for the limiter.

    The real ``public_read_rate_limit_per_minute`` floor (6000) is asserted
    against the real ``Settings``; the doubles below only exist so the
    behaviour tests can use a small budget.
    """

    app_env: str = "dev"
    api_v1_prefix: str = "/api/v1"
    rate_limit_enabled: bool = True
    benchmark_mode: bool = False
    public_read_rate_limit_per_minute: int = 6000
    write_rate_limit_per_minute: int = 120
    analytics_trusted_proxy_ips: tuple[str, ...] = field(default=())


def _build_app(limiter: RequestRateLimiter) -> FastAPI:
    """Return a tiny application that only exercises the limiter."""
    application = FastAPI()

    @application.get("/api/v1/public/items")
    async def public_items() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/api/v1/items")
    async def create_item() -> dict[str, str]:
        return {"status": "created"}

    @application.post("/api/v1/auth/login")
    async def login() -> dict[str, str]:
        return {"status": "ok"}

    application.add_middleware(RateLimitMiddleware, limiter=limiter)
    return application


def _client(app: FastAPI, *, peer: tuple[str, int] = ("127.0.0.1", 1234)) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, client=peer),
        base_url="http://test",
    )


def _request(
    *,
    path: str = "/api/v1/public/items",
    method: str = "GET",
    peer: str = "198.51.100.1",
    headers: dict[str, str] | None = None,
) -> Request:
    """Return a bare Starlette request (no ASGI round trip)."""
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": raw_headers,
            "client": (peer, 1234),
            "scheme": "http",
        }
    )


def _production_values() -> dict[str, object]:
    """Return complete non-placeholder production settings."""
    return {
        "database_url": "postgresql+asyncpg://api:strong-db-password@db:5432/soymutdb",
        "jwt_secret": "a-production-jwt-secret-with-at-least-32-chars",
        "redis_url": "redis://:strong-redis-password@redis:6379/0",
        "s3_endpoint": "https://minio.example.com",
        "s3_access_key": "production-access-key",
        "s3_secret_key": "production-secret-key",
        "analytics_ip_salt": "a-production-analytics-salt-with-at-least-32-chars",
        "cors_origins": ["https://app.example.com"],
    }


# ---------------------------------------------------------------------------
# Graded budgets
# ---------------------------------------------------------------------------


async def test_anonymous_get_below_the_budget_succeeds_and_above_it_is_rejected() -> None:
    """The anonymous-read bucket allows N requests and rejects N+1."""
    redis = FakeRedis()
    limiter = RequestRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: StubSettings(public_read_rate_limit_per_minute=2),
        clock=lambda: 120.5,
    )
    app = _build_app(limiter)

    async with _client(app) as client:
        first = await client.get("/api/v1/public/items")
        second = await client.get("/api/v1/public/items")
        third = await client.get("/api/v1/public/items")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers["Retry-After"] == "60"
    assert third.json()["error"]["code"] == "rate_limit_exceeded"


async def test_write_above_the_budget_is_rejected() -> None:
    """The write bucket allows N requests and rejects N+1 with 429."""
    redis = FakeRedis()
    limiter = RequestRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: StubSettings(write_rate_limit_per_minute=1),
        clock=lambda: 120.5,
    )
    app = _build_app(limiter)

    async with _client(app) as client:
        first = await client.post("/api/v1/items")
        second = await client.post("/api/v1/items")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "60"
    assert second.json()["error"]["code"] == "rate_limit_exceeded"


async def test_write_fails_closed_with_503_when_the_backend_is_unavailable() -> None:
    """A write must not proceed when its budget cannot be verified."""
    limiter = RequestRateLimiter(
        redis_getter=lambda: FailingRedis(),
        settings_getter=lambda: StubSettings(),
        clock=lambda: 120.5,
    )
    app = _build_app(limiter)

    async with _client(app) as client:
        response = await client.post("/api/v1/items")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


async def test_anonymous_read_fails_open_when_the_backend_is_unavailable() -> None:
    """Public data availability comes first: reads are served, not blocked."""
    limiter = RequestRateLimiter(
        redis_getter=lambda: FailingRedis(),
        settings_getter=lambda: StubSettings(public_read_rate_limit_per_minute=1),
        clock=lambda: 120.5,
    )
    app = _build_app(limiter)

    async with _client(app) as client:
        responses = [await client.get("/api/v1/public/items") for _ in range(3)]

    assert [response.status_code for response in responses] == [200, 200, 200]


async def test_authenticated_read_does_not_consume_the_anonymous_budget() -> None:
    """A request with a verifiable access token is not anonymous."""
    redis = FakeRedis()
    limiter = RequestRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: StubSettings(public_read_rate_limit_per_minute=1),
        clock=lambda: 120.5,
    )
    app = _build_app(limiter)
    token = create_access_token(str(uuid.uuid4()))

    async with _client(app) as client:
        first = await client.get(
            "/api/v1/public/items",
            headers={"Authorization": f"Bearer {token}"},
        )
        second = await client.get(
            "/api/v1/public/items",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert redis.keys == []


async def test_invalid_authorization_header_does_not_escape_the_anonymous_budget() -> None:
    """A forged header must not buy a caller a fresh budget."""
    redis = FakeRedis()
    limiter = RequestRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: StubSettings(public_read_rate_limit_per_minute=1),
        clock=lambda: 120.5,
    )
    app = _build_app(limiter)

    async with _client(app) as client:
        first = await client.get(
            "/api/v1/public/items",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        second = await client.get(
            "/api/v1/public/items",
            headers={"Authorization": "Bearer not-a-real-token"},
        )

    assert first.status_code == 200
    assert second.status_code == 429


async def test_login_is_not_counted_by_the_global_limiter() -> None:
    """Only login keeps its own dedicated limiter without double counting."""
    redis = FakeRedis()
    limiter = RequestRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: StubSettings(write_rate_limit_per_minute=1),
        clock=lambda: 120.5,
    )
    app = _build_app(limiter)

    async with _client(app) as client:
        responses = [await client.post("/api/v1/auth/login") for _ in range(3)]

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert redis.keys == []


@pytest.mark.parametrize("path", ["register", "refresh", "logout", "change-password"])
async def test_other_auth_writes_consume_the_global_budget(path: str) -> None:
    redis = FakeRedis()
    limiter = RequestRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: StubSettings(write_rate_limit_per_minute=1),
        clock=lambda: 120.5,
    )
    request = _request(path=f"/api/v1/auth/{path}", method="POST")
    await limiter.check(request)
    with pytest.raises(RateLimitExceededError):
        await limiter.check(request)
    assert len(redis.keys) == 2


@pytest.mark.parametrize("path", ["register", "refresh", "logout", "change-password"])
async def test_other_auth_writes_fail_closed_without_redis(path: str) -> None:
    limiter = RequestRateLimiter(
        redis_getter=lambda: FailingRedis(),
        settings_getter=lambda: StubSettings(),
    )
    with pytest.raises(ServiceUnavailableError):
        await limiter.check(_request(path=f"/api/v1/auth/{path}", method="POST"))


# ---------------------------------------------------------------------------
# Trusted peer IP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("forwarded", "trusted", "expected"),
    [
        ("198.51.100.99, 203.0.113.8", ("10.0.0.2",), "203.0.113.8"),
        ("198.51.100.99, 203.0.113.8, 10.0.0.1", ("10.0.0.2", "10.0.0.1"), "203.0.113.8"),
        ("198.51.100.99, 2001:db8::1", ("10.0.0.2",), "2001:db8::1"),
        ("invalid-client", ("10.0.0.2",), "10.0.0.2"),
        ("198.51.100.99, ", ("10.0.0.2",), "10.0.0.2"),
    ],
)
def test_trusted_proxy_chain_does_not_trust_a_client_supplied_prefix(
    forwarded: str, trusted: tuple[str, ...], expected: str,
) -> None:
    request = _request(peer="10.0.0.2", headers={"X-Forwarded-For": forwarded})
    assert resolve_trusted_peer_ip(request, trusted) == expected


async def test_forwarded_for_from_an_untrusted_peer_is_ignored() -> None:
    """A forged ``X-Forwarded-For`` must not select another budget."""
    redis = FakeRedis()
    limiter = RequestRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: StubSettings(public_read_rate_limit_per_minute=1),
        clock=lambda: 120.5,
    )
    app = _build_app(limiter)

    async with _client(app, peer=("203.0.113.7", 1234)) as client:
        first = await client.get(
            "/api/v1/public/items",
            headers={"X-Forwarded-For": "198.51.100.9"},
        )
        second = await client.get(
            "/api/v1/public/items",
            headers={"X-Forwarded-For": "198.51.100.9"},
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert redis.keys
    assert all("203.0.113.7" in key for key in redis.keys)
    assert not any("198.51.100.9" in key for key in redis.keys)


async def test_forwarded_for_from_a_trusted_peer_is_honoured() -> None:
    """A trusted proxy is allowed to speak for the original client."""
    redis = FakeRedis()
    limiter = RequestRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: StubSettings(
            public_read_rate_limit_per_minute=1,
            analytics_trusted_proxy_ips=("10.0.0.1",),
        ),
        clock=lambda: 120.5,
    )
    app = _build_app(limiter)

    async with _client(app, peer=("10.0.0.1", 1234)) as client:
        first = await client.get(
            "/api/v1/public/items",
            headers={"X-Forwarded-For": "198.51.100.9"},
        )
        second = await client.get(
            "/api/v1/public/items",
            headers={"X-Forwarded-For": "198.51.100.9"},
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert redis.keys
    assert all("198.51.100.9" in key for key in redis.keys)


# ---------------------------------------------------------------------------
# Exemptions and wiring
# ---------------------------------------------------------------------------


async def test_health_and_metrics_are_exempt(monkeypatch) -> None:
    """Probes and scrapes must stay reachable and must not consume budget."""
    redis = FakeRedis()
    limiter = RequestRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: StubSettings(public_read_rate_limit_per_minute=1),
        clock=lambda: 120.5,
    )
    monkeypatch.setattr(middleware_module, "request_rate_limiter", limiter)
    application = main.create_app()

    async with _client(application) as client:
        for _ in range(3):
            assert (await client.get("/health")).status_code == 200
            # The Prometheus application is mounted with a trailing slash.
            assert (await client.get("/metrics/")).status_code == 200
            # The container HEALTHCHECK calls the API's own liveness route.
            assert (await client.get("/api/v1/health/live")).status_code == 200

    assert redis.keys == []


def test_rate_limit_middleware_is_registered_in_the_application() -> None:
    """The limiter must be wired - a defined-but-unregistered limiter is a
    dead control (audit D-11)."""
    application = main.create_app()
    names = [middleware.cls.__name__ for middleware in application.user_middleware]

    assert "RateLimitMiddleware" in names
    # The limiter must sit inside the observability and response-shaping
    # middlewares, otherwise a rejected request would be invisible to
    # Prometheus and would miss the security/CORS headers.
    for outer in (
        "MetricsMiddleware",
        "RequestIdMiddleware",
        "SecurityHeadersMiddleware",
        "CORSMiddleware",
    ):
        assert names.index(outer) < names.index("RateLimitMiddleware")


async def test_rejected_request_is_counted_and_keeps_the_security_headers(monkeypatch) -> None:
    """A 429 produced by the limiter is observable and still hardened."""
    redis = FakeRedis()
    limiter = RequestRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: StubSettings(write_rate_limit_per_minute=1),
        clock=lambda: 120.5,
    )
    monkeypatch.setattr(middleware_module, "request_rate_limiter", limiter)
    application = main.create_app()

    counter = REQUEST_COUNT.labels(
        method="POST", endpoint="/api/v1/rate-limit-probe", status="429"
    )
    before = counter._value.get()

    async with _client(application) as client:
        first = await client.post("/api/v1/rate-limit-probe")
        second = await client.post("/api/v1/rate-limit-probe")

    assert first.status_code == 404  # the probe route does not exist
    assert second.status_code == 429
    assert second.headers["x-content-type-options"] == "nosniff"
    assert second.headers["x-frame-options"] == "DENY"
    assert counter._value.get() == before + 1


# ---------------------------------------------------------------------------
# Bounded in-process fallback
# ---------------------------------------------------------------------------


async def test_in_process_fallback_counter_stays_bounded() -> None:
    """A flood of distinct peers must not grow the process heap."""
    limiter = RequestRateLimiter(
        redis_getter=lambda: FailingRedis(),
        settings_getter=lambda: StubSettings(),
        clock=lambda: 120.5,
    )

    for index in range(FALLBACK_MAX_KEYS + 500):
        request = _request(peer=f"198.51.100.{index % 250}.{index // 250}")
        await limiter.check(request)

    assert limiter.fallback_key_count <= FALLBACK_MAX_KEYS


# ---------------------------------------------------------------------------
# Configuration contract
# ---------------------------------------------------------------------------


def test_config_no_longer_exposes_the_old_rate_limit_field() -> None:
    """The old single-budget field is gone: one source of truth only."""
    assert "rate_limit_per_minute" not in Settings.model_fields
    assert not hasattr(Settings(_env_file=None, app_env="dev"), "rate_limit_per_minute")


def test_public_read_budget_cannot_drop_below_the_edge_rate() -> None:
    """The application budget must never be tighter than nginx ``limit_req``."""
    with pytest.raises(ValidationError, match="public_read_rate_limit_per_minute"):
        Settings(_env_file=None, app_env="dev", public_read_rate_limit_per_minute=5999)

    settings = Settings(_env_file=None, app_env="dev")
    assert settings.public_read_rate_limit_per_minute == 6000


def test_prod_refuses_to_start_in_benchmark_mode() -> None:
    """A production deployment must never run as a benchmark."""
    with pytest.raises(ValidationError, match="benchmark_mode"):
        Settings(
            _env_file=None,
            app_env="prod",
            benchmark_mode=True,
            **_production_values(),
        )


def test_prod_refuses_to_start_with_the_limiter_disabled() -> None:
    """A production deployment must never run without the request budget."""
    with pytest.raises(ValidationError, match="rate_limit_enabled"):
        Settings(
            _env_file=None,
            app_env="prod",
            rate_limit_enabled=False,
            **_production_values(),
        )


def test_startup_fails_in_prod_with_benchmark_mode(monkeypatch) -> None:
    """The startup path itself fails, not only a direct constructor call."""
    monkeypatch.setenv("SOYMUTDB_APP_ENV", "prod")
    monkeypatch.setenv("SOYMUTDB_BENCHMARK_MODE", "true")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError, match="benchmark_mode"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_startup_fails_in_prod_with_the_limiter_disabled(monkeypatch) -> None:
    """The startup path itself fails, not only a direct constructor call."""
    monkeypatch.setenv("SOYMUTDB_APP_ENV", "prod")
    monkeypatch.setenv("SOYMUTDB_RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError, match="rate_limit_enabled"):
            get_settings()
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("app_env", ["dev", "staging"])
def test_non_prod_allows_benchmark_mode_and_a_disabled_limiter(app_env: str) -> None:
    """Outside production the benchmark escape hatch stays available."""
    settings = Settings(
        _env_file=None,
        app_env=app_env,
        benchmark_mode=True,
        rate_limit_enabled=False,
    )

    assert settings.benchmark_mode is True
    assert settings.rate_limit_enabled is False


async def test_disabled_limiter_does_not_consume_any_budget() -> None:
    """``rate_limit_enabled=False`` switches the limiter off completely."""
    redis = FakeRedis()
    limiter = RequestRateLimiter(
        redis_getter=lambda: redis,
        settings_getter=lambda: StubSettings(
            rate_limit_enabled=False,
            public_read_rate_limit_per_minute=1,
        ),
        clock=lambda: 120.5,
    )
    app = _build_app(limiter)

    async with _client(app) as client:
        responses = [await client.get("/api/v1/public/items") for _ in range(3)]

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert redis.keys == []
