"""add Page Builder templates"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "page_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="general"),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column(
            "preview_image_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("key", name="uq_page_templates_key"),
    )
    op.create_index("ix_page_templates_key", "page_templates", ["key"])
    op.create_index("ix_page_templates_category", "page_templates", ["category"])
    op.create_index("ix_page_templates_category_sort", "page_templates", ["category", "sort_order"])


def downgrade() -> None:
    op.drop_index("ix_page_templates_category_sort", table_name="page_templates")
    op.drop_index("ix_page_templates_category", table_name="page_templates")
    op.drop_index("ix_page_templates_key", table_name="page_templates")
    op.drop_table("page_templates")
