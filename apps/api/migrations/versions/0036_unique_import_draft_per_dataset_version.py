"""Ensure one Import Studio draft per immutable DatasetVersion."""

from __future__ import annotations

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | None = None
depends_on: str | None = None


CONSTRAINT_NAME = "uq_import_drafts_dataset_version"


def upgrade() -> None:
    """Make create/resume deterministic under concurrent requests.

    The migration intentionally fails if an existing database already has
    duplicate drafts.  Such rows represent ambiguous edit state and must be
    reconciled with an auditable product decision before the uniqueness
    guarantee can be enabled; silently deleting one would lose user edits.
    """
    op.create_unique_constraint(
        CONSTRAINT_NAME,
        "import_drafts",
        ["dataset_version_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        CONSTRAINT_NAME,
        "import_drafts",
        type_="unique",
    )
