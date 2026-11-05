"""Custom exception hierarchy and unified error response formatting.

Every API error is serialised into a consistent JSON envelope that includes
the ``request_id`` so that logs and client-side debugging can be correlated.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from structlog import get_logger

logger = get_logger(__name__)

# Starlette >= 0.46 renamed the 422 constant (the old name was deprecated).
UNPROCESSABLE_STATUS = status.HTTP_422_UNPROCESSABLE_CONTENT

#: Fallback code emitted by ``http_exception_handler`` for a generic
#: ``HTTPException`` whose status has no dedicated domain code. It is part of
#: the public error contract even though no ``SoyMutDBError`` subclass carries
#: it: the handler emits it for 400/413/500/503 (and any unmapped status).
HTTP_ERROR_CODE = "http_error"

#: Status -> stable error code for the generic ``HTTPException`` handler.
#: Kept beside the handler that consumes it so the two cannot drift.
HTTP_STATUS_ERROR_CODES: dict[int, str] = {
    status.HTTP_401_UNAUTHORIZED: "authentication_failed",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
}


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class SoyMutDBError(Exception):
    """Base class for all SoyMutDB domain errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(SoyMutDBError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


class PluginDisabledError(NotFoundError):
    """A deployed plugin exists but is intentionally hidden/disabled."""

    error_code = "plugin_disabled"


class AuthenticationError(SoyMutDBError):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "authentication_failed"


class AuthorizationError(SoyMutDBError):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "forbidden"


class ValidationError(SoyMutDBError):
    status_code = UNPROCESSABLE_STATUS
    error_code = "validation_error"


class ConflictError(SoyMutDBError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"


class SettingsVersionConflictError(ConflictError):
    """An optimistic settings mutation used a stale section version."""

    error_code = "settings_version_conflict"


class RateLimitExceededError(SoyMutDBError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "rate_limit_exceeded"

    def __init__(
        self,
        message: str,
        *,
        retry_after: int = 60,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.retry_after = max(1, int(retry_after))


class ServiceUnavailableError(SoyMutDBError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "service_unavailable"


class PluginUnavailableError(ServiceUnavailableError):
    """A plugin is enabled but not configured or currently unhealthy."""

    error_code = "plugin_unavailable"


class TaskDispatchError(ServiceUnavailableError):
    """A background task could not be handed to the Celery broker."""

    error_code = "task_dispatch_failed"


# ---------------------------------------------------------------------------
# Error-code contract catalog
# ---------------------------------------------------------------------------

def _iter_error_types(error_type: type[SoyMutDBError]) -> list[type[SoyMutDBError]]:
    """Return a flattened domain-error hierarchy for contract export."""
    out = [error_type]
    for child in error_type.__subclasses__():
        out.extend(_iter_error_types(child))
    return out


def error_code_catalog() -> dict[str, str]:
    """Return the deterministic public catalog of *every* emitted error code.

    ``http_error`` has no ``SoyMutDBError`` subclass, but the generic HTTP
    exception handler emits it, so omitting it leaves a code that a client can
    receive yet cannot discover from the published contract.
    """
    catalog = {
        error_type.error_code: (error_type.__doc__ or "").strip()
        for error_type in sorted(_iter_error_types(SoyMutDBError), key=lambda item: item.error_code)
    }
    catalog[HTTP_ERROR_CODE] = (
        "Generic HTTPException fallback; see x-error-status for the statuses that use it."
    )
    return dict(sorted(catalog.items()))


def error_status_map() -> dict[str, int | None]:
    """Return the published binding from stable error code to HTTP status.

    Derived from the exception hierarchy, never hand-kept. ``http_error`` maps
    to ``None`` because it is the multi-status fallback, not a single status.
    """
    binding = {
        error_type.error_code: error_type.status_code
        for error_type in _iter_error_types(SoyMutDBError)
    }
    binding[HTTP_ERROR_CODE] = None
    return dict(sorted(binding.items()))


def error_status_contract() -> dict[str, Any]:
    """Return the full machine-readable status/error-code contract.

    ``by_code`` binds each published code to the status that emits it;
    ``http_exception`` publishes the status -> code mapping the generic
    ``HTTPException`` handler actually consumes, including its fallback. A
    client can now resolve both directions without guessing from prose.
    """
    mapped = {
        str(status_code): code
        for status_code, code in sorted(HTTP_STATUS_ERROR_CODES.items())
    }
    return {
        "by_code": error_status_map(),
        "http_exception": {**mapped, "fallback": HTTP_ERROR_CODE},
    }


# ---------------------------------------------------------------------------
# Unified error envelope
# ---------------------------------------------------------------------------


def _error_envelope(
    request: Request,
    status_code: int,
    error_code: str,
    message: str,
    details: dict[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    # ``RequestIdMiddleware`` normally sets ``request.state.request_id``; fall
    # back to a fresh id so the envelope always carries a correlatable value
    # (e.g. in unit tests or if middleware registration is skipped).
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    return {
        "error": {
            "code": error_code,
            "message": message,
            "details": details or {},
        },
        "request_id": request_id,
        "status_code": status_code,
    }


def _request_id(request: Request) -> str:
    """Return the request id (generating a fallback when middleware is absent)."""
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


async def soy_mut_db_exception_handler(
    request: Request, exc: SoyMutDBError
) -> JSONResponse:
    """Handle :class:`SoyMutDBError` subclasses."""
    logger.warning(
        "domain_error",
        error_code=exc.error_code,
        message=exc.message,
        path=request.url.path,
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(
            _error_envelope(request, exc.status_code, exc.error_code, exc.message, exc.details)
        ),
        headers=(
            {"Retry-After": str(exc.retry_after)}
            if isinstance(exc, RateLimitExceededError)
            # Auth failures occur on internal routes; they must never enter
            # shared caches (existence-oracle / cache-poisoning safety).
            else {"Cache-Control": "private, no-store"}
            if isinstance(exc, (AuthenticationError, AuthorizationError))
            else None
        ),
    )


async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Handle generic :class:`HTTPException`."""
    code = HTTP_STATUS_ERROR_CODES.get(exc.status_code, HTTP_ERROR_CODE)
    headers: dict[str, str] | None = None
    if exc.status_code in (401, 403):
        # Auth failures occur on internal routes; they must never enter
        # shared caches (existence-oracle / cache-poisoning safety).
        headers = {"Cache-Control": "private, no-store"}
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(
            _error_envelope(request, exc.status_code, code, str(exc.detail))
        ),
        headers=headers,
    )


def _sanitize_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Flatten Pydantic validation errors into a safe, field-level shape.

    Only ``field`` / ``message`` / ``type`` are exposed — internal structures
    such as ``ctx``, ``url`` or input values are never leaked to clients.
    The ``field`` is the user-facing location path (e.g. ``query.chromosome``).
    """
    cleaned: list[dict[str, str]] = []
    for err in errors:
        loc = err.get("loc") or ()
        field = ".".join(str(part) for part in loc)
        message = str(err.get("msg", "Invalid value"))
        # Pydantic prefixes some messages with "Value error, ".
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        cleaned.append(
            {
                "field": field,
                "message": message,
                "type": str(err.get("type", "value_error")),
            }
        )
    return cleaned


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors with a structured envelope.

    The 422 response carries field-level ``errors`` (sanitised, no Pydantic
    internals) plus the unified error envelope fields (``request_id`` etc.).
    """
    errors = _sanitize_validation_errors(list(exc.errors()))
    return JSONResponse(
        status_code=UNPROCESSABLE_STATUS,
        content=jsonable_encoder(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": {},
                },
                "errors": errors,
                "request_id": _request_id(request),
                "status_code": UNPROCESSABLE_STATUS,
            }
        ),
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Catch-all handler that logs the full traceback and returns 500.

    The response body is a fixed, generic message — the exception class,
    message, traceback, SQL, or file paths are NEVER included in the payload
    (they only reach the server-side log via ``logger.exception``).
    """
    logger.exception(
        "unhandled_exception",
        path=request.url.path,
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=jsonable_encoder(
            _error_envelope(
                request,
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "internal_error",
                "An unexpected error occurred",
            )
        ),
    )
