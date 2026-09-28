"""Persist the build-artifact reference a publication was requested from.

``static_publications.artifact_url`` records the *output* artifact that was
built; the request also needs to record the *input* the build was produced from.
Without it the outbox payload was the only carrier, so a publication's audit
trail could show a manifest digest with no way to identify the source tree that
produced it.

The column is nullable: a request may legitimately omit the reference (the
worker then fails closed with ``MissingBuildOutput`` rather than publishing a
synthetic page), and existing rows predate the requirement.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "static_publications",
        sa.Column("build_artifact_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("static_publications", "build_artifact_url")
