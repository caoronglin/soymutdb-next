"""Add searchable fields and view visibility to the saved admin data views.

A data view is the operator's multi-dimensional table over one release-scoped
source. 0058 persisted which fields it shows; this revision adds the two
remaining configuration axes the console needs:

* ``searchable_fields`` -- the allowlisted source fields the search box matches
  against, stored as a JSONB array so the same vocabulary check that guards
  ``visible_fields`` can reject a field the source does not expose;
* ``visibility`` -- ``visible`` (offered in the saved-view list) or ``hidden``
  (kept, still openable by id, but not advertised). This is a presentation
  flag, not a permission: no access decision is derived from it, and the row
  remains readable by any administrator who knows its id.

Both columns are additive. Existing rows keep working: the server defaults
give every 0058 row "searchable nowhere, visible".
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "admin_data_views",
        sa.Column(
            "searchable_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "admin_data_views",
        sa.Column(
            "visibility",
            sa.String(length=8),
            server_default="visible",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_admin_data_views_searchable_fields_array",
        "admin_data_views",
        "jsonb_typeof(searchable_fields) = 'array'",
    )
    op.create_check_constraint(
        "ck_admin_data_views_visibility",
        "admin_data_views",
        "visibility IN ('visible', 'hidden')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_admin_data_views_visibility", "admin_data_views", type_="check")
    op.drop_constraint(
        "ck_admin_data_views_searchable_fields_array",
        "admin_data_views",
        type_="check",
    )
    op.drop_column("admin_data_views", "visibility")
    op.drop_column("admin_data_views", "searchable_fields")
