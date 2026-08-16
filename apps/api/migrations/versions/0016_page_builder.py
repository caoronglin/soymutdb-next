"""Page Definitions: versioned, schema-validated page tree.

Adds ``page_definitions`` (route-addressed public pages) and
``page_definition_versions`` (immutable snapshots with a draft -> preview ->
requested -> published lifecycle).  A PostgreSQL enum ``page_definition_status_enum``
carries the version statuses.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    page_definition_status = postgresql.ENUM(
        "draft",
        "preview",
        "requested",
        "published",
        name="page_definition_status_enum",
        create_type=False,
    )

    op.create_table(
        "page_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route", sa.String(160), nullable=False),
        sa.Column("title_key", sa.String(160), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_page_definitions")),
        sa.UniqueConstraint("route", name=op.f("uq_page_definitions_route")),
    )

    op.create_table(
        "page_definition_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            page_definition_status,
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "definition",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("edited_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("edit_comment", sa.String(512), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["page_definitions.id"],
            name=op.f("fk_page_definition_versions_page_id_page_definitions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_page_definition_versions")),
        sa.UniqueConstraint(
            "page_id",
            "version",
            name=op.f("uq_page_definition_versions_page_id_version"),
        ),
    )
    op.create_index(
        "ix_page_definition_versions_page_id",
        "page_definition_versions",
        ["page_id"],
    )
    op.create_index(
        "ix_page_def_version_page_status",
        "page_definition_versions",
        ["page_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_page_def_version_page_status", table_name="page_definition_versions"
    )
    op.drop_index(
        "ix_page_definition_versions_page_id", table_name="page_definition_versions"
    )
    op.drop_table("page_definition_versions")
    op.drop_table("page_definitions")
    op.execute("DROP TYPE IF EXISTS page_definition_status_enum")
