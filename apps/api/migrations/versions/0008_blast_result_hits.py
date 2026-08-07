"""BLAST result persistence: ``blast_hits`` table and job result stats.

The worker persists parsed HSP rows into ``blast_hits`` (delete-then-insert
per job, so re-deliveries never leave duplicate result sets) and records
``hit_count`` / ``query_len`` on ``blast_jobs`` when a run succeeds.  The raw
BLAST output file itself lives in MinIO under ``blast-results/{job_id}.json``
with checksum/size metadata; only the parsed rows land in PostgreSQL.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create ``blast_hits`` and extend ``blast_jobs`` with result stats."""
    op.add_column(
        "blast_jobs",
        sa.Column("hit_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "blast_jobs",
        sa.Column("query_len", sa.Integer(), nullable=True),
    )
    op.create_table(
        "blast_hits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", UUID(as_uuid=True), nullable=False),
        sa.Column("hsp_num", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.String(length=256), nullable=False),
        sa.Column("subject_title", sa.String(length=1024), nullable=True),
        sa.Column("percent_identity", sa.Float(), nullable=False),
        sa.Column("alignment_length", sa.Integer(), nullable=False),
        sa.Column("mismatches", sa.Integer(), nullable=False),
        sa.Column("gap_opens", sa.Integer(), nullable=False),
        sa.Column("query_start", sa.Integer(), nullable=False),
        sa.Column("query_end", sa.Integer(), nullable=False),
        sa.Column("subject_start", sa.Integer(), nullable=False),
        sa.Column("subject_end", sa.Integer(), nullable=False),
        sa.Column("evalue", sa.Float(), nullable=False),
        sa.Column("bit_score", sa.Float(), nullable=False),
        sa.Column(
            "query_strand", sa.String(length=8), server_default="plus", nullable=False
        ),
        sa.Column(
            "subject_strand", sa.String(length=8), server_default="plus", nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["blast_jobs.id"],
            name=op.f("fk_blast_hits_job_id_blast_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blast_hits")),
    )
    op.create_index("ix_blast_hits_job_id", "blast_hits", ["job_id"])
    op.create_index("ix_blast_hits_subject_id", "blast_hits", ["subject_id"])
    op.create_index("ix_blast_hits_job_evalue", "blast_hits", ["job_id", "evalue"])
    op.create_index(
        "ix_blast_hits_job_bit_score", "blast_hits", ["job_id", "bit_score"]
    )


def downgrade() -> None:
    """Drop ``blast_hits`` and the added ``blast_jobs`` columns."""
    op.drop_index("ix_blast_hits_job_bit_score", table_name="blast_hits")
    op.drop_index("ix_blast_hits_job_evalue", table_name="blast_hits")
    op.drop_index("ix_blast_hits_subject_id", table_name="blast_hits")
    op.drop_index("ix_blast_hits_job_id", table_name="blast_hits")
    op.drop_table("blast_hits")
    op.drop_column("blast_jobs", "query_len")
    op.drop_column("blast_jobs", "hit_count")
