"""FastAPI middleware tests for CORS and request ID propagation."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app import main
from app.core.config import Settings


def _prod_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://api:strong-db-password@db:5432/soymutdb",
        "jwt_secret": "a-production-jwt-secret-with-at-least-32-chars",
        "redis_url": "redis://:strong-redis-password@redis:6379/0",
        "s3_endpoint": "https://minio.example.com",
        "s3_access_key": "production-access-key",
        "s3_secret_key": "production-secret-key",
        "analytics_ip_salt": "production-analytics-ip-salt-at-least-32-characters",
        "cors_origins": ["https://app.example.com"],
        # Production must say no to open self-registration explicitly.
        "feature_registration_enabled": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, app_env="prod", **values)


async def test_cors_allows_only_configured_origin(monkeypatch) -> None:
    """Credentialed preflight requests only allow configured origins."""
    monkeypatch.setattr(main, "settings", _prod_settings())
    application = main.create_app()

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        allowed = await client.options(
            "/health",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        denied = await client.options(
            "/health",
            headers={
                "Origin": "https://untrusted.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://app.example.com"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


async def test_request_id_is_transmitted_and_generated(monkeypatch) -> None:
    """The API preserves an edge request ID and generates one when absent."""
    monkeypatch.setattr(
        main,
        "settings",
        Settings(_env_file=None, app_env="dev", cors_origins=["http://test"]),
    )
    application = main.create_app()

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        transmitted = await client.get("/health", headers={"X-Request-ID": "edge-request-123"})
        generated = await client.get("/health")

    assert transmitted.headers["x-request-id"] == "edge-request-123"
    assert len(generated.headers["x-request-id"]) == 36


async def test_blast_capability_and_release_preflight_preserves_origin_allowlist(
    monkeypatch,
) -> None:
    """Public job credentials travel in headers across the separate portal origin."""
    monkeypatch.setattr(main, "settings", _prod_settings())
    application = main.create_app()
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        headers = {
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Blast-Token,X-SoyMutDB-Release",
        }
        allowed = await client.options("/api/v1/blast/public/jobs/test", headers=headers)
        denied = await client.options(
            "/api/v1/blast/public/jobs/test",
            headers={**headers, "Origin": "https://untrusted.example.com"},
        )
    assert allowed.status_code == 200
    allowed_headers = allowed.headers["access-control-allow-headers"].lower()
    assert "x-blast-token" in allowed_headers
    assert "x-soymutdb-release" in allowed_headers
    assert allowed.headers["access-control-allow-origin"] == "https://app.example.com"
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
