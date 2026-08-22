"""Initial schema — all tables, indexes, constraints, and enums.

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00

Fix vs. reference: uses ``password_hash`` (not ``hashed_password``) to match
the canonical column name expected by tests and the API contract.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create initial database schema."""
    # ── Extensions ────────────────────────────────────────────────────────
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ── Enums ─────────────────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE visibility_enum AS ENUM "
        "('public', 'organization', 'project', 'private')"
    )
    op.execute(
        "CREATE TYPE variant_type_enum AS ENUM ('SNP', 'INS', 'DEL', 'MNV', 'SV')"
    )
    op.execute(
        "CREATE TYPE impact_enum AS ENUM ('HIGH', 'MODERATE', 'LOW', 'MODIFIER')"
    )

    # ── Organizations ─────────────────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
    )
    op.create_index("ix_organizations_name", "organizations", ["name"], unique=True)

    # ── Roles ─────────────────────────────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("permissions", postgresql.JSONB(astext_type=sa.Text()), server_default="'{}'::jsonb", nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
    )
    op.create_index("ix_roles_name", "roles", ["name"], unique=True)

    # ── Users ─────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("full_name", sa.String(length=256), nullable=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("role_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_superuser", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("locale", sa.String(length=10), server_default="'en'", nullable=False),
        sa.Column("avatar_url", sa.String(length=1024), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name=op.f("fk_users_organization_id_organizations"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name=op.f("fk_users_role_id_roles"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_organization_id", "users", ["organization_id"])
    op.create_index("ix_users_org_active", "users", ["organization_id", "is_active"])

    # ── Projects ──────────────────────────────────────────────────────────
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_public", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name=op.f("fk_projects_organization_id_organizations"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("name", "organization_id", name="uq_project_name_org"),
    )

    # ── Project Members ───────────────────────────────────────────────────
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="viewer", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_project_members_project_id_projects"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_project_members_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "user_id", name=op.f("pk_project_members")),
    )

    # ── Releases ──────────────────────────────────────────────────────────
    op.create_table(
        "releases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("is_public", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_releases")),
    )
    op.create_index("ix_releases_name", "releases", ["name"], unique=True)

    # ── Assemblies ────────────────────────────────────────────────────────
    op.create_table(
        "assemblies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("species", sa.String(length=128), server_default="Glycine max", nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("fasta_url", sa.String(length=1024), nullable=True),
        sa.Column("fai_url", sa.String(length=1024), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"], name=op.f("fk_assemblies_release_id_releases"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assemblies")),
    )
    op.create_index("ix_assemblies_name", "assemblies", ["name"], unique=True)

    # ── Chromosomes ───────────────────────────────────────────────────────
    op.create_table(
        "chromosomes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("assembly_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("length", sa.BigInteger(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["assembly_id"], ["assemblies.id"], name=op.f("fk_chromosomes_assembly_id_assemblies"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chromosomes")),
        sa.UniqueConstraint("assembly_id", "name", name="uq_chromosome_assembly_name"),
    )
    op.create_index("ix_chromosome_assembly_order", "chromosomes", ["assembly_id", "order"])

    # ── Genes ─────────────────────────────────────────────────────────────
    op.create_table(
        "genes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("assembly_id", sa.Integer(), nullable=False),
        sa.Column("chromosome_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column("biotype", sa.String(length=64), server_default="protein_coding", nullable=False),
        sa.Column("start", sa.BigInteger(), nullable=False),
        sa.Column("end", sa.BigInteger(), nullable=False),
        sa.Column("strand", sa.String(length=1), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assembly_id"], ["assemblies.id"], name=op.f("fk_genes_assembly_id_assemblies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chromosome_id"], ["chromosomes.id"], name=op.f("fk_genes_chromosome_id_chromosomes"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_genes")),
        sa.CheckConstraint("start > 0", name=op.f("ck_gene_start_positive")),
        sa.CheckConstraint("end >= start", name=op.f("ck_gene_end_after_start")),
    )
    op.create_index("ix_gene_assembly_chr", "genes", ["assembly_id", "chromosome_id"])
    op.create_index("ix_gene_location", "genes", ["chromosome_id", "start", "end"])
    op.create_index("ix_gene_name", "genes", ["name"])
    op.create_index("ix_gene_biotype", "genes", ["biotype"])

    # ── Transcripts ───────────────────────────────────────────────────────
    op.create_table(
        "transcripts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("gene_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column("biotype", sa.String(length=64), server_default="mRNA", nullable=False),
        sa.Column("start", sa.BigInteger(), nullable=False),
        sa.Column("end", sa.BigInteger(), nullable=False),
        sa.Column("strand", sa.String(length=1), nullable=False),
        sa.Column("is_canonical", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["gene_id"], ["genes.id"], name=op.f("fk_transcripts_gene_id_genes"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transcripts")),
    )
    op.create_index("ix_transcript_gene", "transcripts", ["gene_id"])

    # ── Exons ─────────────────────────────────────────────────────────────
    op.create_table(
        "exons",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("transcript_id", sa.String(length=64), nullable=False),
        sa.Column("start", sa.BigInteger(), nullable=False),
        sa.Column("end", sa.BigInteger(), nullable=False),
        sa.Column("order", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"], name=op.f("fk_exons_transcript_id_transcripts"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exons")),
    )
    op.create_index("ix_exon_transcript_order", "exons", ["transcript_id", "order"])

    # ── Gene Aliases ──────────────────────────────────────────────────────
    op.create_table(
        "gene_aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gene_id", sa.String(length=64), nullable=False),
        sa.Column("alias", sa.String(length=256), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["gene_id"], ["genes.id"], name=op.f("fk_gene_aliases_gene_id_genes"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gene_aliases")),
        sa.UniqueConstraint("gene_id", "alias", name="uq_gene_alias"),
    )
    op.create_index("ix_gene_alias_alias", "gene_aliases", ["alias"])

    # ── Mutant Lines ──────────────────────────────────────────────────────
    op.create_table(
        "mutant_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("species", sa.String(length=128), server_default="Glycine max", nullable=False),
        sa.Column("cultivar", sa.String(length=128), nullable=True),
        sa.Column("mutagen", sa.String(length=64), nullable=True),
        sa.Column("mutagen_dose", sa.String(length=64), nullable=True),
        sa.Column("generation", sa.String(length=32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("phenotype_summary", sa.Text(), nullable=True),
        sa.Column("image_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_public", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"], name=op.f("fk_mutant_lines_release_id_releases"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mutant_lines")),
    )
    op.create_index("ix_mutant_lines_name", "mutant_lines", ["name"], unique=True)
    op.create_index("ix_ml_mutagen", "mutant_lines", ["mutagen"])
    op.create_index("ix_ml_cultivar", "mutant_lines", ["cultivar"])

    # ── Phenotypes ────────────────────────────────────────────────────────
    op.create_table(
        "phenotypes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mutant_line_id", sa.Integer(), nullable=False),
        sa.Column("trait_category", sa.String(length=128), nullable=False),
        sa.Column("trait_name", sa.String(length=256), nullable=False),
        sa.Column("trait_value", sa.String(length=512), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("measurement_method", sa.String(length=256), nullable=True),
        sa.Column("image_url", sa.String(length=1024), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["mutant_line_id"], ["mutant_lines.id"], name=op.f("fk_phenotypes_mutant_line_id_mutant_lines"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_phenotypes")),
    )
    op.create_index("ix_phenotype_ml", "phenotypes", ["mutant_line_id"])
    op.create_index("ix_phenotype_trait", "phenotypes", ["trait_category", "trait_name"])

    # ── Variant Summaries ─────────────────────────────────────────────────
    op.create_table(
        "variant_summaries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("assembly_id", sa.Integer(), nullable=False),
        sa.Column("chromosome_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.BigInteger(), nullable=False),
        sa.Column("ref", sa.String(length=4096), nullable=False),
        sa.Column("alt", sa.String(length=4096), nullable=False),
        sa.Column(
            "variant_type",
            postgresql.ENUM(name="variant_type_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("gene_id", sa.String(length=64), nullable=True),
        sa.Column("consequence", sa.String(length=128), nullable=True),
        sa.Column(
            "impact",
            postgresql.ENUM(name="impact_enum", create_type=False),
            nullable=True,
        ),
        sa.Column("mutant_line_id", sa.Integer(), nullable=True),
        sa.Column("release_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["assembly_id"], ["assemblies.id"], name=op.f("fk_variant_summaries_assembly_id_assemblies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chromosome_id"], ["chromosomes.id"], name=op.f("fk_variant_summaries_chromosome_id_chromosomes"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["gene_id"], ["genes.id"], name=op.f("fk_variant_summaries_gene_id_genes"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["mutant_line_id"], ["mutant_lines.id"], name=op.f("fk_variant_summaries_mutant_line_id_mutant_lines"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"], name=op.f("fk_variant_summaries_release_id_releases"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_variant_summaries")),
    )
    op.create_index("ix_vs_chr_pos", "variant_summaries", ["chromosome_id", "position"])
    op.create_index("ix_vs_gene", "variant_summaries", ["gene_id"])
    op.create_index("ix_vs_mutant_line", "variant_summaries", ["mutant_line_id"])
    op.create_index("ix_vs_release", "variant_summaries", ["release_id"])
    op.create_index("ix_vs_type_impact", "variant_summaries", ["variant_type", "impact"])

    # ── Seed Inventory ────────────────────────────────────────────────────
    op.create_table(
        "seed_inventory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mutant_line_id", sa.Integer(), nullable=False),
        sa.Column("lot_number", sa.String(length=100), nullable=False),
        sa.Column("generation", sa.String(length=20), nullable=True),
        sa.Column("quantity_available", sa.Integer(), server_default="0", nullable=False),
        sa.Column("quantity_unit", sa.String(length=20), server_default="seeds", nullable=False),
        sa.Column("minimum_order", sa.Integer(), server_default="10", nullable=False),
        sa.Column("harvest_date", sa.Date(), nullable=True),
        sa.Column("harvest_location", sa.String(length=200), nullable=True),
        sa.Column("storage_location", sa.String(length=200), nullable=True),
        sa.Column("storage_condition", sa.String(length=100), nullable=True),
        sa.Column("germination_rate", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("purity", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("viability_test_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["mutant_line_id"], ["mutant_lines.id"], name=op.f("fk_seed_inventory_mutant_line_id_mutant_lines"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_seed_inventory")),
        sa.UniqueConstraint("mutant_line_id", "lot_number", name="uq_seed_inventory_line_lot"),
    )
    op.create_index("ix_seed_inventory_mutant_line_id", "seed_inventory", ["mutant_line_id"])
    op.create_index("ix_seed_inventory_is_active", "seed_inventory", ["is_active"])

    # ── Seed Requests ─────────────────────────────────────────────────────
    op.create_table(
        "seed_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_number", sa.String(length=50), nullable=False),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("recipient_name", sa.String(length=255), nullable=False),
        sa.Column("recipient_email", sa.String(length=255), nullable=False),
        sa.Column("institution", sa.String(length=255), nullable=False),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("state_province", sa.String(length=100), nullable=True),
        sa.Column("postal_code", sa.String(length=20), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("research_purpose", sa.Text(), nullable=False),
        sa.Column("intended_use", sa.String(length=200), nullable=True),
        sa.Column("material_transfer_agreement", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("mta_signed_date", sa.Date(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("fulfilled_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tracking_number", sa.String(length=100), nullable=True),
        sa.Column("shipping_carrier", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["fulfilled_by"], ["users.id"], name=op.f("fk_seed_requests_fulfilled_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], name=op.f("fk_seed_requests_requester_id_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name=op.f("fk_seed_requests_reviewed_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_seed_requests")),
    )
    op.create_index("ix_seed_requests_request_number", "seed_requests", ["request_number"], unique=True)
    op.create_index("ix_seed_requests_status", "seed_requests", ["status"])

    # ── Tracks ────────────────────────────────────────────────────────────
    op.create_table(
        "tracks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("track_type", sa.String(length=50), nullable=False),
        sa.Column("track_subtype", sa.String(length=50), nullable=True),
        sa.Column("visibility", sa.String(length=20), server_default="public", nullable=False),
        sa.Column("assembly_id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=True),
        sa.Column("uploader_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("display_config", postgresql.JSONB(astext_type=sa.Text()), server_default="'{}'::jsonb", nullable=False),
        sa.Column("color", sa.String(length=20), nullable=True),
        sa.Column("feature_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_featured", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("track_key", sa.String(length=100), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assembly_id"], ["assemblies.id"], name=op.f("fk_tracks_assembly_id_assemblies"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_tracks_project_id_projects"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"], name=op.f("fk_tracks_release_id_releases"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], name=op.f("fk_tracks_uploader_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tracks")),
        sa.UniqueConstraint("assembly_id", "track_key", name="uq_track_assembly_key"),
    )
    op.create_index("ix_tracks_assembly_id", "tracks", ["assembly_id"])
    op.create_index("ix_tracks_track_type", "tracks", ["track_type"])
    op.create_index("ix_tracks_is_active", "tracks", ["is_active"])

    # ── Track Categories ──────────────────────────────────────────────────
    op.create_table(
        "track_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_track_categories")),
    )
    op.create_index("ix_track_categories_name", "track_categories", ["name"], unique=True)

    # ── BLAST Databases ───────────────────────────────────────────────────
    op.create_table(
        "blast_databases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("db_type", sa.String(length=20), nullable=False),
        sa.Column("program", sa.String(length=20), nullable=False),
        sa.Column("db_path", sa.String(length=500), nullable=False),
        sa.Column("assembly_id", sa.Integer(), nullable=True),
        sa.Column("release_id", sa.Integer(), nullable=True),
        sa.Column("sequence_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total_length", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("is_public", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("build_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("version", sa.String(length=50), nullable=True),
        sa.Column("build_date", sa.Date(), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), server_default="'{}'::jsonb", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assembly_id"], ["assemblies.id"], name=op.f("fk_blast_databases_assembly_id_assemblies"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blast_databases")),
    )
    op.create_index("ix_blast_databases_name", "blast_databases", ["name"], unique=True)
    op.create_index("ix_blast_databases_is_active", "blast_databases", ["is_active"])

    # ── BLAST Jobs ────────────────────────────────────────────────────────
    op.create_table(
        "blast_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("job_id", sa.String(length=100), nullable=False),
        sa.Column("program", sa.String(length=20), nullable=False),
        sa.Column("database_id", sa.Integer(), nullable=False),
        sa.Column("query_sequence", sa.Text(), nullable=False),
        sa.Column("query_header", sa.String(length=500), nullable=True),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), server_default="'{}'::jsonb", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hit_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_runtime_seconds", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(length=200), nullable=True),
        sa.Column("is_public", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("celery_task_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["database_id"], ["blast_databases.id"], name=op.f("fk_blast_jobs_database_id_blast_databases"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"], name=op.f("fk_blast_jobs_submitted_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blast_jobs")),
    )
    op.create_index("ix_blast_jobs_job_id", "blast_jobs", ["job_id"], unique=True)
    op.create_index("ix_blast_jobs_status", "blast_jobs", ["status"])

    # ── Audit Logs ────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=True),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_audit_logs_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_resource", "audit_logs", ["resource_type", "resource_id"])
    op.create_index("ix_audit_user_ts", "audit_logs", ["user_id", "timestamp"])

    # ── News Articles ─────────────────────────────────────────────────────
    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("slug", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_published", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], name=op.f("fk_news_articles_author_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_news_articles")),
    )
    op.create_index("ix_news_articles_slug", "news_articles", ["slug"], unique=True)
    op.create_index("ix_news_articles_is_published", "news_articles", ["is_published"])

    # ── Publications ──────────────────────────────────────────────────────
    op.create_table(
        "publications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("authors", sa.Text(), nullable=True),
        sa.Column("journal", sa.String(length=500), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("doi", sa.String(length=200), nullable=True),
        sa.Column("pmid", sa.String(length=20), nullable=True),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publications")),
    )
    op.create_index("ix_publications_doi", "publications", ["doi"], unique=True)

    # ── Static Pages ──────────────────────────────────────────────────────
    op.create_table(
        "static_pages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_static_pages")),
    )
    op.create_index("ix_static_pages_slug", "static_pages", ["slug"], unique=True)

    # ── Download Files ────────────────────────────────────────────────────
    op.create_table(
        "download_files",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_url", sa.String(length=1024), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("file_format", sa.String(length=50), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("download_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"], name=op.f("fk_download_files_release_id_releases"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_download_files")),
    )
    op.create_index("ix_download_files_category", "download_files", ["category"])
    op.create_index("ix_download_files_is_active", "download_files", ["is_active"])


def downgrade() -> None:
    """Drop all tables and types."""
    op.drop_table("download_files")
    op.drop_table("static_pages")
    op.drop_table("publications")
    op.drop_table("news_articles")
    op.drop_table("audit_logs")
    op.drop_table("blast_jobs")
    op.drop_table("blast_databases")
    op.drop_table("track_categories")
    op.drop_table("tracks")
    op.drop_table("seed_requests")
    op.drop_table("seed_inventory")
    op.drop_table("variant_summaries")
    op.drop_table("phenotypes")
    op.drop_table("mutant_lines")
    op.drop_table("gene_aliases")
    op.drop_table("exons")
    op.drop_table("transcripts")
    op.drop_table("genes")
    op.drop_table("chromosomes")
    op.drop_table("assemblies")
    op.drop_table("releases")
    op.drop_table("project_members")
    op.drop_table("projects")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("organizations")

    op.execute("DROP TYPE IF EXISTS impact_enum")
    op.execute("DROP TYPE IF EXISTS variant_type_enum")
    op.execute("DROP TYPE IF EXISTS visibility_enum")
