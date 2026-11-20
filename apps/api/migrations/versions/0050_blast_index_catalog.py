"""Prepare explicit BLAST index metadata without enabling another engine.

Legacy protein indexes have a known sequence type; nucleotide subtypes and all
unrecorded source/annotation/license fields remain unknown. Downgrade refuses
nonlegacy engines and new unfinished indexes so an old binary cannot reinterpret
their file_path as a ready DIAMOND index. Remove those catalog rows (and handle
any dependent jobs explicitly) or restore compatible metadata before rollback.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Counts and build_status already exist since0001; retain their legacy
    # types, values, nullability and defaults on both upgrade and downgrade.
    for column in (
        sa.Column("engine", sa.String(16), server_default="diamond", nullable=False),
        sa.Column("sequence_type", sa.String(24)),
        sa.Column("annotation_version", sa.String(256)),
        sa.Column("source_url", sa.String(2048)),
        sa.Column("fasta_sha256", sa.String(64)),
        sa.Column("index_version", sa.String(256)),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("provenance", postgresql.JSONB()),
        sa.Column("license", sa.Text()),
    ):
        op.add_column("blast_databases", column)
    op.execute("UPDATE blast_databases SET sequence_type = 'protein' WHERE db_type = 'prot'")
    for name, condition in (
        ("engine", "engine IN ('diamond', 'ncbi_blast')"),
        ("sequence_type", "sequence_type IS NULL OR sequence_type IN "
         "('genome', 'cds', 'transcript', 'protein', 'repeat_masked', "
         "'pan_genome', 'family_consensus', 'custom')"),
        ("build_status", "build_status IN ('pending', 'ready', 'building', 'failed')"),
        ("sequence_count", "sequence_count >= 0"),
        ("total_length", "total_length >= 0"),
        ("fasta_sha256", "fasta_sha256 IS NULL OR fasta_sha256 ~ '^[a-f0-9]{64}$'"),
    ):
        op.create_check_constraint(f"ck_blast_catalog_{name}", "blast_databases", condition)
    op.create_index(
        "uq_blast_catalog_active_default", "blast_databases",
        ["assembly_id", "engine", "db_type"], unique=True,
        postgresql_where=sa.text("is_active AND is_default"),
    )


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM blast_databases
                WHERE engine <> 'diamond' OR build_status IN ('building', 'failed')
            ) THEN
                RAISE EXCEPTION 'Cannot downgrade BLAST catalog with nonlegacy engines '
                    'or unfinished indexes; reconcile these rows before rollback';
            END IF;
        END $$;
    """)
    op.drop_index("uq_blast_catalog_active_default", table_name="blast_databases")
    for suffix in (
        "engine", "sequence_type", "build_status", "sequence_count", "total_length", "fasta_sha256",
    ):
        op.drop_constraint(f"ck_blast_catalog_{suffix}", "blast_databases", type_="check")
    for name in (
        "license", "provenance", "is_default", "index_version", "fasta_sha256",
        "source_url", "annotation_version",
        "sequence_type", "engine",
    ):
        op.drop_column("blast_databases", name)
