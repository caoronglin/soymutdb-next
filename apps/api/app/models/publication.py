"""Immutable multi-target static publication models (Phase 3).

Models the lifecycle of publishing one immutable static artifact to a
configured target:

- ``PublicationTarget``: where an artifact can be published (local,
  github_pages, cloudflare_pages).  Only the target *identifier* is stored;
  credentials live in environment/secret config and are never persisted.
- ``StaticPublication``: a single build+publish request with a monotonic,
  target-scoped ``publication_id``, a state machine, an evidence manifest
  digest, and a rollback relation (``previous_publication_id``).

Concurrency contract (see services/publication_service.py):
  - ``publication_id`` is monotonically increasing and unique per target
    (``(target, publication_id)`` unique).  A later request always wins.
  - A target-scoped lease row guards allocation/final promotion only, never
    network I/O inside the same transaction.
  - ``superseded`` is a terminal state marking a stale job that must not
    promote over a newer request.
"""

from __future__ import annotations

from sqlalchemy import Enum as SAEnum
from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..core.compat import StrEnum
from .base import Base, TimestampMixin, enum_values


class PublicationTarget(StrEnum):
    """Where a static artifact is published."""

    LOCAL = "local"
    GITHUB_PAGES = "github_pages"
    CLOUDFLARE_PAGES = "cloudflare_pages"


class PublicationStatus(StrEnum):
    """State machine for a static publication request."""

    REQUESTED = "requested"
    BUILDING = "building"
    VALIDATING = "validating"
    DEPLOYING = "deploying"
    PUBLISHED = "published"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    SUPERSEDED = "superseded"


#: Terminal states after which no further transition is allowed.
_TERMINAL = {
    PublicationStatus.FAILED,
    PublicationStatus.ROLLED_BACK,
    PublicationStatus.SUPERSEDED,
    PublicationStatus.PUBLISHED,
}


#: Allowed forward transitions (``current -> {allowed next}``).
_TRANSITIONS: dict[PublicationStatus, set[PublicationStatus]] = {
    PublicationStatus.REQUESTED: {PublicationStatus.BUILDING, PublicationStatus.FAILED},
    PublicationStatus.BUILDING: {PublicationStatus.VALIDATING, PublicationStatus.FAILED},
    PublicationStatus.VALIDATING: {PublicationStatus.DEPLOYING, PublicationStatus.FAILED},
    PublicationStatus.DEPLOYING: {
        PublicationStatus.PUBLISHED,
        PublicationStatus.FAILED,
        PublicationStatus.SUPERSEDED,
    },
    PublicationStatus.PUBLISHED: {PublicationStatus.ROLLED_BACK},
    # Terminal states allow no forward transition.
    PublicationStatus.FAILED: set(),
    PublicationStatus.ROLLED_BACK: set(),
    PublicationStatus.SUPERSEDED: set(),
}


def transition_allowed(current: PublicationStatus, target: PublicationStatus) -> bool:
    """Return True if ``current -> target`` is an allowed transition."""
    return target in _TRANSITIONS.get(current, set())


def is_terminal(status: PublicationStatus) -> bool:
    return status in _TERMINAL


class StaticPublication(Base, TimestampMixin):
    __tablename__ = "static_publications"
    __table_args__ = (
        UniqueConstraint(
            "target", "publication_id",
            name="uq_static_publications_target_publication_id",
        ),
        Index("ix_static_publications_target_status", "target", "status"),
        Index("ix_static_publications_release_id", "release_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: Monotonic, target-scoped sequence number (allocation-only counter).
    publication_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target: Mapped[str] = mapped_column(
        SAEnum(
            PublicationTarget,
            name="publication_target_enum",
            values_callable=enum_values,
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        SAEnum(
            PublicationStatus,
            name="publication_status_enum",
            values_callable=enum_values,
        ),
        nullable=False,
        server_default=PublicationStatus.REQUESTED.value,
    )
    release_id: Mapped[int] = mapped_column(
        ForeignKey("releases.id", ondelete="RESTRICT"), nullable=False
    )
    page_definition_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: SHA-256 of the canonicalized manifest.json (``release_service.manifest_digest``).
    manifest_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Immutable location of the *built* artifact (S3 object key or local path).
    artifact_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Immutable reference of the *input* the build was produced from (the SSG
    #: output tree/archive). Nullable: a request without one is allowed and the
    #: worker then fails closed rather than publishing a synthetic page.
    build_artifact_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Remote deployment identifier recorded by the target (run id / commit / deploy id).
    remote_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Previous published publication on the same target (rollback relation).
    previous_publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("static_publications.id", ondelete="SET NULL"), nullable=True
    )
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    superseded_by_publication_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<StaticPublication id={self.id} target={self.target!r} "
            f"publication_id={self.publication_id} status={self.status}>"
        )


# ---------------------------------------------------------------------------
# Target-scoped counters and lease
# ---------------------------------------------------------------------------


class PublicationCounter(Base):
    """Per-target monotonic counter backing ``publication_id`` allocation.

    A dedicated table (rather than ``max(publication_id)``) makes allocation
    race-free: increment the row under row lock, read the new value.
    """

    __tablename__ = "publication_counters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target: Mapped[str] = mapped_column(
        SAEnum(
            PublicationTarget,
            name="publication_target_enum",
            values_callable=enum_values,
        ),
        nullable=False,
        unique=True,
    )
    last_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PublicationTargetLease(Base):
    """Target-scoped advisory lease row (allocation/final-promotion only).

    The workflow acquires this row with ``SELECT ... FOR UPDATE`` for the
    short critical section of allocating a new ``publication_id`` or of
    comparing the current job against the target's latest request before
    promotion; it must never be held across network I/O.
    """

    __tablename__ = "publication_target_leases"

    target: Mapped[str] = mapped_column(
        SAEnum(
            PublicationTarget,
            name="publication_target_enum",
            values_callable=enum_values,
        ),
        nullable=False,
        primary_key=True,
    )
    latest_publication_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


__all__ = [
    "PublicationCounter",
    "PublicationStatus",
    "PublicationTarget",
    "PublicationTargetLease",
    "StaticPublication",
    "is_terminal",
    "transition_allowed",
]
