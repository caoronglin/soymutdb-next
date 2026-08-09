"""Seed request contacts table (D1 — public seed/gene-material requests).

The new ``seed_request_contacts`` table backs the public contact module:
anyone may submit a request (name / email / institution / country + up to
200 gene IDs), an outbox event dispatches the confirmation + admin
notification emails through the worker (``soymutdb_worker.tasks.email``),
and curators advance the small status machine
(pending → approved/rejected → fulfilled).

The table is intentionally named ``seed_request_contacts`` rather than
``seed_requests``: migration 0001 already created a ``seed_requests`` table
(legacy authenticated requests against mutant lines), so a new table avoids
a schema collision.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0012"
# Chain serialization: 0011 (gwas_jobs, B5) is the current head.
down_revision: str | None = "0011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the ``seed_request_contacts`` table."""
    op.create_table(
        "seed_request_contacts",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("institution", sa.String(length=512), nullable=False),
        sa.Column("country", sa.String(length=128), nullable=False),
        sa.Column("gene_ids", JSONB(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "fulfilled",
                name="seed_request_contact_status_enum",
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_by", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["processed_by"],
            ["users.id"],
            name=op.f("fk_seed_request_contacts_processed_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_seed_request_contacts")),
    )
    op.create_index(
        "ix_seed_request_contacts_status", "seed_request_contacts", ["status"]
    )
    op.create_index(
        "ix_seed_request_contacts_email", "seed_request_contacts", ["email"]
    )


def downgrade() -> None:
    """Drop the ``seed_request_contacts`` table and its status enum."""
    op.drop_index("ix_seed_request_contacts_email", table_name="seed_request_contacts")
    op.drop_index("ix_seed_request_contacts_status", table_name="seed_request_contacts")
    op.drop_table("seed_request_contacts")
    op.execute("DROP TYPE IF EXISTS seed_request_contact_status_enum")
