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

#: The nginx edge limiter allows 100 requests/second per client for the
#: ``api`` zone (``infra/nginx/conf.d/default.conf``:
#: ``limit_req zone=api burst=200 nodelay``), i.e. 6000 requests per minute.
#: The application-layer anonymous-read budget must never be *lower* than
#: that rate: a tighter application budget turns the API into the real
#: bottleneck and makes the edge quota dead configuration.  The invariant is
#: enforced by :meth:`Settings.validate_security_configuration`.
EDGE_PUBLIC_READ_RATE_LIMIT_FLOOR_PER_MINUTE = 6000


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
    # The unpublished ``03_soymut`` preview is available only in a local,
    # baseline deployment after an explicit operator opt-in. Its routes also
    # require a loopback TCP peer; this flag never changes public search APIs.
    local_test_preview_enabled: bool = False
    # Bundled demo fixtures (SRA sample runs, the demo Zea mays run) are only
    # served when a deployment explicitly opts in. Without this flag a live
    # upstream failure returns 503 instead of presenting fixture data as if it
    # were the requested record.
    demo_fixtures_enabled: bool = False
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
    #: LIFO checkout keeps a small hot set of server connections in use and
    #: lets the rest age out, instead of round-robining every pooled
    #: connection through PostgreSQL on each burst.
    db_pool_use_lifo: bool = True
    # Process topology is consumed by the container entrypoint. Keep these
    # values in Settings so validation/docs share one canonical contract.
    api_workers: int = Field(default=2, ge=1, le=16)
    api_graceful_shutdown_seconds: int = Field(default=30, ge=5, le=600)
    db_echo: bool = False
    #: Per-statement timeout in **seconds** sent to PostgreSQL via asyncpg
    #: ``server_settings.statement_timeout`` (0 disables).  Prevents a slow
    #: query from pinning a pooled connection indefinitely.  NOTE: external
    #: reference (geekblogs) was unavailable, so this follows the general
    #: PostgreSQL/asyncpg best practice of a bounded statement_timeout.
    db_statement_timeout: int = 30
    #: PostgreSQL JIT compilation.  Measured on the isolated 200k-variant
    #: baseline, the stats aggregate triggered JIT and spent ~500 ms of a
    #: ~640 ms statement inside the JIT (generation/inlining/optimization/
    #: emission), while execution without JIT took ~130 ms.  Aggregates and
    #: index lookups are not the long-running analytical queries JIT targets,
    #: so it is off by default; enable per deployment if a real workload
    #: profile shows a win.
    db_jit_enabled: bool = False

    # ------------------------------------------------------------ ClickHouse
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "soymutdb"
    clickhouse_password: str = "soymutdb_dev_password"
    clickhouse_database: str = "soymutdb"
    clickhouse_secure: bool = False
    clickhouse_connect_timeout: int = 10
    clickhouse_send_receive_timeout: int = 30
    # Override in deployments; the development default is intentionally non-secret.
    analytics_ip_salt: str = "soymutdb-analytics-dev"
    # Only direct peers listed here may supply a client IP through X-Forwarded-For.
    # The empty default prevents direct callers from spoofing telemetry hashes.
    analytics_trusted_proxy_ips: tuple[str, ...] = ()

    # ----------------------------------------------------------------- Redis
    redis_url: str = "redis://localhost:6379/0"

    # ----------------------------------------------------------- Rate limits
    # The global inbound request limiter lives in ``app/core/middleware.py``
    # and is wired into the ASGI stack by ``app/main.py``.  It is graded by
    # request class (see the plan in
    # ``docs/superpowers/plans/2026-09-15-phase-1-baseline-security-plan.md``,
    # section S-2):
    #   * anonymous public reads -> ``public_read_rate_limit_per_minute``
    #     and **fail open** while the limiter backend is unavailable;
    #   * writes (POST/PUT/PATCH/DELETE) -> ``write_rate_limit_per_minute``
    #     and **fail closed** (503) while the backend is unavailable;
    #   * ``/api/v1/auth/*`` keeps its own dedicated limiter
    #     (``app/core/ratelimit.py``) and is therefore not counted here.
    #: Master switch of the global request limiter.  Production refuses to
    #: start with it disabled, so there is no way to run a live deployment
    #: without the request budget.
    rate_limit_enabled: bool = True
    #: Marks a non-production deployment as a benchmark run (capacity
    #: measurements must not be distorted by the request budget).  Production
    #: refuses to start with it enabled.
    benchmark_mode: bool = False
    #: Anonymous public reads (GET/HEAD without a verified principal) per
    #: peer per minute.  Must stay at or above
    #: :data:`EDGE_PUBLIC_READ_RATE_LIMIT_FLOOR_PER_MINUTE` (the nginx edge
    #: ``limit_req`` rate of 100 r/s expressed per minute).
    public_read_rate_limit_per_minute: int = Field(default=6000, ge=1)
    #: Write operations (POST/PUT/PATCH/DELETE) per peer per minute.
    write_rate_limit_per_minute: int = Field(default=120, ge=1)
    login_rate_limit_window: int = Field(default=60, ge=1)
    login_rate_limit_max: int = Field(default=10, ge=1)
    # Second dimension: one source address must not be able to spray many
    # usernames. The per-(username, IP) budget above alone never bounds an
    # attacker who rotates the username, because every pair gets a fresh
    # counter; this budget bounds the address instead.
    login_ip_rate_limit_max: int = Field(default=50, ge=1)
    # External article previews issue bounded outbound requests, so they need a
    # tighter per-editor budget than the generic inbound middleware limit.
    external_article_preview_rate_limit_window: int = Field(default=300, ge=1)
    external_article_preview_rate_limit_max: int = Field(default=6, ge=1)
    #: Default TTL (seconds) for the cache-aside read-through helper in
    #: ``app.services.cache`` (stats / releases hotspots).
    redis_cache_default_ttl: int = 300
    #: Bounded socket timeouts so a wedged Redis degrades to a direct query
    #: instead of hanging the request path.
    redis_socket_timeout: float = 2.0
    redis_socket_connect_timeout: float = 2.0
    #: Upper bound on pooled Redis connections per API process.  redis-py's
    #: default pool is unbounded, so a slow Redis plus concurrent requests
    #: could open sockets without limit; checkout then blocks instead.
    redis_max_connections: int = Field(default=64, ge=1)

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
    blast_max_length: int = 100000
    blast_default_db: str = "williams82_cds"
    blast_max_active_jobs_per_user: int = Field(default=3, ge=1, le=20)
    # Public capability jobs share the existing worker, with a separate peer budget.
    blast_public_enabled: bool = True
    blast_public_max_length: int = Field(default=10000, ge=10, le=100000)
    blast_public_token_ttl_seconds: int = Field(default=86400, ge=1, le=86400)
    blast_public_rate_limit_max: int = Field(default=5, ge=1)
    blast_public_rate_limit_window: int = Field(default=3600, ge=1)
    #: Maximum delivery attempts per BLAST job (broker-level retries only;
    #: the worker itself is idempotent on top of this).
    blast_max_attempts: int = 3

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

    # --------------------------------------------------------------- Admin
    admin_email: str = "admin@soymutdb.local"
    admin_password: str = "admin123"

    # SMTP delivery is owned by the worker (``soymutdb_worker.tasks.email``
    # reads the ``SOYMUTDB_SMTP_*`` environment directly); the API never sends
    # mail, so it intentionally declares no SMTP settings.

    # --------------------------------------------------- Static publication
    # Credentials / locations for the three immutable-publication targets are
    # read here (env / secret config) and never persisted to the database.
    # They are redacted from API responses and audit logs by
    # ``services.publication_targets``.
    publication_local_root: str | None = None
    github_pages_token: str | None = None
    github_pages_repo: str | None = None
    github_repository: str | None = None
    github_api_origin: str = "https://api.github.com"
    cloudflare_pages_api_token: str | None = None
    cloudflare_pages_account_id: str | None = None
    cloudflare_pages_project: str | None = None

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

    # Rust bio-core engine selector.  ``python`` is documented as a legacy
    # fallback but there is NO equivalent Python implementation of these
    # algorithms, so selecting it must fail closed rather than silently return
    # empty results.  ``rust`` is the only value that enables computation.
    bio_engine: Literal["rust", "python"] = "rust"

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

        # The preview dataset must never reach a production deployment, and
        # `app_env=dev` already guarantees that. Requiring `deployment_mode ==
        # "baseline"` on top added nothing except making the local *full-stack*
        # (`extended`) run unable to preview its own test data, so the flag is
        # allowed in either local mode.
        if self.local_test_preview_enabled and self.app_env != "dev":
            validation_errors.append(
                "local_test_preview_enabled requires app_env=dev"
            )

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

        # The application layer must never be the tighter of the two limits.
        # The nginx edge limiter allows 100 r/s per client (6000/min); an
        # application budget below that rate turns the API into the real
        # bottleneck and makes the edge quota meaningless.
        if (
            self.public_read_rate_limit_per_minute
            < EDGE_PUBLIC_READ_RATE_LIMIT_FLOOR_PER_MINUTE
        ):
            validation_errors.append(
                "public_read_rate_limit_per_minute must be at least "
                f"{EDGE_PUBLIC_READ_RATE_LIMIT_FLOOR_PER_MINUTE} (the nginx edge "
                "limit_req rate of 100 r/s expressed per minute)"
            )

        if self.app_env == "prod":
            # A production deployment must never run without the request
            # budget, and it must never run in benchmark mode.  Both are
            # startup failures, not warnings: there is no header-based
            # bypass for the limiter.
            if self.benchmark_mode:
                validation_errors.append(
                    "benchmark_mode must not be enabled in production"
                )
            if not self.rate_limit_enabled:
                validation_errors.append(
                    "rate_limit_enabled must not be disabled in production"
                )

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
                    "analytics_ip_salt must be at least 32 characters and must not use "
                    "the development default"
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
