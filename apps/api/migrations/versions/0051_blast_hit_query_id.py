"""Preserve the original query identifier for every BLAST HSP.

Legacy rows remain NULL: inventing a query ID would conflate multi-FASTA hits.
"""
import sqlalchemy as sa
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("blast_hits", sa.Column("query_id", sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column("blast_hits", "query_id")
