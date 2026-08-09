"""GWAS jobs table for the EMMAX / GEMMA association pipelines.

The API writes ``gwas_jobs`` rows together with their outbox events (same
transaction); the worker advances ``status`` / ``result_summary`` /
``error_message`` when the association run executes.  Status values use the
BLAST-style spelling (pending / running / completed / failed / cancelled)
mirroring the shared Job state machine (``soymutdb_jobs.status.JobStatus``).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0011"
# Chain serialization fix (B1/B5 parallel integration): 0010 (news
# operations, B1) is created first, so 0011 (gwas_jobs, B5) depends on it.
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the ``gwas_jobs`` table."""
    op.create_table(
        "gwas_jobs",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("phenotype_file_path", sa.String(length=2048), nullable=False),
        sa.Column("genotype_file_path", sa.String(length=2048), nullable=True),
        sa.Column("kinship_file_path", sa.String(length=2048), nullable=True),
        sa.Column("covariate_file_path", sa.String(length=2048), nullable=True),
        sa.Column(
            "object_type",
            sa.Enum("snp", "other", name="gwas_file_type_enum"),
            server_default="snp",
            nullable=False,
        ),
        sa.Column(
            "method",
            sa.Enum("emmax", "gemma", name="gwas_method_enum"),
            nullable=False,
        ),
        sa.Column("params", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="gwas_job_status_enum",
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("result_summary", JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            ["user_id"],
            ["users.id"],
            name=op.f("fk_gwas_jobs_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gwas_jobs")),
    )
    op.create_index("ix_gwas_jobs_status", "gwas_jobs", ["status"])
    op.create_index("ix_gwas_jobs_user_id", "gwas_jobs", ["user_id"])
    op.create_index("ix_gwas_jobs_method_status", "gwas_jobs", ["method", "status"])


def downgrade() -> None:
    """Drop the ``gwas_jobs`` table and its enums."""
    op.drop_index("ix_gwas_jobs_method_status", table_name="gwas_jobs")
    op.drop_index("ix_gwas_jobs_user_id", table_name="gwas_jobs")
    op.drop_index("ix_gwas_jobs_status", table_name="gwas_jobs")
    op.drop_table("gwas_jobs")
    op.execute("DROP TYPE IF EXISTS gwas_job_status_enum")
    op.execute("DROP TYPE IF EXISTS gwas_method_enum")
    op.execute("DROP TYPE IF EXISTS gwas_file_type_enum")
