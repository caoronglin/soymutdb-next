"""Align ``tracks.visibility`` with the ORM's ``track_visibility_enum``.

0042 reconciled the migrated schema with the ORM models, but only converted
``tracks.status``. ``tracks.visibility`` was left as the ``varchar(20)`` that
0001 created, while ``Track.visibility`` declares

    Enum(TrackVisibility, name="track_visibility_enum", ...)

and **no** migration ever created that type (0001's ``visibility_enum`` is an
orphan with a different vocabulary, referenced by no table). On any
alembic-built database the type is therefore missing and PostgreSQL fails while
preparing the statement:

    type "track_visibility_enum" does not exist

That is a 500 on ``GET /tracks``. The suite builds its schema from
``Base.metadata`` (``create_all``), which does create the type, so the drift
was invisible to it -- the same blind spot 0042 documents.

Backfill direction: 0001 allowed any 20-character string, and the older shared
vocabulary included ``organization``, which ``TrackVisibility`` does not
define. Coercing an out-of-vocabulary row to ``public`` could publish a track
that was scoped to an organization, so such a row becomes the most restrictive
value instead. (Widening visibility is the one direction that must never be
the default of a schema repair.)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | None = None
depends_on: str | None = None

TRACK_VISIBILITY_ENUM = postgresql.ENUM(
    "public",
    "project",
    "private",
    name="track_visibility_enum",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    TRACK_VISIBILITY_ENUM.create(bind, checkfirst=True)

    op.execute(
        "UPDATE tracks SET visibility = 'private' "
        "WHERE visibility NOT IN ('public', 'project', 'private')"
    )

    # Drop the varchar default first: it is typed `character varying`, and
    # leaving it in place while the column becomes an enum would leave the
    # default un-castable. It is restored below, typed.
    op.alter_column(
        "tracks",
        "visibility",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "tracks",
        "visibility",
        existing_type=sa.String(length=20),
        type_=TRACK_VISIBILITY_ENUM,
        existing_nullable=False,
        postgresql_using="visibility::track_visibility_enum",
    )
    op.alter_column(
        "tracks",
        "visibility",
        existing_type=TRACK_VISIBILITY_ENUM,
        existing_nullable=False,
        server_default="public",
    )


def downgrade() -> None:
    op.alter_column(
        "tracks",
        "visibility",
        existing_type=TRACK_VISIBILITY_ENUM,
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "tracks",
        "visibility",
        existing_type=TRACK_VISIBILITY_ENUM,
        type_=sa.String(length=20),
        existing_nullable=False,
        postgresql_using="visibility::text",
    )
    op.alter_column(
        "tracks",
        "visibility",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        server_default="public",
    )
    TRACK_VISIBILITY_ENUM.drop(op.get_bind(), checkfirst=True)
