"""Application configuration loaded from environment variables via pydantic-settings."""

from __future__ import annotations

import json
import warnings
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_DEV_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://localhost:3000",
    "http://localhost:8080",
]

_DEFAULT_PRODUCTION_VALUES = {
    "database_url": "postgresql+asyncpg://soymutdb:soymutdb_dev_password@localhost:5432/soymutdb",
    "redis_url": "redis://localhost:6379/0",
    "s3_endpoint": "http://localhost:9000",
    "s3_access_key": "minioadmin",
    "s3_secret_key": "minioadmin",
}

_EXAMPLE_JWT_SECRETS = {
    "dev_jwt_secret_change_in_production",
    "change-me",
    "change-me-in-production",
    "your-secret-key",
    "your-secret-key-change-me",
}


class Settings(BaseSettings):
    """Global application settings.

    All values can be overridden by environment variables prefixed with
    ``SOYMUTDB_`` (e.g. ``SOYMUTDB_DATABASE_URL``).
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="SOYMUTDB_", extra="ignore"
    )

    def __init__(self, **kwargs: Any) -> None:
        """Load normal fields and support explicit prefixed overrides.

        Environment variables are normally read by ``pydantic-settings``.  The
        prefixed form is also accepted as a constructor keyword so operators
        can perform a deterministic startup check, for example
        ``Settings(SOYMUTDB_APP_ENV="prod")``.
        """
        normalized = dict(kwargs)
        for key in tuple(normalized):
            if not key.startswith("SOYMUTDB_"):
                continue
            field_name = key.removeprefix("SOYMUTDB_").lower()
            if field_name in type(self).model_fields and field_name not in normalized:
                normalized[field_name] = normalized[key]
            normalized.pop(key)
        super().__init__(**normalized)

    # ------------------------------------------------------------------ App
    app_name: str = "SoyMutDB"
    app_env: Literal["dev", "staging", "prod"] = "dev"
    api_v1_prefix: str = "/api/v1"
    debug: bool = False

    # ----------------------------------------------------------- PostgreSQL
    database_url: str = (
        "postgresql+asyncpg://soymutdb:soymutdb_dev_password@localhost:5432/soymutdb"
    )
    # Connection budget (aligns with docker-compose.yml postgres comment):
    # default postgres max_connections=100 -> app budget <= 80%.  API pool
    # (5+5 per worker process) + 3 worker pools (2+4 each) + migrate + beat +
    # monitoring/ops headroom.  Bump these together with postgres
    # max_connections when the fleet grows.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    db_pool_pre_ping: bool = True
    db_echo: bool = False

    # ------------------------------------------------------------ ClickHouse
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "soymutdb"
    clickhouse_password: str = "soymutdb_dev_password"
    clickhouse_database: str = "soymutdb"
    clickhouse_secure: bool = False
    clickhouse_connect_timeout: int = 10
    clickhouse_send_receive_timeout: int = 30
    clickhouse_max_execution_time: int = 30
    max_sync_rows: int = 10000

    # ----------------------------------------------------------------- Redis
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 3600
    rate_limit_per_minute: int = 60
    login_rate_limit_window: int = Field(default=60, ge=1)
    login_rate_limit_max: int = Field(default=10, ge=1)

    # ----------------------------------------------------------- S3 / MinIO
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "us-east-1"
    s3_public_bucket: str = "genomic-data"
    s3_private_bucket: str = "user-tracks"
    s3_blast_bucket: str = "blast-dbs"
    s3_export_bucket: str = "exports"
    #: Bucket for user-uploaded analysis inputs / results (fastp, scanpy).
    s3_analyses_bucket: str = "analyses"
    #: Bucket for GWAS inputs (``gwas/{job}/input/``) and results
    #: (``gwas/{job}/output/``).
    s3_gwas_bucket: str = "gwas"
    s3_public_url: str = "http://localhost:8080/files"

    # ------------------------------------------------------------------ JWT
    jwt_secret: str = "dev_jwt_secret_change_in_production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # ------------------------------------------- Refresh session (HttpOnly cookie)
    # The refresh token is delivered exclusively through an HttpOnly cookie;
    # the login response JSON never contains it.
    refresh_cookie_name: str = "soymutdb_refresh"  # SOYMUTDB_REFRESH_COOKIE_NAME
    # Cookie Path is limited to the auth prefix so the browser only sends the
    # cookie to auth endpoints, never to other API routes.
    refresh_cookie_path: str = "/api/v1/auth"  # SOYMUTDB_REFRESH_COOKIE_PATH
    refresh_cookie_samesite: str = "lax"  # SOYMUTDB_REFRESH_COOKIE_SAMESITE
    # None → auto: Secure in prod/staging, relaxed (no Secure) in dev so
    # local http development works. Set explicitly to override.
    refresh_cookie_secure: bool | None = None  # SOYMUTDB_REFRESH_COOKIE_SECURE

    # --------------------------------------------------------------- Celery
    # Broker/result 使用独立的 Redis 实例（compose 中 redis-celery 服务，
    # noeviction + AOF）；此处默认值仅供本地开发（单机 Redis 不同 DB）。
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    # Celery result TTL（秒）：默认 7 天（1-7 天范围内建议值），worker 与
    # compose 均读取 SOYMUTDB_CELERY_RESULT_EXPIRES。
    celery_result_expires: int = 604800

    # ----------------------------------------------------------- Pagination
    max_page_size: int = 200
    default_page_size: int = 20

    # ----------------------------------------------------------------- CORS
    # Keep the raw default empty so production can distinguish an omitted
    # allowlist from an explicitly configured one.  Development fills this
    # with localhost origins in the model validator below.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --------------------------------------------------------------- BLAST
    blast_max_sequences: int = 100
    blast_max_length: int = 100000
    blast_default_db: str = "williams82_cds"
    blast_bin_dir: str = "/usr/bin"
    blast_cache_dir: str = "/tmp/blast_cache"
    #: Maximum delivery attempts per BLAST job (broker-level retries only;
    #: the worker itself is idempotent on top of this).
    blast_max_attempts: int = 3

    # ---------------------------------------------------------------- GWAS
    #: Maximum delivery attempts per GWAS job (broker-level retries only).
    gwas_max_attempts: int = 3

    # --------------------------------------------------------------- Outbox
    # Transactional outbox: API writes events inside business transactions;
    # a background dispatcher forwards them to Celery.  Disable only for
    # single-instance debugging (SOYMUTDB_OUTBOX_DISPATCHER_ENABLED=false).
    outbox_dispatcher_enabled: bool = True
    outbox_poll_interval_seconds: float = 1.0
    outbox_batch_size: int = 50
    #: Max send attempts per event before the row is left ``failed``.
    outbox_max_attempts: int = 5
    #: Sent events older than this many days are archived/deleted.
    outbox_retention_days: int = 30
    outbox_cleanup_interval_seconds: float = 3600.0

    # ----------------------------------------------------- OpenTelemetry
    otel_enabled: bool = False
    otel_service_name: str = "soymutdb-api"

    # --------------------------------------------------------------- Admin
    admin_email: str = "admin@soymutdb.local"
    admin_password: str = "admin123"

    # --------------------------------------------------------------- CDN
    cdn_enabled: bool = False
    cdn_urls: list[str] = Field(default_factory=lambda: [])

    # -------------------------------------------------------- Timeouts (centralized)
    api_timeout_critical: int = 30
    api_timeout_non_critical: int = 5
    api_timeout_file_transfer: int = 60

    # --------------------------------------------------------- Feature flags
    feature_registration_enabled: bool = True
    feature_blast_enabled: bool = True
    feature_seed_requests_enabled: bool = True

    @property
    def refresh_cookie_secure_effective(self) -> bool:
        """Effective ``Secure`` flag for the refresh cookie.

        Defaults to ``True`` outside development; ``False`` in dev so the
        cookie works over plain http://localhost.  ``SOYMUTDB_REFRESH_COOKIE_SECURE``
        can override the automatic choice.
        """
        if self.refresh_cookie_secure is not None:
            return self.refresh_cookie_secure
        return self.app_env != "dev"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        """Accept comma-separated origins from ``SOYMUTDB_CORS_ORIGINS``."""
        if value is None:
            return []
        if isinstance(value, str):
            raw_value = value.strip()
            if not raw_value:
                return []
            if raw_value.startswith("["):
                try:
                    value = json.loads(raw_value)
                except json.JSONDecodeError as exc:
                    raise ValueError("CORS origins must be comma-separated or a JSON list") from exc
                if not isinstance(value, list):
                    raise ValueError("CORS origins JSON value must be a list")
            else:
                value = raw_value.split(",")
        if not isinstance(value, (list, tuple, set)):
            raise ValueError("CORS origins must be a list or comma-separated string")
        return [origin.strip() for origin in value if isinstance(origin, str) and origin.strip()]

    @model_validator(mode="after")
    def validate_security_configuration(self) -> Settings:
        """Fail closed for production and warn when development defaults apply."""
        if self.app_env == "dev":
            if not self.cors_origins:
                self.cors_origins = list(_DEV_CORS_ORIGINS)
            warnings.warn(
                "development defaults and relaxed security policy are active; "
                "do not use this configuration in production",
                UserWarning,
                stacklevel=2,
            )

        validation_errors: list[str] = []

        # Credentials are always enabled by the API middleware, so a wildcard
        # origin is unsafe in every environment, not just production.
        if "*" in self.cors_origins:
            validation_errors.append(
                "CORS origins cannot contain '*' when credentials are enabled"
            )

        if self.app_env == "prod":
            required_fields = (
                "database_url",
                "jwt_secret",
                "redis_url",
                "s3_endpoint",
                "s3_access_key",
                "s3_secret_key",
            )
            for field_name in required_fields:
                value = getattr(self, field_name).strip()
                if not value:
                    validation_errors.append(f"{field_name} is required in production settings")

            for field_name, default_value in _DEFAULT_PRODUCTION_VALUES.items():
                if getattr(self, field_name).strip() == default_value:
                    validation_errors.append(
                        f"{field_name} must not use the development default in production settings"
                    )

            jwt_secret = self.jwt_secret.strip()
            if len(jwt_secret) < 32 or jwt_secret.lower() in _EXAMPLE_JWT_SECRETS:
                validation_errors.append(
                    "JWT secret must be at least 32 characters and must not be an example value"
                )

            if not self.cors_origins:
                validation_errors.append("CORS origins are required in production settings")

        if validation_errors:
            raise ValueError("; ".join(validation_errors))

        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
