"""Pydantic v2 schemas for the notification centre (D2).

Contract:
- ``GET  /api/v1/notifications``          -> NotificationListResponse
- ``GET  /api/v1/notifications/unread-count`` -> UnreadCountResponse
- ``POST /api/v1/notifications/read``     MarkReadRequest -> MarkReadResponse
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


def _coerce_id_to_str(value: object) -> object:
    """Pydantic v2 does not coerce uuid.UUID -> str; ORM ids are UUIDs."""
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


class NotificationResponse(BaseModel):
    """One notification entry (list item)."""

    id: str
    type: str
    title: str
    body: str
    link: str | None = None
    read_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

    _coerce_id = field_validator("id", mode="before")(_coerce_id_to_str)


class NotificationListResponse(BaseModel):
    """Paginated notification list (unread first) plus counters."""

    items: list[NotificationResponse]
    total: int
    unread_count: int


class UnreadCountResponse(BaseModel):
    """Number of unread notifications for the current user."""

    unread_count: int


class MarkReadRequest(BaseModel):
    """Mark a subset of notifications read (``ids``) or all of them (``all``)."""

    ids: list[str] | None = Field(default=None, max_length=100)
    all: bool = False

    @model_validator(mode="after")
    def _require_selector(self) -> "MarkReadRequest":
        if not self.all and not self.ids:
            raise ValueError("Provide 'ids' or set 'all' to true")
        return self


class MarkReadResponse(BaseModel):
    """Number of rows flipped to read."""

    marked: int
