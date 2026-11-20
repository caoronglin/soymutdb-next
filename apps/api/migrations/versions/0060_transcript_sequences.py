"""Add the per-transcript residue store.

Until this revision the platform held coordinates and annotations but not a
single residue: every gene detail response reported all four molecules
(``genomic``/``cds``/``transcript``/``protein``) as ``unavailable`` with
``no_sequence_store:<molecule>``. This adds the table those residues live in.

Shape, and why it is this small:

* one row per ``(transcript_id, molecule)``; ``molecule`` is currently
  ``cds`` or ``protein``, the two files the annotation ships per transcript.
  A molecule is a row, not a column, so a third one is data rather than a
  migration.
* ``sequence`` is the residue string, ``length`` and ``sha256`` its measured
  size and digest, so a reader never has to recompute what the writer already
  knew. Three check constraints keep the row from lying: the molecule is in the
  closed vocabulary, ``length = char_length(sequence)``, and the digest is
  64 lowercase hex characters.
* the reference genome is NOT here. 1 GB of FASTA shredded into rows would be
  neither storable nor queryable; ``assemblies.fasta_url``/``fai_url`` already
  point at the file and its ``.fai`` offsets, and the API slices a bounded
  interval out of it (``app.services.reference_sequence_service``).
* ``ON DELETE CASCADE`` on the transcript: re-importing a GFF3 replaces every
  transcript of an assembly, and residues belonging to transcripts that no
  longer exist must not survive that.

The table is additive and empty, so upgrade/downgrade are symmetric and no
data rewrite is involved.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "transcript_sequences",
        sa.Column("transcript_id", sa.String(length=64), nullable=False),
        sa.Column("molecule", sa.String(length=16), nullable=False),
        sa.Column("length", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["transcripts.id"],
            name="fk_transcript_sequences_transcript",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("transcript_id", "molecule", name="pk_transcript_sequences"),
        sa.CheckConstraint(
            "molecule IN ('cds', 'protein')",
            name="ck_transcript_sequences_molecule",
        ),
        sa.CheckConstraint(
            "length = char_length(sequence)",
            name="ck_transcript_sequences_length",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_transcript_sequences_sha256_shape",
        ),
        comment=(
            "Residues of one transcript for one molecule; the reference genome is "
            "sliced from assemblies.fasta_url instead of being stored here."
        ),
    )


def downgrade() -> None:
    op.drop_table("transcript_sequences")
