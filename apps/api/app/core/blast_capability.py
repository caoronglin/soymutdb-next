"""Purpose-specific, expiring capabilities for explicitly anonymous BLAST jobs.

These JWTs cannot authenticate an account: their type and subject namespace
are distinct from access/refresh tokens. No token or signing diagnostic is
included in an error or a URL.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from jwt import InvalidTokenError

from .config import get_settings
from .exceptions import AuthenticationError

PURPOSE = "blast-public-job"
PUBLIC_JOB_MARKER = "_public_blast"


def issue_blast_capability(job_id: uuid.UUID) -> tuple[str, datetime]:
    settings = get_settings()
    now = datetime.now(UTC).replace(microsecond=0)
    expires_at = now + timedelta(seconds=settings.blast_public_token_ttl_seconds)
    token = jwt.encode(
        {
            "sub": str(job_id),
            "type": PURPOSE,
            "purpose": PURPOSE,
            "jti": secrets.token_urlsafe(32),
            "iat": now,
            "exp": expires_at,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_at


def verify_blast_capability(token: str | None, job_id: uuid.UUID) -> datetime:
    settings = get_settings()
    try:
        if not token or len(token) > 4096:
            raise ValueError("Missing capability")
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "type", "purpose", "jti", "iat", "exp"]},
        )
        if (
            claims["type"] != PURPOSE
            or claims["purpose"] != PURPOSE
            or claims["sub"] != str(job_id)
            or not isinstance(claims["jti"], str)
            or len(claims["jti"]) < 32
            or isinstance(claims["exp"], bool)
            or isinstance(claims["iat"], bool)
            or not 0 < claims["exp"] - claims["iat"] <= 86400
        ):
            raise ValueError("Invalid capability claims")
        return datetime.fromtimestamp(claims["exp"], UTC)
    except (InvalidTokenError, ValueError, TypeError, OverflowError) as exc:
        raise AuthenticationError("Invalid or expired BLAST capability") from exc
