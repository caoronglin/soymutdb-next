"""Pure unit tests for production settings and CORS validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _production_values() -> dict[str, object]:
    """Return complete non-placeholder production settings."""
    return {
        "database_url": "postgresql+asyncpg://api:strong-db-password@db:5432/soymutdb",
        "jwt_secret": "a-production-jwt-secret-with-at-least-32-chars",
        "redis_url": "redis://:strong-redis-password@redis:6379/0",
        "s3_endpoint": "https://minio.example.com",
        "s3_access_key": "production-access-key",
        "s3_secret_key": "production-secret-key",
        "clickhouse_password": "strong-clickhouse-password",
        "analytics_ip_salt": "a-production-analytics-salt-with-at-least-32-chars",
        "admin_password": "a-strong-production-admin-password",
        "admin_email": "ops@example.com",
        "cors_origins": ["https://app.example.com"],
    }


@pytest.mark.parametrize(
    "missing_field",
    [
        "database_url",
        "jwt_secret",
        "analytics_ip_salt",
        "redis_url",
        "s3_endpoint",
        "s3_access_key",
        "s3_secret_key",
        "admin_password",
        "admin_email",
    ],
)
def test_prod_rejects_missing_required_infrastructure(missing_field: str) -> None:
    """Production settings fail closed when any required value is blank."""
    values = _production_values()
    values[missing_field] = ""

    with pytest.raises(ValidationError, match="production settings"):
        Settings(_env_file=None, app_env="prod", **values)


def test_prod_rejects_default_infrastructure_values() -> None:
    """Development placeholders cannot accidentally be used in production."""
    with pytest.raises(ValidationError, match="production settings"):
        Settings(_env_file=None, app_env="prod", cors_origins=["https://app.example.com"])

def test_prod_rejects_clickhouse_dev_default_password() -> None:
    """The ClickHouse app-layer default password must not be used in production."""
    values = _production_values()
    values["clickhouse_password"] = "soymutdb_dev_password"

    with pytest.raises(ValidationError, match="production settings"):
        Settings(_env_file=None, app_env="prod", **values)


@pytest.mark.parametrize(
    "admin_password",
    ["admin123", "change-me", "short", "password", "admin"],
)
def test_prod_rejects_weak_or_default_admin_password(admin_password: str) -> None:
    """Production admin bootstrap password must be strong and non-default."""
    values = _production_values()
    values["admin_password"] = admin_password

    with pytest.raises(ValidationError, match="admin password"):
        Settings(_env_file=None, app_env="prod", **values)


@pytest.mark.parametrize(
    "admin_email",
    ["", "admin@soymutdb.local", "not-an-email"],
)
def test_prod_rejects_invalid_or_default_admin_email(admin_email: str) -> None:
    """Production admin email must be a valid, non-default address."""
    values = _production_values()
    values["admin_email"] = admin_email

    with pytest.raises(ValidationError, match="admin email"):
        Settings(_env_file=None, app_env="prod", **values)



@pytest.mark.parametrize(
    "jwt_secret",
    ["short-secret", "dev_jwt_secret_change_in_production"],
)
def test_prod_rejects_weak_or_example_jwt_secret(jwt_secret: str) -> None:
    """Production JWT signing keys must not be short or example values."""
    values = _production_values()
    values["jwt_secret"] = jwt_secret

    with pytest.raises(ValidationError, match="JWT secret"):
        Settings(_env_file=None, app_env="prod", **values)


def test_rejects_non_hmac_jwt_algorithm() -> None:
    """JWT configuration must stay on the supported HMAC algorithms."""
    values = _production_values()
    values["jwt_algorithm"] = "ES256"

    with pytest.raises(ValidationError, match="jwt_algorithm"):
        Settings(_env_file=None, app_env="prod", **values)


def test_dev_warns_and_uses_localhost_cors_defaults() -> None:
    """Development remains convenient but makes its relaxed defaults visible."""
    with pytest.warns(UserWarning, match="development defaults"):
        settings = Settings(_env_file=None, app_env="dev", cors_origins=[])

    assert "http://localhost:5173" in settings.cors_origins
    assert "http://localhost:3000" in settings.cors_origins


def test_cors_origins_accept_comma_separated_environment_style_values() -> None:
    """CORS origins support the documented comma-separated environment format."""
    values = _production_values()
    values["cors_origins"] = "https://app.example.com, https://admin.example.com"

    settings = Settings(_env_file=None, app_env="prod", **values)

    assert settings.cors_origins == [
        "https://app.example.com",
        "https://admin.example.com",
    ]


def test_baseline_prod_does_not_require_optional_services() -> None:
    """Baseline production only requires PostgreSQL and core security settings."""
    settings = Settings(
        _env_file=None,
        app_env="prod",
        deployment_mode="baseline",
        database_url="postgresql+asyncpg://api:strong-db-password@db:5432/soymutdb",
        jwt_secret="a-production-jwt-secret-with-at-least-32-chars",
        analytics_ip_salt="a-production-analytics-salt-with-at-least-32-chars",
        admin_password="a-strong-production-admin-password",
        admin_email="ops@example.com",
        cors_origins=["https://app.example.com"],
    )

    assert settings.deployment_mode == "baseline"


def test_prod_rejects_missing_cors_origins() -> None:
    """Production must explicitly configure at least one trusted origin."""
    values = _production_values()
    values["cors_origins"] = []

    with pytest.raises(ValidationError, match="CORS origins"):
        Settings(_env_file=None, app_env="prod", **values)


def test_cors_wildcard_is_rejected_when_credentials_are_enabled() -> None:
    """The API's credentialed CORS policy must never accept a wildcard."""
    values = _production_values()
    values["cors_origins"] = ["*"]

    with pytest.raises(ValidationError, match="CORS origins"):
        Settings(_env_file=None, app_env="prod", **values)
