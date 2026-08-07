"""Analysis jobs table for the fastp / scanpy pipelines.

The API writes ``analysis_jobs`` rows together with their outbox events (same
transaction); the worker advances ``status`` / ``result_summary`` when the
pipeline runs.  Status values mirror the shared Job state machine
(``soymutdb_jobs.status.JobStatus``): pending / queued / running / succeeded /
failed / cancel_requested / cancelled.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the ``analysis_jobs`` table."""
    op.create_table(
        "analysis_jobs",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "analysis_type",
            sa.Enum("FASTP", "SCANPY", name="analysis_type_enum"),
            nullable=False,
        ),
        sa.Column("input_objects", JSONB(), nullable=False),
        sa.Column(
            "params", JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "QUEUED",
                "RUNNING",
                "SUCCEEDED",
                "FAILED",
                "CANCEL_REQUESTED",
                "CANCELLED",
                name="analysis_job_status_enum",
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("result_summary", JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
            name=op.f("fk_analysis_jobs_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_jobs")),
    )
    op.create_index("ix_analysis_jobs_status", "analysis_jobs", ["status"])
    op.create_index("ix_analysis_jobs_user_id", "analysis_jobs", ["user_id"])
    op.create_index(
        "ix_analysis_jobs_type_status", "analysis_jobs", ["analysis_type", "status"]
    )


def downgrade() -> None:
    """Drop the ``analysis_jobs`` table and its enums."""
    op.drop_index("ix_analysis_jobs_type_status", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_user_id", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_status", table_name="analysis_jobs")
    op.drop_table("analysis_jobs")
    op.execute("DROP TYPE IF EXISTS analysis_job_status_enum")
    op.execute("DROP TYPE IF EXISTS analysis_type_enum")
