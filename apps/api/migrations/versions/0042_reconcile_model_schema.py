"""Reconcile the migrated schema with the ORM models (deployment drift repair).

The test suite builds its schema from ``Base.metadata`` (``create_all``), so
columns that were added to the models without a migration stayed invisible until
a real deployment: news/static pages kept their single-language legacy columns,
``content_versions`` did not exist, and tracks/seeds/publications/blast were
missing fields the API selects. This migration adds exactly those, backfilling
from legacy columns where the data exists.

Backfill policy:
- a column with a legacy source or a safe default becomes NOT NULL after the
  backfill (``news_articles``/``static_pages`` bilingual fields, ``db_path`` →
  ``file_path``, ``sort_order`` → ``display_order``);
- a column whose historical value cannot be known is added NULLABLE: inventing
  a file format or a seed lot for existing rows would write wrong data, and the
  ORM still requires the field for every new row.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | None = None
depends_on: str | None = None

FILE_FORMAT_ENUM = postgresql.ENUM(
    "vcf",
    "bam",
    "cram",
    "bigwig",
    "bigbed",
    "gff3",
    "bed",
    "bw",
    name="file_format_enum",
    create_type=False,
)
TRACK_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "validating",
    "ready",
    "error",
    "deleted",
    name="track_status_enum",
    create_type=False,
)
SEED_REQUEST_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "approved",
    "rejected",
    "shipped",
    "cancelled",
    name="seed_request_status_enum",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    FILE_FORMAT_ENUM.create(bind, checkfirst=True)
    TRACK_STATUS_ENUM.create(bind, checkfirst=True)
    SEED_REQUEST_STATUS_ENUM.create(bind, checkfirst=True)

    # --- news_articles: bilingual fields from the legacy single-language ones --
    op.add_column("news_articles", sa.Column("title_en", sa.String(length=512), nullable=True))
    op.add_column("news_articles", sa.Column("title_zh", sa.String(length=512), nullable=True))
    op.add_column("news_articles", sa.Column("content_en", sa.Text(), nullable=True))
    op.add_column("news_articles", sa.Column("content_zh", sa.Text(), nullable=True))
    op.execute("UPDATE news_articles SET title_en = title WHERE title_en IS NULL")
    op.execute("UPDATE news_articles SET content_en = content WHERE content_en IS NULL")
    op.alter_column("news_articles", "title_en", nullable=False)
    op.alter_column("news_articles", "content_en", nullable=False)

    # --- static_pages: bilingual fields from the legacy single-language ones ---
    op.add_column("static_pages", sa.Column("title_en", sa.String(length=512), nullable=True))
    op.add_column("static_pages", sa.Column("title_zh", sa.String(length=512), nullable=True))
    op.add_column("static_pages", sa.Column("content_en", sa.Text(), nullable=True))
    op.add_column("static_pages", sa.Column("content_zh", sa.Text(), nullable=True))
    op.execute("UPDATE static_pages SET title_en = title WHERE title_en IS NULL")
    op.execute("UPDATE static_pages SET content_en = content WHERE content_en IS NULL")
    op.alter_column("static_pages", "title_en", nullable=False)
    op.alter_column("static_pages", "content_en", nullable=False)
    op.add_column(
        "static_pages",
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
    )
    op.add_column(
        "static_pages",
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_static_pages_author"),
            nullable=True,
        ),
    )
    op.add_column("static_pages", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("static_pages", sa.Column("category", sa.String(length=64), nullable=True))
    op.add_column(
        "static_pages", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True)
    )

    # --- publications ---------------------------------------------------------
    op.add_column(
        "publications",
        sa.Column("is_featured", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    # --- track_categories: display_order from sort_order ----------------------
    op.add_column("track_categories", sa.Column("display_order", sa.Integer(), nullable=True))
    op.execute("UPDATE track_categories SET display_order = sort_order WHERE display_order IS NULL")
    op.alter_column("track_categories", "display_order", nullable=False)

    # --- tracks ---------------------------------------------------------------
    # file_format/file_url have no legacy source: nullable, so an existing row is
    # never assigned a fabricated format or URL.
    op.add_column("tracks", sa.Column("file_format", FILE_FORMAT_ENUM, nullable=True))
    op.add_column(
        "tracks",
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("track_categories.id", ondelete="SET NULL", name="fk_tracks_category"),
            nullable=True,
        ),
    )
    op.add_column("tracks", sa.Column("file_url", sa.String(length=2048), nullable=True))
    op.add_column("tracks", sa.Column("index_url", sa.String(length=2048), nullable=True))
    op.add_column(
        "tracks",
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_tracks_owner"),
            nullable=True,
        ),
    )
    op.add_column(
        "tracks",
        sa.Column("status", TRACK_STATUS_ENUM, server_default="pending", nullable=False),
    )
    op.add_column("tracks", sa.Column("metadata", postgresql.JSONB(), nullable=True))
    op.add_column(
        "tracks",
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    # --- blast_databases: file_path from db_path ------------------------------
    op.add_column("blast_databases", sa.Column("file_path", sa.String(length=2048), nullable=True))
    op.execute("UPDATE blast_databases SET file_path = db_path WHERE file_path IS NULL")
    op.alter_column("blast_databases", "file_path", nullable=False)

    # --- blast_jobs -----------------------------------------------------------
    op.add_column(
        "blast_jobs",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_blasts_jobs_user"),
            nullable=True,
        ),
    )
    op.add_column("blast_jobs", sa.Column("result_path", sa.String(length=2048), nullable=True))
    op.add_column("blast_jobs", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))

    # --- seed_inventory: no legacy source for lots/quantities -----------------
    op.add_column("seed_inventory", sa.Column("seed_lot", sa.String(length=128), nullable=True))
    op.add_column("seed_inventory", sa.Column("quantity_grams", sa.Numeric(10, 2), nullable=True))
    op.add_column("seed_inventory", sa.Column("location", sa.String(length=256), nullable=True))
    op.add_column("seed_inventory", sa.Column("viability_pct", sa.Numeric(5, 2), nullable=True))

    # --- seed_requests: requester fields from the legacy recipient columns ----
    op.add_column(
        "seed_requests", sa.Column("requester_name", sa.String(length=256), nullable=True)
    )
    op.add_column(
        "seed_requests", sa.Column("requester_email", sa.String(length=320), nullable=True)
    )
    op.add_column(
        "seed_requests", sa.Column("requester_institution", sa.String(length=512), nullable=True)
    )
    op.add_column(
        "seed_requests",
        sa.Column(
            "mutant_line_id",
            sa.Integer(),
            sa.ForeignKey(
                "mutant_lines.id", ondelete="CASCADE", name="fk_seed_requests_mutant_line"
            ),
            nullable=True,
        ),
    )
    op.add_column("seed_requests", sa.Column("purpose", sa.Text(), nullable=True))
    op.add_column(
        "seed_requests", sa.Column("quantity_requested", sa.Numeric(10, 2), nullable=True)
    )
    op.add_column(
        "seed_requests",
        sa.Column(
            "reviewer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_seed_requests_reviewer"),
            nullable=True,
        ),
    )
    op.add_column("seed_requests", sa.Column("notes", sa.Text(), nullable=True))
    op.execute(
        "UPDATE seed_requests SET requester_name = recipient_name WHERE requester_name IS NULL"
    )
    op.execute(
        "UPDATE seed_requests SET requester_email = recipient_email WHERE requester_email IS NULL"
    )
    op.execute(
        "UPDATE seed_requests SET requester_institution = institution "
        "WHERE requester_institution IS NULL"
    )
    op.execute("UPDATE seed_requests SET purpose = research_purpose WHERE purpose IS NULL")
    op.alter_column("seed_requests", "requester_name", nullable=False)
    op.alter_column("seed_requests", "requester_email", nullable=False)
    op.alter_column("seed_requests", "requester_institution", nullable=False)
    op.alter_column("seed_requests", "purpose", nullable=False)

    # --- content_versions -----------------------------------------------------
    op.create_table(
        "content_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("page_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title_en", sa.String(length=512), nullable=False),
        sa.Column("title_zh", sa.String(length=512), nullable=True),
        sa.Column("content_en", sa.Text(), nullable=False),
        sa.Column("content_zh", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("edited_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("edit_comment", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["page_id"], ["static_pages.id"], ondelete="CASCADE", name="fk_content_versions_page"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_content_versions"),
    )
    op.create_index("ix_content_versions_page_id", "content_versions", ["page_id"])
    op.create_index("ix_content_version_page", "content_versions", ["page_id", "version"])


def downgrade() -> None:
    op.drop_index("ix_content_version_page", table_name="content_versions")
    op.drop_index("ix_content_versions_page_id", table_name="content_versions")
    op.drop_table("content_versions")

    for column in (
        "notes",
        "reviewer_id",
        "quantity_requested",
        "purpose",
        "mutant_line_id",
        "requester_institution",
        "requester_email",
        "requester_name",
    ):
        op.drop_column("seed_requests", column)
    for column in ("viability_pct", "location", "quantity_grams", "seed_lot"):
        op.drop_column("seed_inventory", column)
    for column in ("expires_at", "result_path", "user_id"):
        op.drop_column("blast_jobs", column)
    op.drop_column("blast_databases", "file_path")
    for column in (
        "is_deleted",
        "metadata",
        "status",
        "owner_id",
        "index_url",
        "file_url",
        "category_id",
        "file_format",
    ):
        op.drop_column("tracks", column)
    op.drop_column("track_categories", "display_order")
    op.drop_column("publications", "is_featured")
    for column in (
        "published_at",
        "category",
        "summary",
        "author_id",
        "status",
        "content_zh",
        "content_en",
        "title_zh",
        "title_en",
    ):
        op.drop_column("static_pages", column)
    for column in ("content_zh", "content_en", "title_zh", "title_en"):
        op.drop_column("news_articles", column)

    bind = op.get_bind()
    SEED_REQUEST_STATUS_ENUM.drop(bind, checkfirst=True)
    TRACK_STATUS_ENUM.drop(bind, checkfirst=True)
    FILE_FORMAT_ENUM.drop(bind, checkfirst=True)
