"""Add ``transcript_parts`` — CDS and UTR segments inside a transcript.

The schema has carried ``genes`` / ``transcripts`` / ``exons`` since 0001, but
nothing ever filled the latter two, and *no* table has ever been able to hold a
coding sequence. ``exons`` alone cannot describe a gene model: an exon is the
union of the coding and untranslated segments it contains, so a renderer that
sees only exons can draw boxes but cannot tell a CDS boundary from a UTR
boundary — and that distinction is the whole point of the annotation.

Sources are GFF3 files whose feature column already separates ``CDS``,
``five_prime_UTR`` and ``three_prime_UTR`` (the bundled
``Gmax_880_Wm82.a6.v1`` annotation carries 518,583 / 106,509 / 91,257 of them).
The column layout is chosen so the importer can stream rows without joining
back to ``transcripts`` for coordinates.

``Exon`` rows stay: the importer derives them by merging the parts of one
transcript, so existing exon consumers keep working and the two views cannot
disagree at the source. This migration only *adds* — no existing table is
altered, so the downgrade is a plain drop.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "transcript_parts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("transcript_id", sa.String(length=64), nullable=False),
        sa.Column("part_type", sa.String(length=24), nullable=False),
        sa.Column("start", sa.BigInteger(), nullable=False),
        sa.Column("end", sa.BigInteger(), nullable=False),
        sa.Column("order", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "part_type IN ('cds', 'five_prime_utr', 'three_prime_utr')",
            name="ck_transcript_parts_type",
        ),
        # `end` is a reserved word. `op.create_table` quotes column names
        # automatically, but a CheckConstraint's text is emitted verbatim, so an
        # unquoted `end >= start` reaches PostgreSQL as-is and the whole
        # CREATE TABLE fails with `syntax error at or near "end"`.
        sa.CheckConstraint('"end" >= "start"', name="ck_transcript_parts_order"),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["transcripts.id"],
            name="transcript_parts_transcript_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="transcript_parts_pkey"),
    )
    # The renderer's query is "every part of these transcripts", always grouped
    # by type and read in transcript order.
    op.create_index(
        "ix_transcript_parts_transcript",
        "transcript_parts",
        ["transcript_id", "part_type", "order"],
    )
    # A window query over a coordinate range is the other access path (the
    # region genome view asks "what is in this 20 kb").
    op.create_index("ix_transcript_parts_location", "transcript_parts", ["start", "end"])


def downgrade() -> None:
    op.drop_index("ix_transcript_parts_location", table_name="transcript_parts")
    op.drop_index("ix_transcript_parts_transcript", table_name="transcript_parts")
    op.drop_table("transcript_parts")
