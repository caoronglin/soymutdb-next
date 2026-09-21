"""Add import_manifests: application-level control plane for import idempotency (ADR-0005)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "import_manifests",
        sa.Column("import_id", sa.String(length=64), primary_key=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("assembly_id", sa.Integer(), nullable=False),
        sa.Column("importer_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("normalization_version", sa.String(length=64), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "created",
                "parsing",
                "writing",
                "verifying",
                "published",
                "failed",
                name="import_manifest_status_enum",
            ),
            nullable=False,
            server_default=sa.text("'created'::import_manifest_status_enum"),
        ),
        sa.Column("expected_rows", sa.BigInteger(), nullable=True),
        sa.Column("written_rows", sa.BigInteger(), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_import_manifests_fingerprint",
        "import_manifests",
        ["fingerprint"],
        unique=True,
    )
    op.create_index(
        "ix_import_manifests_release_id",
        "import_manifests",
        ["release_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_import_manifests_release_id", table_name="import_manifests")
    op.drop_index("ix_import_manifests_fingerprint", table_name="import_manifests")
    op.drop_table("import_manifests")
    op.execute("DROP TYPE IF EXISTS import_manifest_status_enum")
