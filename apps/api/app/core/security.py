"""Security utilities: Argon2id password hashing, JWT, RBAC, and password strength.

Argon2id is used for password hashing via ``argon2-cffi`` (NOT bcrypt).
JWT tokens are issued with ``PyJWT``.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError
import jwt
from jwt import InvalidTokenError

from .compat import StrEnum
from .config import get_settings
from .exceptions import AuthorizationError

settings = get_settings()

# ---------------------------------------------------------------------------
# Password strength
# ---------------------------------------------------------------------------

_COMMON_WEAK_PASSWORDS: set[str] = {
    "password",
    "admin",
    "soymutdb",
    "12345678",
    "qwerty",
    "abc123",
}

_SPECIAL_CHARS = re.compile(r"[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]")


def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate password complexity requirements.

    Returns:
        (True, "OK") if the password meets all requirements, or
        (False, reason_string) describing the first failure.
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"

    if password.lower() in _COMMON_WEAK_PASSWORDS:
        return False, "Password is too common"

    types_present = sum(
        [
            bool(re.search(r"[A-Z]", password)),
            bool(re.search(r"[a-z]", password)),
            bool(re.search(r"\d", password)),
            bool(_SPECIAL_CHARS.search(password)),
        ]
    )
    if types_present < 3:
        return (
            False,
            "Password must contain at least 3 of: uppercase, lowercase, "
            "digits, and special characters",
        )

    return True, "OK"


def password_strength_score(password: str) -> int:
    """Return a password strength score from 0 (weak) to 4 (strong).

    Scoring:
        0 – fewer than 8 characters
        1 – 8+ chars but <3 character types
        2 – 8+ chars, 3 character types
        3 – 8+ chars, 4 character types
        4 – 8+ chars, 4 types, and length >= 12
    """
    if len(password) < 8:
        return 0

    if password.lower() in _COMMON_WEAK_PASSWORDS:
        return 1

    types_present = sum(
        [
            bool(re.search(r"[A-Z]", password)),
            bool(re.search(r"[a-z]", password)),
            bool(re.search(r"\d", password)),
            bool(_SPECIAL_CHARS.search(password)),
        ]
    )

    if types_present < 3:
        return 1
    if types_present == 3:
        return 2
    # 4 types present
    return 4 if len(password) >= 12 else 3

# Argon2id hasher with sensible production defaults.
# Argon2id is the recommended variant per RFC 9106 (side-channel + GPU resistant).
_pwd_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,  # argon2id
)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class RoleName(StrEnum):
    """The 10 RBAC roles supported by SoyMutDB.

    Ordered roughly from least to most privileged.
    """

    VIEWER = "viewer"
    RESEARCHER = "researcher"
    CURATOR = "curator"
    DATA_MANAGER = "data_manager"
    TRACK_MANAGER = "track_manager"
    BLAST_MANAGER = "blast_manager"
    SEED_MANAGER = "seed_manager"
    CONTENT_EDITOR = "content_editor"
    AUDITOR = "auditor"
    ADMINISTRATOR = "administrator"


# Explicit grants preserve the common viewer -> researcher -> curator
# progression without treating domain-specific roles as interchangeable.
# Administrators remain the only role that implicitly grants every role.
_COMMON_GRANTS = frozenset(
    {RoleName.VIEWER, RoleName.RESEARCHER, RoleName.CURATOR}
)
_ROLE_GRANTS: dict[RoleName, frozenset[RoleName]] = {
    RoleName.VIEWER: frozenset({RoleName.VIEWER}),
    RoleName.RESEARCHER: frozenset({RoleName.VIEWER, RoleName.RESEARCHER}),
    RoleName.CURATOR: _COMMON_GRANTS,
    RoleName.DATA_MANAGER: _COMMON_GRANTS | {RoleName.DATA_MANAGER},
    RoleName.TRACK_MANAGER: _COMMON_GRANTS | {RoleName.TRACK_MANAGER},
    RoleName.BLAST_MANAGER: _COMMON_GRANTS | {RoleName.BLAST_MANAGER},
    RoleName.SEED_MANAGER: _COMMON_GRANTS | {RoleName.SEED_MANAGER},
    RoleName.CONTENT_EDITOR: _COMMON_GRANTS | {RoleName.CONTENT_EDITOR},
    RoleName.AUDITOR: _COMMON_GRANTS | {RoleName.AUDITOR},
    RoleName.ADMINISTRATOR: frozenset(RoleName),
}


def has_role(user_roles: list[str], required: RoleName) -> bool:
    """Return whether any assigned role explicitly grants ``required``."""
    for role_name in user_roles:
        try:
            assigned_role = RoleName(role_name)
        except ValueError:
            # Unknown role string -- ignore defensively.
            continue
        if required in _ROLE_GRANTS[assigned_role]:
            return True
    return False


def require_admin_roles(user_roles: list[str]) -> None:
    """Require the administrator role for protected admin operations."""
    if not has_role(user_roles, RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator role required")


# ---------------------------------------------------------------------------
# Password hashing (Argon2id)
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return _pwd_hasher.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against an Argon2id hash.

    Returns ``False`` on mismatch or invalid hash (never raises).
    """
    try:
        return _pwd_hasher.verify(password_hash, plain_password)
    except (VerifyMismatchError, InvalidHashError):
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT access token.

    Claims are kept minimal: ``sub`` (user id), ``roles``, ``jti``, ``type``,
    ``iat`` and ``exp``.  ``jti`` is a fresh random id per token, usable for
    correlation and revocation bookkeeping.
    """
    now = datetime.now(UTC)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode: dict[str, Any] = {
        "exp": expire,
        "sub": str(subject),
        "type": "access",
        "iat": now,
        "jti": uuid.uuid4().hex,
    }
    if extra:
        to_encode.update(extra)
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str, jti: str | None = None) -> str:
    """Create a signed JWT refresh token.

    The ``jti`` claim identifies the token; the server stores only the
    SHA-256 hash of the full token string (see :func:`hash_refresh_token`).
    """
    expire = datetime.now(UTC) + timedelta(
        days=settings.refresh_token_expire_days
    )
    to_encode: dict[str, Any] = {
        "exp": expire,
        "sub": str(subject),
        "type": "refresh",
        "iat": datetime.now(UTC),
        "jti": jti or uuid.uuid4().hex,
    }
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def hash_refresh_token(token: str) -> str:
    """Return the SHA-256 hex digest used as the server-side token key.

    Plaintext refresh tokens are never stored; only this digest is persisted.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token.

    Raises :class:`ValueError` if the token is invalid or expired.
    """
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except InvalidTokenError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc


def get_token_subject(token: str) -> str:
    """Extract the ``sub`` claim from a JWT token."""
    payload = decode_token(token)
    if "sub" not in payload:
        raise ValueError("Token missing subject claim")
    return payload["sub"]
