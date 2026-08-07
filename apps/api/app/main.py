"""SoyMutDB FastAPI application entry point.

Mounts the real modular v1 router (no placeholder routes), configures
middleware, exception handlers, and lifespan startup/shutdown.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import ORJSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .api.v1.router import api_router
from .core.config import get_settings
from .core.database import close_db
from .core.exceptions import (
    SoyMutDBError,
    http_exception_handler,
    soy_mut_db_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from .core.metrics import get_metrics_app
from .core.middleware import RequestIdMiddleware
from .schemas.error import ErrorDetail, ErrorResponse, FieldError, ValidationErrorResponse

logger = structlog.get_logger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# OpenAPI metadata
# ---------------------------------------------------------------------------

OPENAPI_DESCRIPTION = """
SoyMutDB API — high-performance soybean genomic variant platform.

## Error contract

Every error response uses the unified envelope (see `ErrorResponse`):

```json
{
  "error": {"code": "not_found", "message": "...", "details": {}},
  "request_id": "…",
  "status_code": 404
}
```

- `request_id` is always present and echoed in the `X-Request-ID` header.
- Validation failures (422) additionally return a field-level `errors` array
  (`ValidationErrorResponse`); internal framework structures are never
  exposed.
- 500 responses never include stack traces, SQL, paths, or exception text.

## Authentication

- **Bearer**: JWT access tokens via `Authorization: Bearer <token>`
  (obtained from `POST /api/v1/auth/login`).
- **Cookie**: refresh sessions use the HttpOnly `soymutdb_refresh` cookie
  (path-scoped to `/api/v1/auth`) for `POST /api/v1/auth/refresh` and
  `POST /api/v1/auth/logout`.
"""

OPENAPI_TAGS = [
    {"name": "health", "description": "Liveness / readiness probes."},
    {"name": "auth", "description": "Registration, login, token refresh, logout, profile."},
    {"name": "stats", "description": "Public statistics and dashboard aggregates."},
    {"name": "admin", "description": "Administrator-only operations (audit logs, config, dashboard)."},
    {"name": "analytics", "description": "Behavioural analytics tracking and summaries."},
    {"name": "widgets", "description": "Dashboard widgets and layouts."},
]


def _build_openapi_schema(app: FastAPI) -> dict[str, Any]:
    """Build the OpenAPI schema with the unified error contract.

    Injects the error schemas into ``components.schemas``, documents the
    security schemes (bearer + refresh cookie), and attaches the 422/500
    error responses to every path operation.
    """
    if app.openapi_schema is not None:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
        webhooks=app.webhooks.routes,
        tags=app.openapi_tags,
        servers=app.servers,
        separate_input_output_schemas=getattr(
            app, "separate_input_output_schemas", True
        ),
    )

    components = schema.setdefault("components", {})
    components.setdefault("schemas", {}).update(
        {
            "ErrorDetail": ErrorDetail.model_json_schema(
                ref_template="#/components/schemas/{model}"
            ),
            "ErrorResponse": ErrorResponse.model_json_schema(
                ref_template="#/components/schemas/{model}"
            ),
            "FieldError": FieldError.model_json_schema(
                ref_template="#/components/schemas/{model}"
            ),
            "ValidationErrorResponse": ValidationErrorResponse.model_json_schema(
                ref_template="#/components/schemas/{model}"
            ),
        }
    )

    security_schemes = components.setdefault("securitySchemes", {})
    if "HTTPBearer" in security_schemes:
        security_schemes["HTTPBearer"]["description"] = (
            "JWT access token. Obtain one via POST /api/v1/auth/login "
            "and send it as `Authorization: Bearer <token>`."
        )
    security_schemes.setdefault(
        "refreshCookie",
        {
            "type": "apiKey",
            "in": "cookie",
            "name": settings.refresh_cookie_name,
            "description": (
                "HttpOnly refresh session cookie (path-scoped to /api/v1/auth); "
                "used by POST /api/v1/auth/refresh and /logout."
            ),
        },
    )

    # Document the unified error responses on every path operation.
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            responses = operation["responses"]
            responses.setdefault(
                "422",
                {
                    "description": "Validation Error",
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/ValidationErrorResponse"
                            }
                        }
                    },
                },
            )
            responses.setdefault(
                "500",
                {
                    "description": "Internal Server Error",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                        }
                    },
                },
            )

    app.openapi_schema = schema
    return schema


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown lifecycle.

    Database connections (PostgreSQL, ClickHouse, Redis) are lazily
    initialised on first use; we only need to dispose them on shutdown.
    """
    logger.info("api.startup", env=settings.app_env, debug=settings.debug)
    yield
    await close_db()
    logger.info("api.shutdown")


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        return response


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        description=OPENAPI_DESCRIPTION,
        version="2.0.0",
        openapi_tags=OPENAPI_TAGS,
        default_response_class=ORJSONResponse,
        docs_url="/api/docs" if settings.debug else None,
        redoc_url="/api/redoc" if settings.debug else None,
        openapi_url="/api/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    # Custom OpenAPI: injects the unified error contract and security schemes.
    app.openapi = lambda: _build_openapi_schema(app)  # type: ignore[method-assign]

    # --- Middleware (order matters: outermost first) ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Content-Type",
            "Range",
            "X-Requested-With",
            "X-Request-ID",
        ],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)

    # --- Exception handlers ---
    app.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # --- Routes ---
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    # Prometheus metrics endpoint
    app.mount("/metrics", get_metrics_app())

    # Root health check
    @app.get("/health", tags=["health"])
    async def root_health() -> dict[str, str]:
        return {"status": "ok", "service": "soymutdb-api"}

    return app


app = create_app()
