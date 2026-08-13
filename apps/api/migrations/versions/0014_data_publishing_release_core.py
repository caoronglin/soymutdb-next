"""Data publishing and release core schema."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE import_task_status_enum RENAME TO import_status_enum")
    for old, new in (("queued", "uploading"), ("running", "validating"), ("completed", "ready")):
        op.execute(f"ALTER TYPE import_status_enum RENAME VALUE '{old}' TO '{new}'")
    op.execute("ALTER TYPE import_status_enum ADD VALUE IF NOT EXISTS 'ingesting'")
    op.execute("ALTER TYPE import_status_enum ADD VALUE IF NOT EXISTS 'published'")
    op.execute("ALTER TYPE import_status_enum ADD VALUE IF NOT EXISTS 'rolled_back'")
    op.execute("CREATE TYPE release_status_enum AS ENUM ('draft', 'validated', 'ready', 'published', 'rolled_back')")
    op.add_column("releases", sa.Column("status", postgresql.ENUM(name="release_status_enum", create_type=False), nullable=False, server_default="draft"))
    op.create_table("data_sets",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("type", sa.String(32), nullable=False),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id", ondelete="SET NULL")),
        sa.Column("source_objects", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", postgresql.ENUM(name="import_status_enum", create_type=False), nullable=False, server_default="uploading"),
        sa.Column("validation_evidence", postgresql.JSONB()), sa.Column("manifest", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("release_data_sets", sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("data_set_id", sa.Integer(), sa.ForeignKey("data_sets.id", ondelete="CASCADE"), primary_key=True))
    op.create_table("active_release", sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id", ondelete="RESTRICT")))
    op.execute("INSERT INTO active_release (id, release_id) VALUES (1, NULL)")
    op.create_table("provenance", sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("data_set_id", sa.Integer(), sa.ForeignKey("data_sets.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("object_key", sa.String(1024), nullable=False), sa.Column("checksum_sha256", sa.String(64), nullable=False),
                    sa.Column("source", sa.String(1024), nullable=False), sa.Column("tool", sa.String(128)), sa.Column("tool_version", sa.String(64)),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    for name, column in (("data_set_id", sa.Column("data_set_id", sa.Integer(), sa.ForeignKey("data_sets.id", ondelete="SET NULL"))),
                         ("release_id", sa.Column("release_id", sa.Integer(), sa.ForeignKey("releases.id", ondelete="SET NULL"))),
                         ("idempotency_key", sa.Column("idempotency_key", sa.String(256), nullable=True)),
                         ("object_key", sa.Column("object_key", sa.String(1024))), ("error_detail", sa.Column("error_detail", postgresql.JSONB())),
                         ("failed_batch", sa.Column("failed_batch", sa.Integer())), ("retry_count", sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False))):
        op.add_column("import_tasks", column)
    op.create_unique_constraint("uq_import_tasks_idempotency_key", "import_tasks", ["idempotency_key"])
    for name, column in (("assembly", sa.Column("assembly", sa.String(128))), ("manifest", sa.Column("manifest", postgresql.JSONB())),
                         ("active_at", sa.Column("active_at", sa.DateTime(timezone=True))), ("rolled_back_at", sa.Column("rolled_back_at", sa.DateTime(timezone=True))),
                         ("reason", sa.Column("reason", sa.Text()))):
        op.add_column("releases", column)


def downgrade() -> None:
    for column in ("reason", "rolled_back_at", "active_at", "manifest", "assembly", "status"):
        op.drop_column("releases", column)
    op.execute("DROP TYPE IF EXISTS release_status_enum")
    op.drop_constraint("uq_import_tasks_idempotency_key", "import_tasks", type_="unique")
    for column in ("retry_count", "failed_batch", "error_detail", "object_key", "idempotency_key", "release_id", "data_set_id"):
        op.drop_column("import_tasks", column)
    op.drop_table("provenance")
    op.drop_table("active_release")
    op.drop_table("release_data_sets")
    op.drop_table("data_sets")
