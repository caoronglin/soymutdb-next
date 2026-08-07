"""Authentication endpoints: register, login, refresh, change-password, logout, /me.

Refresh sessions
----------------
The refresh token is delivered exclusively through an HttpOnly cookie
(path-scoped to ``/api/v1/auth``) and is never returned in JSON.  Every
refresh rotates the token server-side (SHA-256 hashes in ``refresh_tokens``);
reuse of a rotated token revokes the whole session family.  ``refresh`` and
``logout`` additionally verify the request Origin/Referer (CSRF defence).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...core.csrf import validate_request_origin
from ...core.database import get_db
from ...core.exceptions import AuthenticationError, ConflictError, RateLimitExceededError
from ...core.ratelimit import login_rate_limiter
from ...core.security import (
    RoleName,
    create_access_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from ...models.auth import AuditLog, Role, User
from ...schemas.auth import (
    LoginRequest,
    PasswordChangeRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
)
from ...services.auth_service import auth_service
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/auth", tags=["auth"])

settings = get_settings()


# ---------------------------------------------------------------------------
# Refresh-token cookie helpers
# ---------------------------------------------------------------------------


def _samesite() -> Literal["lax", "strict", "none"]:
    return cast(Literal["lax", "strict", "none"], settings.refresh_cookie_samesite)


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Store the refresh token in an HttpOnly, path-scoped cookie."""
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        httponly=True,
        secure=settings.refresh_cookie_secure_effective,
        samesite=_samesite(),
        path=settings.refresh_cookie_path,
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Expire the refresh cookie on the client."""
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=settings.refresh_cookie_secure_effective,
        samesite=_samesite(),
        path=settings.refresh_cookie_path,
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Register a new user account (Argon2id password hashing).

    Password strength is validated both client-side and server-side.
    """
    # Server-side password strength validation.
    valid, reason = validate_password_strength(payload.password)
    if not valid:
        raise ConflictError(reason)

    # Check for existing email / username.
    existing = await db.execute(
        select(User).where(
            (User.email == payload.email) | (User.username == payload.username)
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("A user with this email or username already exists")

    # Resolve role (default viewer).
    role_result = await db.execute(
        select(Role).where(Role.name == payload.role_name)
    )
    role = role_result.scalar_one_or_none()
    if role is None:
        # Fallback to viewer role.
        role_result = await db.execute(select(Role).where(Role.name == RoleName.VIEWER.value))
        role = role_result.scalar_one_or_none()

    user = User(
        id=uuid.uuid4(),
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role_id=role.id if role else None,
        is_active=True,
        joined_at=datetime.now(UTC),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return _user_to_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate and return an access token (refresh token via cookie).

    Login attempts are limited through the shared Redis-backed fixed-window
    limiter before credential verification. This keeps the limit consistent
    across workers and instances without changing the authentication flow.

    The refresh token is set as an HttpOnly cookie scoped to ``/api/v1/auth``
    and is **not** included in the JSON response body.
    """
    client_ip = request.client.host if request.client else None
    await login_rate_limiter.enforce(username=payload.username, client_ip=client_ip)

    # Look up user by email OR username.
    result = await db.execute(
        select(User).where(
            (User.email == payload.username) | (User.username == payload.username)
        )
    )
    user = result.scalar_one_or_none()

    # Check account lock.
    if user is not None and user.locked_until is not None:
        if user.locked_until > datetime.now(UTC):
            retry_after = max(
                1,
                int((user.locked_until - datetime.now(UTC)).total_seconds()),
            )
            raise RateLimitExceededError(
                "Account is temporarily locked due to too many failed login attempts. "
                f"Try again after {user.locked_until.isoformat()}",
                retry_after=retry_after,
            )
        # Lock expired — clear it.
        user.locked_until = None

    # Validate credentials.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AuthenticationError("Invalid email or password")

    if not user.is_active:
        raise AuthenticationError("Account is inactive")

    # Successful login — clear any expired legacy database lock.
    if user.locked_until is not None:
        user.locked_until = None

    # Update last_login_at.
    now = datetime.now(UTC)
    user.last_login_at = now

    # Record audit log entry for login.
    db.add(
        AuditLog(
            user_id=user.id,
            action="login",
            resource_type="auth",
            resource_id=str(user.id),
            new_value={"username": user.username, "login_at": now.isoformat()},
            ip_address=client_ip,
        )
    )
    await db.commit()

    roles = get_user_roles(user)
    extra = {"roles": roles}
    access_token = create_access_token(subject=str(user.id), extra=extra)
    refresh_token = await auth_service.issue_refresh_token(db, user.id)

    _set_refresh_cookie(response, refresh_token)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Rotate the refresh cookie into a new access/refresh pair.

    The presented refresh token is read **only** from the HttpOnly cookie
    (path-scoped to ``/api/v1/auth``).  Rotation is server-side: the old
    token is revoked and a replacement is issued in the same family.  A
    previously rotated token presented again triggers reuse detection and
    revokes the whole family.  Requests without a trusted Origin/Referer
    are rejected (CSRF defence).
    """
    validate_request_origin(request, settings)

    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not refresh_token:
        raise AuthenticationError("Missing refresh token cookie")

    user, new_refresh_token = await auth_service.rotate_refresh_token(
        db, refresh_token
    )

    roles = get_user_roles(user)
    access_token = create_access_token(subject=str(user.id), extra={"roles": roles})
    _set_refresh_cookie(response, new_refresh_token)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Logout: revoke the current refresh family and clear the cookie.

    Requires a valid Bearer access token.  The refresh cookie (if present)
    identifies the family to revoke; the response also expires the cookie on
    the client.  Requests without a trusted Origin/Referer are rejected
    (CSRF defence).
    """
    validate_request_origin(request, settings)

    client_ip = request.client.host if request.client else None
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if refresh_token:
        await auth_service.revoke_token_family_by_token(db, refresh_token)

    # Record audit log entry for logout.
    db.add(
        AuditLog(
            user_id=current_user.id,
            action="logout",
            resource_type="auth",
            resource_id=str(current_user.id),
            new_value={"logout_at": datetime.now(UTC).isoformat()},
            ip_address=client_ip,
        )
    )
    await db.commit()

    _clear_refresh_cookie(response)
    return None


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the currently authenticated user's profile.

    Uses proper dependency injection via ``Depends(get_current_user)``.
    """
    return _user_to_response(current_user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Change the current user's password.

    .. note::
        **Admin password policy** — Administrator account passwords are set
        **only** via the initial configuration (``SOYMUTDB_ADMIN_PASSWORD``
        environment variable) or the ``create_admin.py`` CLI script.
        There is **no** "forgot password" reset flow for administrator accounts.

        Non-admin users can freely change their own password through this
        endpoint. Administrators may also use it, but if they lock themselves
        out the password must be reset by a system administrator using the
        CLI script.

    Server-side password strength validation is applied to the new password.
    """
    # Validate new password strength.
    valid, reason = validate_password_strength(payload.new_password)
    if not valid:
        raise ConflictError(reason)
    if not verify_password(payload.current_password, current_user.password_hash):
        raise AuthenticationError("Current password is incorrect")
    current_user.password_hash = hash_password(payload.new_password)

    # Record audit log entry for password change.
    client_ip = request.client.host if request.client else None
    db.add(
        AuditLog(
            user_id=current_user.id,
            action="password_change",
            resource_type="auth",
            resource_id=str(current_user.id),
            ip_address=client_ip,
        )
    )
    await db.commit()

    # Invalidate every refresh session — after a password change all
    # previously issued tokens must stop working.
    await auth_service.revoke_all_user_tokens(db, current_user.id)


def _user_to_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        role_name=user.role_rel.name if user.role_rel else None,
        organization_id=user.organization_id,
        joined_at=user.joined_at,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )
