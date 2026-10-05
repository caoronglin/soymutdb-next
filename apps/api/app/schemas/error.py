"""OpenAPI error-contract schemas.

These mirror the runtime envelope produced by
``app.core.exceptions`` handlers and are injected into the generated
OpenAPI document (``components.schemas``) so clients can rely on a
stable error contract.

Runtime behaviour lives in ``app.core.exceptions``; these classes are
for documentation only and are intentionally not used as response
serializers.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Machine-readable error detail (inside the ``error`` envelope)."""

    code: str = Field(..., description="Stable machine-readable error code, e.g. ``not_found``.")
    message: str = Field(..., description="Human-readable error message.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured context (never contains secrets or stack traces).",
    )


class FieldError(BaseModel):
    """Field-level validation error for 422 responses."""

    field: str = Field(..., description="Dot-joined request field path, e.g. ``query.chromosome``.")
    message: str = Field(..., description="Human-readable validation message.")
    type: str = Field(..., description="Pydantic error type identifier (e.g. ``string_type``).")


class ErrorResponse(BaseModel):
    """Unified error envelope returned by every API error."""

    error: ErrorDetail
    request_id: str = Field(
        ..., description="Correlation id (also echoed in the ``X-Request-ID`` header)."
    )
    status_code: int = Field(..., description="HTTP status code.")


class ValidationErrorResponse(ErrorResponse):
    """422 response: unified envelope plus field-level ``errors``."""

    errors: list[FieldError] = Field(
        default_factory=list,
        description="Field-level validation errors (sanitised; no internal structure exposed).",
    )
