"""Comparative-genomics relations: families, membership and derived artifacts.

The vocabulary is deliberately narrow, because each field here is a claim a
researcher will read as a fact:

* a family states *how* it was built (``method``, ``source_*``) — an unnamed
  grouping is not a family, it is a guess;
* membership states the relationship type (one-to-one / one-to-many /
  many-to-many) per row, and which species the member belongs to;
* an alignment or tree states its frozen input hash, so a finished artifact can
  be shown next to the exact member set it was computed from.

Absence is represented as absence. A species with no row in
``gene_family_members`` has no data for that family; the API says so instead of
serving an empty list that reads as "present, empty".
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class FamilyLevel(enum.StrEnum):
    FAMILY = "gene_family"
    SUBFAMILY = "gene_subfamily"


class RelationshipType(enum.StrEnum):
    """How members of one family relate to each other.

    The distinction is scientific, not cosmetic: one-to-one means a defensible
    ortholog pair, one-to-many means a lineage-specific expansion, and
    many-to-many means the source could not resolve a pairing. Collapsing them
    into "related" would let the portal imply a precision the source lacks.
    """

    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_MANY = "many_to_many"


class ArtifactType(enum.StrEnum):
    MSA = "msa"
    TREE = "tree"


class ComparativeArtifactState(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GeneFamily(Base):
    """A release/assembly-scoped protein family or subfamily."""

    __tablename__ = "gene_families"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assembly_id", "release_id"],
            ["assemblies.id", "assemblies.release_id"],
            name="fk_gene_families_assembly_release",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "assembly_id",
            "release_id",
            "level",
            "external_id",
            name="uq_gene_families_scope",
        ),
        CheckConstraint(
            "level IN ('gene_family', 'gene_subfamily')",
            name="ck_gene_families_level",
        ),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gene_families_sha256",
        ),
        Index("ix_gene_families_scope", "release_id", "assembly_id", "level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assembly_id: Mapped[int] = mapped_column(Integer, nullable=False)
    release_id: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[str] = mapped_column(
        String(16),
        default=FamilyLevel.FAMILY.value,
        server_default="gene_family",
        nullable=False,
    )
    #: Identifier in the source resource (``PF00001``, ``OG0001234``...).
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    #: How the family was produced. Never defaulted: a family without a stated
    #: method cannot be stored, because the portal would have to invent one.
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    method_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)
    source_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    members: Mapped[list[GeneFamilyMember]] = relationship(
        back_populates="family", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<GeneFamily id={self.id} external_id={self.external_id!r} method={self.method!r}>"


class GeneFamilyMember(Base):
    """One member of a family, with the relationship it was placed under."""

    __tablename__ = "gene_family_members"
    __table_args__ = (
        UniqueConstraint("family_id", "gene_accession", name="uq_gene_family_members_member"),
        CheckConstraint(
            "relationship_type IN ('one_to_one', 'one_to_many', 'many_to_many')",
            name="ck_gene_family_members_relationship_type",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_gene_family_members_confidence",
        ),
        Index("ix_gene_family_members_scope", "release_id", "assembly_id", "gene_accession"),
        Index("ix_gene_family_members_species", "family_id", "species"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    family_id: Mapped[int] = mapped_column(
        ForeignKey("gene_families.id", ondelete="CASCADE"), nullable=False
    )
    assembly_id: Mapped[int] = mapped_column(Integer, nullable=False)
    release_id: Mapped[int] = mapped_column(Integer, nullable=False)
    gene_accession: Mapped[str] = mapped_column(String(64), nullable=False)
    species: Mapped[str] = mapped_column(String(128), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(16), nullable=False)
    method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Free-form source evidence (e-value, bitscore, HMM hit...). Kept verbatim
    #: so a client shows what the source said, not a re-derivation.
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ``raise_on_sql`` rather than ``noload``: a member is always read through
    # the family (``_members`` selects the rows themselves), so an accidental
    # lazy access is a bug, and SQLAlchemy 2.1 deprecates ``noload`` for
    # returning ``None`` instead of raising.
    family: Mapped[GeneFamily] = relationship(
        back_populates="members", lazy="raise_on_sql"
    )

    def __repr__(self) -> str:
        return (
            f"<GeneFamilyMember family={self.family_id} gene={self.gene_accession!r} "
            f"type={self.relationship_type!r}>"
        )


class ComparativeArtifact(Base):
    """An asynchronously produced alignment or tree, bound to its input."""

    __tablename__ = "comparative_artifacts"
    __table_args__ = (
        CheckConstraint(
            "artifact_type IN ('msa', 'tree')",
            name="ck_comparative_artifacts_type",
        ),
        CheckConstraint(
            "state IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_comparative_artifacts_state",
        ),
        CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_comparative_artifacts_input_sha256",
        ),
        CheckConstraint(
            "object_sha256 IS NULL OR object_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_comparative_artifacts_object_sha256",
        ),
        CheckConstraint(
            "state <> 'succeeded' OR object_key IS NOT NULL",
            name="ck_comparative_artifacts_succeeded_has_object",
        ),
        Index("ix_comparative_artifacts_scope", "release_id", "assembly_id"),
        Index("ix_comparative_artifacts_family", "family_id", "artifact_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    #: The outbox/analysis job that produces this artifact. Unique: one job,
    #: one artifact -- a re-delivered message must not fan out.
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), unique=True, nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(16), nullable=False)
    family_id: Mapped[int | None] = mapped_column(
        ForeignKey("gene_families.id", ondelete="CASCADE"), nullable=True
    )
    assembly_id: Mapped[int] = mapped_column(Integer, nullable=False)
    release_id: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Hash over the exact ordered member set the artifact was computed from.
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_member_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    state: Mapped[str] = mapped_column(
        String(20),
        default=ComparativeArtifactState.PENDING.value,
        server_default="pending",
        nullable=False,
    )
    object_key: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    object_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ComparativeArtifact id={self.id} type={self.artifact_type!r} state={self.state!r}>"
        )


__all__ = [
    "ArtifactType",
    "ComparativeArtifact",
    "ComparativeArtifactState",
    "FamilyLevel",
    "GeneFamily",
    "GeneFamilyMember",
    "RelationshipType",
]
