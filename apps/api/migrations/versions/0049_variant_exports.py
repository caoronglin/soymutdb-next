"""Durable owner-scoped variant export records.

The export request used to be answered by an outbox event alone: the durable
command record existed, but the *result* had no owner-visible home.  The
Celery/Redis result backend is disposable, so "is my export ready?" and "where
is my file?" could not be answered by PostgreSQL — the system of record.

This migration adds ``variant_exports``: the submitter, the lifecycle status
(shared job vocabulary), the release/assembly provenance, the artifact's
*object key* (never a URL) and the expiry after which the artifact is no
longer downloadable.

No existing table is altered and no existing data is rewritten: the new table
is empty until the next export request is accepted.
"""

from __future__ import annotations

from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None

ENUM_NAME = "variant_export_status_enum"
TABLE_NAME = "variant_exports"


def upgrade() -> None:
    op.execute(
        f"CREATE TYPE {ENUM_NAME} AS ENUM ('pending', 'running', 'succeeded', 'failed')"
    )
    op.execute(
        f"""
        CREATE TABLE {TABLE_NAME} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            status {ENUM_NAME} NOT NULL DEFAULT 'pending',
            release_key VARCHAR(64) NOT NULL,
            assembly_key VARCHAR(64),
            format VARCHAR(16) NOT NULL,
            compress BOOLEAN NOT NULL DEFAULT true,
            filters JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            artifact_path VARCHAR(2048),
            record_count INTEGER,
            file_size INTEGER,
            error_message TEXT,
            started_at TIMESTAMP WITH TIME ZONE,
            completed_at TIMESTAMP WITH TIME ZONE,
            expires_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(f"CREATE INDEX ix_variant_exports_user_id ON {TABLE_NAME} (user_id)")
    op.execute(f"CREATE INDEX ix_variant_exports_status ON {TABLE_NAME} (status)")
    op.execute(f"CREATE INDEX ix_variant_exports_created_at ON {TABLE_NAME} (created_at)")


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
    op.execute(f"DROP TYPE IF EXISTS {ENUM_NAME}")
