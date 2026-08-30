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
    "clickhouse_password": "soymutdb_dev_password",
    "analytics_ip_salt": "soymutdb-analytics-dev",
    "admin_password": "admin123",
    "admin_email": "admin@soymutdb.local",
}

_EXAMPLE_ADMIN_PASSWORDS = {
    "admin123",
    "change-me",
    "change-me-in-production",
    "password",
    "admin",
}

_EXAMPLE_JWT_SECRETS = {
    "dev_jwt_secret_change_in_production",
    "change-me",
    "change-me-in-production",
    "your-secret-key",
    "your-secret-key-change-me",
}

# The API uses symmetric JWT signing; keeping the allowlist explicit prevents
# accidentally enabling an algorithm that requires an unmaintained crypto path.
_ALLOWED_JWT_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})


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
    # extended preserves the full data/async stack; baseline only requires PostgreSQL
    # and exposes optional integrations as disabled capabilities.
    deployment_mode: Literal["baseline", "extended"] = "extended"
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
    #: Per-statement timeout in **seconds** sent to PostgreSQL via asyncpg
    #: ``server_settings.statement_timeout`` (0 disables).  Prevents a slow
    #: query from pinning a pooled connection indefinitely.  NOTE: external
    #: reference (geekblogs) was unavailable, so this follows the general
    #: PostgreSQL/asyncpg best practice of a bounded statement_timeout.
    db_statement_timeout: int = 30

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
    # Override in deployments; the development default is intentionally non-secret.
    analytics_ip_salt: str = "soymutdb-analytics-dev"
    # Only direct peers listed here may supply a client IP through X-Forwarded-For.
    # The empty default prevents direct callers from spoofing telemetry hashes.
    analytics_trusted_proxy_ips: tuple[str, ...] = ()
    max_sync_rows: int = 10000

    # ----------------------------------------------------------------- Redis
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 3600
    rate_limit_per_minute: int = 60
    login_rate_limit_window: int = Field(default=60, ge=1)
    login_rate_limit_max: int = Field(default=10, ge=1)
    #: Default TTL (seconds) for the cache-aside read-through helper in
    #: ``app.services.cache`` (stats / releases hotspots).
    redis_cache_default_ttl: int = 300
    #: Bounded socket timeouts so a wedged Redis degrades to a direct query
    #: instead of hanging the request path.
    redis_socket_timeout: float = 2.0
    redis_socket_connect_timeout: float = 2.0

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
    #: Bound broker I/O so one publish cannot hold an outbox lease forever.
    celery_broker_connect_timeout_seconds: float = Field(default=3.0, ge=1.0, le=60.0)
    celery_broker_socket_timeout_seconds: float = Field(default=5.0, ge=1.0, le=120.0)
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
    outbox_batch_size: int = Field(default=50, ge=1, le=1000)
    #: Durable claim lifetime.  The dispatcher renews active batch leases at
    #: one third of this interval while broker delivery is in progress.
    outbox_lease_seconds: float = Field(default=60.0, ge=5.0, le=3600.0)
    #: Max send attempts per event before the row is left ``failed``.
    outbox_max_attempts: int = Field(default=5, ge=1, le=100)
    #: Sent events older than this many days are archived/deleted.
    outbox_retention_days: int = 30
    outbox_cleanup_interval_seconds: float = 3600.0

    # ----------------------------------------------------- OpenTelemetry
    otel_enabled: bool = False
    otel_service_name: str = "soymutdb-api"

    # --------------------------------------------------------------- Admin
    admin_email: str = "admin@soymutdb.local"
    admin_password: str = "admin123"

    # ---------------------------------------------------------------- SMTP
    # Email delivery is opt-in: ``smtp_enabled`` defaults to ``False`` so
    # dev/staging never send real mail.  With SMTP disabled the worker
    # renders the messages and writes them under ``logs/emails/`` instead
    # (locally verifiable).  Production sets SOYMUTDB_SMTP_ENABLED=true plus
    # the SMTP_* credentials (see deploy/.env.example).
    smtp_enabled: bool = False
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "no-reply@soymutdb.local"
    smtp_use_tls: bool = True
    #: Admin notification recipient for contact modules (seed requests …);
    #: falls back to ``admin_email`` when unset.
    smtp_admin_to: str | None = None

    @property
    def smtp_admin_to_effective(self) -> str:
        """Effective admin notification address (``smtp_admin_to`` or ``admin_email``)."""
        return self.smtp_admin_to or self.admin_email

    # --------------------------------------------------- Static publication
    # Credentials / locations for the three immutable-publication targets are
    # read here (env / secret config) and never persisted to the database.
    # They are redacted from API responses and audit logs by
    # ``services.publication_targets``.
    publication_local_root: str | None = None
    publication_artifact_bucket: str = "static-publications"
    github_pages_token: str | None = None
    github_pages_repo: str | None = None
    github_repository: str | None = None
    github_api_origin: str = "https://api.github.com"
    cloudflare_pages_api_token: str | None = None
    cloudflare_pages_account_id: str | None = None
    cloudflare_pages_project: str | None = None

    # --------------------------------------------------------------- CDN
    cdn_enabled: bool = False
    cdn_urls: list[str] = Field(default_factory=lambda: [])

    # ------------------------------------------------------------- Plugins
    # Plugin code is deployed out-of-band.  Runtime manifests are accepted
    # only when their HMAC signature verifies with this deployment secret.
    plugin_manifest_signing_key: str | None = None
    plugin_manifests_json: str = "[]"

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

        if self.jwt_algorithm not in _ALLOWED_JWT_ALGORITHMS:
            validation_errors.append(
                "jwt_algorithm must be one of HS256, HS384, or HS512"
            )

        if self.app_env == "prod":
            required_fields = [
                "database_url",
                "jwt_secret",
                "analytics_ip_salt",
            ]
            if self.deployment_mode == "extended":
                required_fields.extend(
                    ["redis_url", "s3_endpoint", "s3_access_key", "s3_secret_key"]
                )
            for field_name in ("admin_password", "admin_email"):
                if field_name in self.model_fields_set:
                    required_fields.append(field_name)
            for field_name in required_fields:
                value = getattr(self, field_name).strip()
                if not value:
                    validation_errors.append(f"{field_name} is required in production settings")

            production_default_fields = {"database_url", "analytics_ip_salt"}
            if self.deployment_mode == "extended":
                production_default_fields.update(
                    {"redis_url", "s3_endpoint", "s3_access_key", "s3_secret_key"}
                )
            # Optional bootstrap credentials may be omitted by focused callers;
            # reject their placeholder only when an operator supplied the field.
            for field_name in ("admin_password", "admin_email", "clickhouse_password"):
                if field_name in self.model_fields_set:
                    production_default_fields.add(field_name)
            for field_name, default_value in _DEFAULT_PRODUCTION_VALUES.items():
                current_value = getattr(self, field_name).strip()
                if field_name in production_default_fields and current_value == default_value:
                    validation_errors.append(
                        f"{field_name} must not use the development default in production settings"
                    )

            jwt_secret = self.jwt_secret.strip()
            if len(jwt_secret) < 32 or jwt_secret.lower() in _EXAMPLE_JWT_SECRETS:
                validation_errors.append(
                    "JWT secret must be at least 32 characters and must not be an example value"
                )

            if "admin_password" in self.model_fields_set:
                admin_password = self.admin_password.strip()
                if len(admin_password) < 12 or admin_password.lower() in _EXAMPLE_ADMIN_PASSWORDS:
                    validation_errors.append(
                        "admin password must be at least 12 characters and must not "
                        "be an example value"
                    )

            if "admin_email" in self.model_fields_set:
                admin_email = self.admin_email.strip()
                if "@" not in admin_email or admin_email == "admin@soymutdb.local":
                    validation_errors.append(
                        "admin email must be a valid non-default address in production settings"
                    )

            analytics_salt = self.analytics_ip_salt.strip()
            if len(analytics_salt) < 32 or analytics_salt == "soymutdb-analytics-dev":
                validation_errors.append(
                    "analytics_ip_salt must be at least 32 characters and must not use the development default"
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
