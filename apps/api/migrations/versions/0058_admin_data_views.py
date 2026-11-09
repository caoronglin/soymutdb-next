"""Add saved multi-view configurations for the admin data workspace.

``admin_data_views`` stores presentation choices only: which allowlisted
fields to show for one read-only source (genes, variants or mutant lines),
the filters/sort to apply, and the grid/kanban/gallery render mode. It holds
no biological records and no identifiers, so it adds no data-access boundary.

Two indexes enforce the invariants:

* names are unique per source, so an operator can keep the same familiar
  label (for example "Chromosome view") for each source;
* at most one default view per source, via a partial unique index.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "admin_data_views",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "view_type",
            sa.String(length=16),
            server_default="grid",
            nullable=False,
        ),
        sa.Column(
            "visible_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "filters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("sort_field", sa.String(length=64), nullable=True),
        sa.Column("sort_dir", sa.String(length=4), nullable=True),
        sa.Column("group_field", sa.String(length=64), nullable=True),
        sa.Column("title_field", sa.String(length=64), nullable=True),
        sa.Column("page_size", sa.Integer(), server_default="25", nullable=False),
        sa.Column(
            "is_default", sa.Boolean(), server_default=sa.false(), nullable=False
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
            "source IN ('genes', 'variants', 'mutant_lines')",
            name="ck_admin_data_views_source",
        ),
        sa.CheckConstraint(
            "view_type IN ('grid', 'kanban', 'gallery')",
            name="ck_admin_data_views_view_type",
        ),
        sa.CheckConstraint(
            "sort_dir IS NULL OR sort_dir IN ('asc', 'desc')",
            name="ck_admin_data_views_sort_dir",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(visible_fields) = 'array'",
            name="ck_admin_data_views_visible_fields_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(filters) = 'object'",
            name="ck_admin_data_views_filters_object",
        ),
        sa.CheckConstraint(
            "page_size BETWEEN 5 AND 200",
            name="ck_admin_data_views_page_size",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_data_views"),
        sa.UniqueConstraint(
            "source", "name", name="uq_admin_data_views_source_name"
        ),
    )
    op.create_index(
        "ix_admin_data_views_source", "admin_data_views", ["source"]
    )
    op.create_index(
        "uq_admin_data_views_default",
        "admin_data_views",
        ["source"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_admin_data_views_default", table_name="admin_data_views"
    )
    op.drop_index("ix_admin_data_views_source", table_name="admin_data_views")
    op.drop_table("admin_data_views")