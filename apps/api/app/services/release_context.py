"""Resolve and carry the immutable data release used by public queries."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import get_db
from ..core.exceptions import (
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from ..models.content import Release, ReleaseStatus
from ..models.data_publishing import ActiveRelease

_CURSOR_VERSION = 1


@dataclass(frozen=True, slots=True)
class ReleaseContext:
    """Resolved release identity passed explicitly to repository services."""

    release_id: int
    assembly_id: int | None = None
    assembly: str | None = None

    @property
    def release_key(self) -> str:
        """Return the ClickHouse representation of the release id."""
        return str(self.release_id)

    def identity(self) -> dict[str, Any]:
        """Return stable, non-secret fields suitable for cursor binding."""
        return {
            "release_id": self.release_id,
            "assembly_id": self.assembly_id,
            "assembly": self.assembly,
        }


async def resolve_release_context(
    db: AsyncSession,
    requested_release_id: int | None = None,
) -> ReleaseContext:
    """Resolve a published release, defaulting to the singleton active pointer."""
    if requested_release_id is None:
        statement = (
            select(Release)
            .join(ActiveRelease, ActiveRelease.release_id == Release.id)
            .where(
                ActiveRelease.id == 1,
                Release.status == ReleaseStatus.PUBLISHED,
            )
        )
    else:
        statement = select(Release).where(
            Release.id == requested_release_id,
            Release.status == ReleaseStatus.PUBLISHED,
        )

    release = (await db.execute(statement)).scalar_one_or_none()
    if release is None and requested_release_id is None:
        raise ServiceUnavailableError("No active data release is available")
    if release is None:
        raise NotFoundError(f"Release {requested_release_id} is not available")

    return ReleaseContext(
        release_id=int(release.id),
        assembly_id=release.assembly_id,
        assembly=release.assembly,
    )


async def get_release_context(
    db: AsyncSession = Depends(get_db),
    release_id: int | None = Query(default=None, ge=1),
    pinned_release_id: int | None = Header(
        default=None,
        alias="X-SoyMutDB-Release",
        ge=1,
    ),
) -> ReleaseContext:
    """FastAPI dependency resolving query/header pins or the active release."""
    if release_id is not None and pinned_release_id is not None and release_id != pinned_release_id:
        raise ValidationError("Conflicting release ids were provided")
    requested_release_id = release_id if release_id is not None else pinned_release_id
    return await resolve_release_context(db, requested_release_id)


def encode_bound_cursor(
    *,
    kind: str,
    sort_key: Mapping[str, Any],
    release_context: ReleaseContext,
    filters: Mapping[str, Any] | None = None,
) -> str:
    """Encode and authenticate a release/filter-bound keyset cursor."""
    payload = {
        "v": _CURSOR_VERSION,
        "k": kind,
        "c": _context_digest(release_context, filters),
        "s": dict(sort_key),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body = _urlsafe_encode(raw)
    signature = hmac.new(_cursor_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_urlsafe_encode(signature)}"


def decode_bound_cursor(
    cursor: str,
    *,
    kind: str,
    release_context: ReleaseContext,
    filters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify a cursor and return its sort-key mapping."""
    try:
        body, encoded_signature = cursor.split(".", maxsplit=1)
        body_bytes = body.encode("ascii")
        supplied_signature = _urlsafe_decode(encoded_signature)
    except Exception as exc:
        raise ValidationError("Invalid cursor encoding") from exc

    expected_signature = hmac.new(_cursor_secret(), body_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_signature, supplied_signature):
        raise ValidationError("Invalid cursor signature")

    try:
        payload = json.loads(_urlsafe_decode(body))
    except Exception as exc:
        raise ValidationError("Invalid cursor payload") from exc

    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
        raise ValidationError("Invalid cursor version")
    if payload.get("k") != kind:
        raise ValidationError("Invalid cursor kind")
    if payload.get("c") != _context_digest(release_context, filters):
        raise ValidationError("Cursor context does not match this release or filter set")
    sort_key = payload.get("s")
    if not isinstance(sort_key, dict):
        raise ValidationError("Invalid cursor sort key")
    return sort_key


def _context_digest(
    release_context: ReleaseContext,
    filters: Mapping[str, Any] | None,
) -> str:
    payload = {
        "release": release_context.identity(),
        "filters": dict(filters or {}),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _cursor_secret() -> bytes:
    return get_settings().jwt_secret.encode("utf-8")


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(
        f"{value}{padding}",
        altchars=b"-_",
        validate=True,
    )
