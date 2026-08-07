"""Server-side refresh-token session management.

Refresh tokens are JWTs carrying a ``jti`` claim; the server stores only the
SHA-256 hash of each token (``refresh_tokens.token_hash``) and tracks token
*families* so that rotation can detect reuse.

Rotation semantics
------------------
Every successful refresh revokes the presented token and issues a new one in
the same family (``replaced_by`` links the old row to the new one).  If a
token that was already rotated is presented again, that is treated as token
theft (reuse detection): the entire family is revoked and the request is
rejected.

Concurrency
-----------
Rotation serialises on the refresh-token row with ``SELECT ... FOR UPDATE``.
When two refresh requests present the same token concurrently, the first to
lock the row rotates it and commits; the second one then observes a revoked
row, triggers reuse detection and fails.  Exactly one request can succeed
for a given token — deterministic under concurrency.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.exceptions import AuthenticationError
from ..core.security import (
    create_refresh_token,
    decode_token,
    hash_refresh_token,
)
from ..models.auth import RefreshToken, User

logger = logging.getLogger(__name__)

settings = get_settings()


class AuthService:
    """Issue, rotate and revoke server-side refresh-token sessions."""

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _expiry(now: datetime) -> datetime:
        return now + timedelta(days=settings.refresh_token_expire_days)

    async def issue_refresh_token(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        now: datetime | None = None,
        family_id: uuid.UUID | None = None,
    ) -> str:
        """Create a new refresh token and persist its hash.

        Does **not** commit — callers own the transaction (login already
        commits the audit entry).  Returns the plaintext token so the
        endpoint can put it into the HttpOnly cookie.
        """
        now = now or self._now()
        token = create_refresh_token(subject=str(user_id))
        record = RefreshToken(
            id=uuid.uuid4(),
            family_id=family_id or uuid.uuid4(),
            user_id=user_id,
            token_hash=hash_refresh_token(token),
            issued_at=now,
            expires_at=self._expiry(now),
        )
        db.add(record)
        return token

    async def rotate_refresh_token(
        self,
        db: AsyncSession,
        refresh_token: str,
        *,
        now: datetime | None = None,
    ) -> tuple[User, str]:
        """Exchange *refresh_token* for a new access/refresh pair.

        Returns ``(user, new_refresh_token)``.  The presented token is
        revoked in the same transaction the new one is issued in.  If the
        presented token is already revoked (or otherwise not the current
        family head), the whole family is revoked and an
        :class:`AuthenticationError` is raised.

        Row-level locking (``FOR UPDATE``) makes concurrent refreshes with
        the same token deterministic: exactly one succeeds.
        """
        now = now or self._now()

        try:
            payload = decode_token(refresh_token)
        except ValueError as exc:
            raise AuthenticationError(str(exc)) from exc
        if payload.get("type") != "refresh":
            raise AuthenticationError("Invalid refresh token")

        try:
            user_id = uuid.UUID(str(payload.get("sub")))
        except (TypeError, ValueError) as exc:
            raise AuthenticationError("Invalid refresh token") from exc

        token_hash = hash_refresh_token(refresh_token)
        result = await db.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .with_for_update()
        )
        record = result.scalar_one_or_none()

        if record is None:
            # No server-side record: legacy token from before the session
            # table existed, or unknown token.  No security-compat mode —
            # force a fresh login.
            raise AuthenticationError(
                "Refresh token is not recognised; please sign in again"
            )

        if record.revoked_at is not None:
            # This token was already rotated (or revoked) — reuse detected.
            await self._revoke_family(db, record.family_id, now=now)
            await db.commit()
            logger.warning(
                "refresh_token_reuse_detected",
                extra={
                    "family_id": str(record.family_id),
                    "user_id": str(record.user_id),
                },
            )
            raise AuthenticationError(
                "Refresh token reuse detected; all sessions were revoked. "
                "Please sign in again."
            )

        if record.expires_at <= now:
            raise AuthenticationError("Refresh token has expired")

        if record.user_id != user_id:
            # JWT subject does not match the DB record — inconsistent token.
            await self._revoke_family(db, record.family_id, now=now)
            await db.commit()
            raise AuthenticationError("Invalid refresh token")

        # Resolve the user; any problem revokes the family (fail closed).
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user is None or not user.is_active or user.is_deleted:
            await self._revoke_family(db, record.family_id, now=now)
            await db.commit()
            raise AuthenticationError("User not found or inactive")

        # Rotate: issue the replacement token in the same family and revoke
        # the presented one.  Single commit keeps the pair atomic and lets
        # the FOR UPDATE lock protect the whole check-then-rotate sequence.
        new_token = await self.issue_refresh_token(
            db, user.id, now=now, family_id=record.family_id
        )
        new_hash = hash_refresh_token(new_token)
        new_record = await self._get_inserted_record(db, new_hash)
        record.revoked_at = now
        record.replaced_by = new_record.id
        await db.commit()

        return user, new_token

    async def revoke_token_family_by_token(
        self,
        db: AsyncSession,
        refresh_token: str,
        *,
        now: datetime | None = None,
    ) -> uuid.UUID | None:
        """Revoke the family of *refresh_token* (used by logout).

        Returns the revoked ``family_id`` or ``None`` when the token is not
        known server-side (the request still succeeds — logout must clear
        the cookie regardless).
        """
        now = now or self._now()
        token_hash = hash_refresh_token(refresh_token)
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        await self._revoke_family(db, record.family_id, now=now)
        await db.commit()
        return record.family_id

    async def revoke_all_user_tokens(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        now: datetime | None = None,
    ) -> int:
        """Revoke every refresh session belonging to *user_id*.

        Used when a password changes or an administrator forces a logout /
        disables an account.  Returns the number of revoked rows.
        """
        now = now or self._now()
        result = await db.execute(
            update(RefreshToken)
            .where(
                (RefreshToken.user_id == user_id)
                & (RefreshToken.revoked_at.is_(None))
            )
            .values(revoked_at=now)
        )
        await db.commit()
        return int(cast(CursorResult, result).rowcount or 0)

    async def _revoke_family(
        self,
        db: AsyncSession,
        family_id: uuid.UUID,
        *,
        now: datetime,
    ) -> None:
        """Mark every row in *family_id* as revoked (unconditional)."""
        await db.execute(
            update(RefreshToken)
            .where(
                (RefreshToken.family_id == family_id)
                & (RefreshToken.revoked_at.is_(None))
            )
            .values(revoked_at=now)
        )

    @staticmethod
    async def _get_inserted_record(
        db: AsyncSession, token_hash: str
    ) -> RefreshToken:
        """Locate the freshly inserted record by its hash.

        The record was queued via ``db.add`` and carries an explicit client
        side id; this lookup is used to link ``replaced_by`` deterministically
        without depending on flush ordering.
        """
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        record = result.scalar_one_or_none()
        if record is None:  # pragma: no cover - defensive
            raise AuthenticationError("Refresh token could not be issued")
        return record


auth_service = AuthService()

__all__ = ["AuthService", "auth_service"]
