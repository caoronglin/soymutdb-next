"""Add bilingual fields to publications for EN/ZH display."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "publications",
        sa.Column("title_zh", sa.Text(), nullable=True),
    )
    op.add_column(
        "publications",
        sa.Column("authors_zh", sa.Text(), nullable=True),
    )
    op.add_column(
        "publications",
        sa.Column("abstract_zh", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("publications", "abstract_zh")
    op.drop_column("publications", "authors_zh")
    op.drop_column("publications", "title_zh")
