"""Comparative-genomics relations: groups, members and artifact jobs.

Adds the three things a comparative-genomics read needs and nothing else:

* ``gene_families`` — a release/assembly-scoped family or subfamily with its
  method and provenance. A family is a claim about grouping, so it must state
  how it was produced; unnamed grouping is exactly what the platform refuses.
* ``gene_family_members`` — membership rows, with ``relationship_type``
  distinguishing one-to-one / one-to-many / many-to-many. A membership row is
  also how "this species has no member" is represented: it is *absent*, not an
  empty list pretending to be an answer.
* ``comparative_artifacts`` — asynchronous multiple-sequence alignment and
  phylogenetic-tree artifacts, stored as objects and described by a row that
  records the frozen input, the method and the provenance.

Downgrade drops all three tables; nothing else references them yet.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

_RELATIONSHIP_TYPES = ("one_to_one", "one_to_many", "many_to_many")


def upgrade() -> None:
    op.create_table(
        "gene_families",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("assembly_id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        #: ``gene_family`` or ``gene_subfamily``.
        sa.Column("level", sa.String(16), server_default="gene_family", nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("method_version", sa.String(64), nullable=True),
        sa.Column("source_name", sa.String(256), nullable=False),
        sa.Column("source_version", sa.String(128), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assembly_id", "release_id"],
            ["assemblies.id", "assemblies.release_id"],
            name="fk_gene_families_assembly_release",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "assembly_id", "release_id", "level", "external_id",
            name="uq_gene_families_scope",
        ),
        sa.CheckConstraint(
            "level IN ('gene_family', 'gene_subfamily')",
            name="ck_gene_families_level",
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gene_families_sha256",
        ),
        sa.Index("ix_gene_families_scope", "release_id", "assembly_id", "level"),
    )

    op.create_table(
        "gene_family_members",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("assembly_id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("gene_accession", sa.String(64), nullable=False),
        sa.Column("species", sa.String(128), nullable=False),
        #: ``relationship_type`` is per row: one family can connect its members
        #: one-to-one in one subfamily and many-to-many in another.
        sa.Column("relationship_type", sa.String(16), nullable=False),
        #: How this membership was established, and how strongly the source
        #: trusted it. Both nullable: an unresolved value stays absent.
        sa.Column("method", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["family_id"], ["gene_families.id"],
            name="fk_gene_family_members_family", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "family_id", "gene_accession",
            name="uq_gene_family_members_member",
        ),
        sa.CheckConstraint(
            "relationship_type IN ('one_to_one', 'one_to_many', 'many_to_many')",
            name="ck_gene_family_members_relationship_type",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_gene_family_members_confidence",
        ),
        sa.Index("ix_gene_family_members_scope", "release_id", "assembly_id", "gene_accession"),
        sa.Index("ix_gene_family_members_species", "family_id", "species"),
    )

    op.create_table(
        "comparative_artifacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("artifact_type", sa.String(16), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=True),
        sa.Column("assembly_id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column(
            "input_member_ids", postgresql.JSONB(), nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "state", sa.String(20), server_default="pending", nullable=False,
        ),
        sa.Column("object_key", sa.String(2048), nullable=True),
        sa.Column("object_sha256", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["family_id"], ["gene_families.id"],
            name="fk_comparative_artifacts_family", ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "artifact_type IN ('msa', 'tree')",
            name="ck_comparative_artifacts_type",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_comparative_artifacts_state",
        ),
        sa.CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_comparative_artifacts_input_sha256",
        ),
        sa.CheckConstraint(
            "object_sha256 IS NULL OR object_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_comparative_artifacts_object_sha256",
        ),
        sa.CheckConstraint(
            "state <> 'succeeded' OR object_key IS NOT NULL",
            name="ck_comparative_artifacts_succeeded_has_object",
        ),
        sa.Index("ix_comparative_artifacts_scope", "release_id", "assembly_id"),
        sa.Index("ix_comparative_artifacts_family", "family_id", "artifact_type"),
    )


def downgrade() -> None:
    op.drop_index("ix_comparative_artifacts_family", table_name="comparative_artifacts")
    op.drop_index("ix_comparative_artifacts_scope", table_name="comparative_artifacts")
    op.drop_table("comparative_artifacts")
    op.drop_index("ix_gene_family_members_species", table_name="gene_family_members")
    op.drop_index("ix_gene_family_members_scope", table_name="gene_family_members")
    op.drop_table("gene_family_members")
    op.drop_index("ix_gene_families_scope", table_name="gene_families")
    op.drop_table("gene_families")
