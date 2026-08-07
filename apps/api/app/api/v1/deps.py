"""FastAPI dependency-injection helpers.

Fix vs. reference: the ``/me`` endpoint uses a proper ``Depends(get_current_user)``
callable, NOT ``Depends(lambda: ...)``.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

from fastapi import Depends, Header, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthenticationError, AuthorizationError
from ...core.security import RoleName, decode_token, has_role
from ...models.auth import Role, User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    """Resolve the current authenticated user from the Bearer token.

    Raises :class:`AuthenticationError` if the token is missing, invalid, or
    the user does not exist / is inactive.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Missing or invalid Authorization header")

    token = credentials.credentials
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise AuthenticationError(str(exc)) from exc

    if payload.get("type") != "access":
        raise AuthenticationError("Invalid token type")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise AuthenticationError("Token missing subject")

    try:
        user_uuid = uuid.UUID(str(user_id_str))
    except ValueError as exc:
        raise AuthenticationError("Invalid subject in token") from exc

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if user is None:
        raise AuthenticationError("User not found")
    if not user.is_active:
        raise AuthenticationError("User account is inactive")
    if user.is_deleted:
        raise AuthenticationError("User account has been deleted")

    return user


def get_user_roles(user: User) -> list[str]:
    """Return the list of role names assigned to *user*."""
    roles: list[str] = []
    if user.role_rel is not None:
        roles.append(user.role_rel.name)
    if user.is_superuser:
        roles.append(RoleName.ADMINISTRATOR.value)
    return roles


def require_role(required_role: RoleName):
    """Return a dependency that enforces the given RBAC role (hierarchical).

    Usage::

        @router.post("/admin", dependencies=[Depends(require_role(RoleName.ADMINISTRATOR))])
        async def admin_only(): ...
    """

    async def _checker(current_user: User = Depends(get_current_user)) -> User:
        user_roles = get_user_roles(current_user)
        if not has_role(user_roles, required_role):
            raise AuthorizationError(
                f"Requires role '{required_role.value}' or higher"
            )
        return current_user

    return _checker


async def get_optional_user(
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User | None:
    """Like :func:`get_current_user` but returns ``None`` if no token is present."""
    if credentials is None:
        return None
    return await get_current_user(db=db, credentials=credentials)
