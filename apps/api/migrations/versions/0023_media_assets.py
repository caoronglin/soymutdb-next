"""Add verified media assets and canonical news cover references."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("public_url", sa.String(length=2048), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("alt_text", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("credit", sa.String(length=512), nullable=True),
        sa.Column("is_decorative", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="ready", nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("size_bytes > 0", name="ck_media_assets_size_positive"),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'archived')",
            name="ck_media_assets_status",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_media_assets_uploaded_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_assets")),
        sa.UniqueConstraint("object_key", name=op.f("uq_media_assets_object_key")),
    )
    op.create_index(
        "ix_media_assets_purpose", "media_assets", ["purpose"], unique=False
    )
    op.create_index(
        "ix_media_assets_status_purpose",
        "media_assets",
        ["status", "purpose"],
        unique=False,
    )
    op.create_index(
        "ix_media_assets_checksum", "media_assets", ["checksum_sha256"], unique=False
    )

    op.add_column(
        "news_articles",
        sa.Column("cover_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("news_articles", sa.Column("cover_alt_text", sa.Text(), nullable=True))
    op.create_index(
        "ix_news_articles_cover_asset_id", "news_articles", ["cover_asset_id"], unique=False
    )
    op.create_foreign_key(
        "fk_news_articles_cover_asset_id_media_assets",
        "news_articles",
        "media_assets",
        ["cover_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_news_articles_cover_asset_id_media_assets", "news_articles", type_="foreignkey"
    )
    op.drop_index("ix_news_articles_cover_asset_id", table_name="news_articles")
    op.drop_column("news_articles", "cover_alt_text")
    op.drop_column("news_articles", "cover_asset_id")
    op.drop_index("ix_media_assets_checksum", table_name="media_assets")
    op.drop_index("ix_media_assets_status_purpose", table_name="media_assets")
    op.drop_index("ix_media_assets_purpose", table_name="media_assets")
    op.drop_table("media_assets")
