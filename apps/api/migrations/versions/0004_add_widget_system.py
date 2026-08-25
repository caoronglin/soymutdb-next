"""Add widget system: widgets and page_layouts tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-05 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create widgets and page_layouts tables with seed data."""
    # ── Enums ─────────────────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE widget_category_enum AS ENUM "
        "('hero', 'navigation', 'search', 'data_table', 'detail', "
        "'visualization', 'stats', 'external', 'layout', 'custom')"
    )
    op.execute(
        "CREATE TYPE widget_permission_enum AS ENUM ('public', 'authenticated', 'admin')"
    )

    # ── Widgets ───────────────────────────────────────────────────────────
    op.create_table(
        "widgets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "category",
            postgresql.ENUM(name="widget_category_enum", create_type=False),
            server_default="custom",
            nullable=False,
        ),
        sa.Column("template_path", sa.String(length=512), nullable=False),
        sa.Column("data_source", sa.String(length=256), nullable=True),
        sa.Column(
            "params_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("cache_ttl", sa.Integer(), server_default="300", nullable=False),
        sa.Column(
            "admin_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "permissions",
            postgresql.ENUM(name="widget_permission_enum", create_type=False),
            server_default="public",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_widgets")),
    )
    op.create_index("ix_widgets_name", "widgets", ["name"], unique=True)

    # ── Page Layouts ──────────────────────────────────────────────────────
    op.create_table(
        "page_layouts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("page_name", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.Column(
            "widget_order",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_page_layouts")),
    )
    op.create_index("ix_page_layouts_name", "page_layouts", ["page_name"], unique=True)

    # ── Seed default widgets ──────────────────────────────────────────────
    op.execute(
        """
        INSERT INTO widgets (name, display_name, description, category, template_path, cache_ttl, permissions, is_active)
        VALUES
          ('hero', 'Hero Banner', 'Landing page hero section with title, subtitle, and CTA button', 'hero', 'hero.html', 300, 'public', true),
          ('stats', 'Statistics Cards', 'Key database statistics displayed as cards', 'stats', 'stats.html', 300, 'public', true),
          ('search_bar', 'Search Bar', 'Main search input with type selector', 'search', 'search_bar.html', 600, 'public', true),
          ('variant_table', 'Variant Table', 'Tabular display of variant search results', 'data_table', 'variant_table.html', 60, 'public', true),
          ('gene_detail', 'Gene Detail', 'Detailed gene information view', 'detail', 'gene_detail.html', 300, 'public', true),
          ('chromosome_view', 'Chromosome View', 'SVG chromosome ideogram with variant density', 'visualization', 'chromosome_view.html', 300, 'public', true),
          ('external_result', 'External Result', 'Display results from external data sources', 'external', 'external_result.html', 300, 'public', true),
          ('error', 'Error Display', 'Error message widget', 'layout', 'error.html', 0, 'public', true),
          ('sample_detail', 'Sample Detail', 'Detailed mutant/sample information view', 'detail', 'sample_detail.html', 300, 'public', true),
          ('quick_stats', 'Quick Stats Bar', 'Compact inline statistics bar', 'stats', 'quick_stats.html', 300, 'public', true),
          ('sra_run', 'SRA Run Detail', 'NCBI SRA run metadata card fetched from runinfo API', 'detail', 'sra_run.html', 300, 'public', true)
        """
    )
    # Set data_source for widgets that need dynamic data loading
    op.execute(
        """
        UPDATE widgets SET data_source = 'sra_run'
        WHERE name = 'sra_run'
        """
    )

    # ── Seed default layouts ──────────────────────────────────────────────
    op.execute(
        """
        INSERT INTO page_layouts (page_name, display_name, widget_order, is_active)
        VALUES
          ('index', 'Home Page', '["hero", "search_bar", "stats", "quick_stats"]'::jsonb, true),
          ('about', 'About Page', '["hero"]'::jsonb, true),
          ('browse', 'Browse Page', '["chromosome_view", "stats"]'::jsonb, true),
          ('search', 'Search Results', '["search_bar", "variant_table"]'::jsonb, true)
        """
    )


def downgrade() -> None:
    """Drop widget tables and enums."""
    op.drop_table("page_layouts")
    op.drop_table("widgets")

    op.execute("DROP TYPE IF EXISTS widget_permission_enum")
    op.execute("DROP TYPE IF EXISTS widget_category_enum")
