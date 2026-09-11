"""Authentication, authorisation, organisation and audit models.

Fix vs. reference: ``last_login_at``, ``locked_until``, ``assigned_at`` and
``joined_at`` are now proper ``DateTime`` columns (the reference used UUID by
mistake).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from .content import NewsArticle


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    permissions: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=dict
    )

    users: Mapped[list[User]] = relationship(
        back_populates="role_rel", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Role id={self.id} name={self.name!r}>"


# ---------------------------------------------------------------------------
# Organisation
# ---------------------------------------------------------------------------


class Organization(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    users: Mapped[list[User]] = relationship(
        back_populates="organization_rel", lazy="selectin"
    )
    projects: Mapped[list[Project]] = relationship(
        back_populates="organization", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Organization id={self.id} name={self.name!r}>"


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class User(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    username: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    role_id: Mapped[int | None] = mapped_column(
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    locale: Mapped[str] = mapped_column(
        String(10), default="en", server_default="en", nullable=False
    )
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Security / audit timestamps (DateTime, NOT UUID).
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    role_rel: Mapped[Role | None] = relationship(
        back_populates="users", lazy="joined"
    )
    organization_rel: Mapped[Organization | None] = relationship(
        back_populates="users", lazy="joined"
    )
    project_memberships: Mapped[list[ProjectMember]] = relationship(
        back_populates="user", lazy="selectin"
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(
        back_populates="user", lazy="noload"
    )
    articles: Mapped[list[NewsArticle]] = relationship(
        back_populates="author",
        foreign_keys="NewsArticle.author_id",
        lazy="noload",
    )

    __table_args__ = (
        Index("ix_users_org_active", "organization_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"


# ---------------------------------------------------------------------------
# RefreshToken
# ---------------------------------------------------------------------------


class RefreshToken(Base):
    """Server-side record for an issued refresh token.

    Only the SHA-256 hash of the token string is stored (``token_hash``),
    never the plaintext.  Rows form *families*: every successful rotation
    revokes the presented row (``revoked_at``) and inserts a new one in the
    same family linked via ``replaced_by``.  Presenting a token whose row is
    already revoked signals token theft and revokes the whole family.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<RefreshToken id={self.id} family={self.family_id} "
            f"user={self.user_id} revoked={self.revoked_at is not None}>"
        )


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


class Project(Base, TimestampMixin, SoftDeleteMixin, AuditMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    organization: Mapped[Organization | None] = relationship(
        back_populates="projects", lazy="joined"
    )
    members: Mapped[list[ProjectMember]] = relationship(
        back_populates="project",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("name", "organization_id", name="uq_project_name_org"),
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} name={self.name!r}>"


# ---------------------------------------------------------------------------
# ProjectMember
# ---------------------------------------------------------------------------


class ProjectMember(Base, TimestampMixin):
    __tablename__ = "project_members"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(
        String(32), default="viewer", server_default="viewer", nullable=False
    )

    project: Mapped[Project] = relationship(
        back_populates="members", lazy="joined"
    )
    user: Mapped[User] = relationship(
        back_populates="project_memberships", lazy="joined"
    )

    def __repr__(self) -> str:
        return f"<ProjectMember project={self.project_id} user={self.user_id} role={self.role!r}>"


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    user: Mapped[User | None] = relationship(
        back_populates="audit_logs", lazy="joined"
    )

    __table_args__ = (
        Index("ix_audit_resource", "resource_type", "resource_id"),
        Index("ix_audit_user_ts", "user_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action!r}>"


__all__ = [
    "AuditLog",
    "Organization",
    "Project",
    "ProjectMember",
    "RefreshToken",
    "Role",
    "User",
]
