"""Add configurable table views and the species instance registry.

``table_view_templates`` stores an admin-authored ordered column set per table
kind, scoped by species, site variant and (optionally) release. ``species_instances``
registers the deployed species databases that one admin console manages.

Both are configuration rows: they carry no biological records and no internal
identifiers of mutants, genes or variants.

Partial unique indexes enforce the two invariants that matter:

* one default template per (kind, species, site_variant, release scope);
* one local instance per deployment.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "table_view_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "species",
            sa.String(length=128),
            server_default="Glycine max",
            nullable=False,
        ),
        sa.Column(
            "site_variant",
            sa.String(length=16),
            server_default="external",
            nullable=False,
        ),
        sa.Column("release_id", sa.Integer(), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "actions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('mutation_sites', 'variants', 'genes', 'mutant_lines')",
            name="ck_table_view_templates_kind",
        ),
        sa.CheckConstraint(
            "site_variant IN ('external', 'internal')",
            name="ck_table_view_templates_site_variant",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(columns) = 'array'", name="ck_table_view_templates_columns_array"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(actions) = 'object'", name="ck_table_view_templates_actions_object"
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["releases.id"],
            name="fk_table_view_templates_release",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_table_view_templates"),
    )
    op.create_index(
        "ix_table_view_templates_kind", "table_view_templates", ["kind"]
    )
    op.create_index(
        "ix_table_view_templates_lookup",
        "table_view_templates",
        ["kind", "species", "site_variant", "release_id"],
    )
    # ``release_id`` is NULL for a deployment-wide default, and a plain unique
    # index treats NULLs as distinct — two deployment-wide defaults would both
    # be accepted. The index therefore keys on ``coalesce(release_id, 0)``.
    # Raw DDL: Alembic's ``create_index`` would parenthesise the expression
    # tuple a second time and emit invalid SQL.
    op.execute(
        "CREATE UNIQUE INDEX uq_table_view_templates_default "
        "ON table_view_templates "
        "(kind, species, site_variant, coalesce(release_id, 0)) "
        "WHERE is_default"
    )

    op.create_table(
        "species_instances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("species", sa.String(length=128), nullable=False),
        sa.Column("api_base_url", sa.String(length=512), nullable=False),
        sa.Column("jbrowse_base_url", sa.String(length=512), nullable=True),
        sa.Column("portal_base_url", sa.String(length=512), nullable=True),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "is_local",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("api_base_url ~ '^https?://'", name="ck_species_instances_url"),
        sa.PrimaryKeyConstraint("id", name="pk_species_instances"),
    )
    op.create_index(
        "ix_species_instances_code", "species_instances", ["code"], unique=True
    )
    op.create_index(
        "uq_species_instances_local",
        "species_instances",
        ["is_local"],
        unique=True,
        postgresql_where=sa.text("is_local"),
    )


def downgrade() -> None:
    op.drop_index("uq_species_instances_local", table_name="species_instances")
    op.drop_index("ix_species_instances_code", table_name="species_instances")
    op.drop_table("species_instances")

    op.drop_index("uq_table_view_templates_default", table_name="table_view_templates")

    op.drop_index("ix_table_view_templates_lookup", table_name="table_view_templates")
    op.drop_index("ix_table_view_templates_kind", table_name="table_view_templates")
    op.drop_table("table_view_templates")
