"""Persist proven genomic coordinates for BLAST hits, never AA offsets.

``blastp``/``blastx``/``tblastn`` subject start/end are amino-acid or
translated coordinates. A genome-browser link is only legitimate when the
subject ID was resolved through an explicit protein/transcript/gene relation
in the searched assembly. This additive column stores that resolution (or a
machine-readable "unresolved" reason). Legacy rows stay NULL.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blast_hits",
        sa.Column("genome_resolution", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blast_hits", "genome_resolution")
