"""Add stable public identifier to mutant lines.

Adds ``mutant_lines.public_id`` (VARCHAR(32), unique, nullable). It is
nullable only while a line is unpublished; publication requires a value.
Values are issued by the application and never derived from the private
persistence key or the internal lab designation.

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mutant_lines",
        sa.Column("public_id", sa.String(length=32), nullable=True),
    )
    # A unique index (not a constraint) is required so multiple unpublished
    # rows may keep a NULL public_id.
    op.create_index(
        "ix_mutant_lines_public_id",
        "mutant_lines",
        ["public_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_mutant_lines_public_id", table_name="mutant_lines")
    op.drop_column("mutant_lines", "public_id")
