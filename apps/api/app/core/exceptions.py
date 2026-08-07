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


class TaskDispatchError(ServiceUnavailableError):
    """A background task could not be handed to the Celery broker."""

    error_code = "task_dispatch_failed"


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
            else None
        ),
    )


async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Handle generic :class:`HTTPException`."""
    code = "http_error"
    if exc.status_code == 401:
        code = "authentication_failed"
    elif exc.status_code == 403:
        code = "forbidden"
    elif exc.status_code == 404:
        code = "not_found"
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(
            _error_envelope(request, exc.status_code, code, str(exc.detail))
        ),
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
