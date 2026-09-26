"""Seed the local species instance so the console has a local target.

The console is the local deployment's admin surface, but a fresh database has
no ``species_instances`` row: the instance badge showed "—" and "set current"
had nothing to select until an operator hand-registered the local instance.
The seed is deployment-neutral console metadata (the local row is never probed
over the network — the request already reached this API), so an administrator
can edit name/URLs afterwards.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | None = None
depends_on: str | None = None

_SEEDED_CODE = "local"
_SEEDED_NAME = "Local SoyMutDB"
_SEEDED_API_BASE_URL = "http://localhost:8010"


def upgrade() -> None:
    # Idempotent and non-destructive: an existing local row (created by an
    # operator or an earlier deployment) wins.
    op.execute(
        sa.text(
            """
            INSERT INTO species_instances
                (code, name, species, api_base_url, is_enabled, is_local)
            SELECT :code, :name, 'Glycine max', :api_base_url, true, true
            WHERE NOT EXISTS (
                SELECT 1 FROM species_instances WHERE is_local
            )
            """
        ).bindparams(
            code=_SEEDED_CODE,
            name=_SEEDED_NAME,
            api_base_url=_SEEDED_API_BASE_URL,
        )
    )


def downgrade() -> None:
    # Only the untouched seed is removed; an edited row is operator data and
    # must survive the rollback (deleting it would erase registration work).
    op.execute(
        sa.text(
            """
            DELETE FROM species_instances
            WHERE code = :code
              AND name = :name
              AND api_base_url = :api_base_url
              AND is_local
            """
        ).bindparams(
            code=_SEEDED_CODE,
            name=_SEEDED_NAME,
            api_base_url=_SEEDED_API_BASE_URL,
        )
    )
