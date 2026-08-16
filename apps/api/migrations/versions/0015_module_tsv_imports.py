"""Module TSV import foundation: release-scoped schema/data tables.

Adds ``module_tsv`` to the import task type vocabulary and creates the
server-owned module schema registry plus release-scoped module data rows.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE import_task_type_enum ADD VALUE IF NOT EXISTS 'module_tsv'")

    op.create_table(
        "module_schemas",
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("columns", postgresql.JSONB(), nullable=False),
        sa.Column("unique_key", postgresql.JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("key", "version", name=op.f("pk_module_schemas")),
    )

    op.create_table(
        "module_data_rows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_key", sa.String(80), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("row_key", sa.String(512), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["releases.id"],
            name=op.f("fk_module_data_rows_release_id_releases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_module_data_rows")),
        sa.UniqueConstraint(
            "module_key", "release_id", "row_key",
            name="uq_module_data_rows_module_release_row",
        ),
    )
    op.create_index("ix_module_data_rows_module_key", "module_data_rows", ["module_key"])
    op.create_index("ix_module_data_rows_release_id", "module_data_rows", ["release_id"])


def downgrade() -> None:
    op.drop_index("ix_module_data_rows_release_id", table_name="module_data_rows")
    op.drop_index("ix_module_data_rows_module_key", table_name="module_data_rows")
    op.drop_table("module_data_rows")
    op.drop_table("module_schemas")
    # PostgreSQL cannot easily remove an enum value; keep the type value in
    # place for downgrade safety (the application no longer references it).
