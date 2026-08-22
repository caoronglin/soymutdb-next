"""Pydantic v2 schemas for authentication, users, roles, and organizations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


def _validate_password_complexity(v: str) -> str:
    """Enforce password complexity: 8+ chars, at least 3 of 4 char types.

    Character types: uppercase, lowercase, digits, special.
    Meets national information security level 3 protection standards.
    """
    types_present = sum(
        [
            any(c.isupper() for c in v),
            any(c.islower() for c in v),
            any(c.isdigit() for c in v),
            any(not c.isalnum() for c in v),
        ]
    )
    if types_present < 3:
        raise ValueError(
            "Password must contain at least 3 of: uppercase letters, "
            "lowercase letters, digits, and special characters"
        )
    return v


class UserCreate(BaseModel):
    """Payload for creating a new user account."""

    username: str = Field(
        ..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_]+$"
    )
    email: EmailStr = Field(..., examples=["researcher@univ.edu"])
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plain-text password (will be hashed with Argon2id).",
        examples=["S3cureP@ss!"],
    )
    full_name: str = Field(..., min_length=1, max_length=255, examples=["Jane Doe"])
    organization_id: int | None = Field(default=None)
    role_name: Literal["viewer"] = Field(
        default="viewer",
        examples=["viewer"],
        description="Public registration always creates a viewer account.",
    )

    @field_validator("password")
    @classmethod
    def _password_complexity(cls, v: str) -> str:
        return _validate_password_complexity(v)


class UserUpdate(BaseModel):
    """Payload for partially updating a user account."""

    email: EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_active: bool | None = None
    role_name: str | None = None
    organization_id: int | None = None


class UserResponse(BaseModel):
    """Public representation of a user."""

    id: str
    username: str
    email: str
    full_name: str | None
    is_active: bool
    is_superuser: bool
    role_name: str | None = None
    organization_id: int | None = None
    joined_at: datetime
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    """Cursor-paginated list of users."""

    items: list[UserResponse] = Field(default_factory=list)
    next_cursor: str | None = Field(default=None)
    has_more: bool = Field(default=False)


class LoginRequest(BaseModel):
    """Credentials for logging in — accepts email or username.

    Both ``username`` and ``email`` keys are accepted; ``email`` is treated
    as an alias for ``username`` so API clients may send either field.
    """

    username: str | None = Field(
        default=None,
        description="Email address or username",
        examples=["researcher@univ.edu"],
    )
    email: str | None = Field(
        default=None,
        description="Email address (alternative to ``username``)",
        examples=["researcher@univ.edu"],
    )
    password: str = Field(..., examples=["S3cureP@ss!"])

    @model_validator(mode="after")
    def _resolve_username(self) -> LoginRequest:
        if not self.username and self.email:
            self.username = self.email
        if not self.username:
            raise ValueError("username or email is required")
        return self


class TokenResponse(BaseModel):
    """Token pair returned after successful authentication.

    Only the access token is returned in JSON.  The refresh token is
    delivered exclusively through the HttpOnly refresh cookie and never
    appears in any response body.
    """

    access_token: str
    token_type: str = Field(default="bearer")
    expires_in: int = Field(..., description="Access token lifetime in seconds.")


class RefreshTokenRequest(BaseModel):
    """Payload for rotating a refresh token (``POST /auth/refresh``)."""

    refresh_token: str = Field(..., min_length=1, description="Refresh token to exchange.")


class PasswordChangeRequest(BaseModel):
    """Payload for changing the current user's password."""

    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _password_complexity(cls, v: str) -> str:
        return _validate_password_complexity(v)


class TokenPayload(BaseModel):
    """Decoded JWT payload."""

    sub: str
    exp: datetime
    iat: datetime
    roles: list[str] = Field(default_factory=list)
    token_type: str = Field(default="access")


class RoleResponse(BaseModel):
    """Public representation of a role."""

    id: int
    name: str
    description: str | None = None
    permissions: dict[str, Any] | list[str] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrganizationResponse(BaseModel):
    """Public representation of an organization."""

    id: int
    name: str
    description: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
