"""Narrow SQLAlchemy Core table definitions for tables the worker accesses.

Replaces the old dependency on the API's ``app.models`` ORM classes: the
worker only touches a handful of columns, declared here explicitly, so the
worker image never imports API source code.  These tables are only used to
build SELECT/INSERT/UPDATE statements — never to create schema.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID

metadata = MetaData()

genes = Table(
    "genes",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(256)),
    Column("biotype", String(64)),
    Column("chromosome_id", Integer),
    Column("start", BigInteger),
    Column("end", BigInteger),
    Column("strand", String(1)),
    Column("description", Text),
)

chromosomes = Table(
    "chromosomes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(64)),
)

expression_data = Table(
    "expression_data",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("gene_id", String(64)),
    Column("library_id", Integer),
    Column("fpkm", Float),
    Column("tpm", Float),
    Column("raw_count", BigInteger),
)

expression_libraries = Table(
    "expression_libraries",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("library_name", String(256)),
    Column("tissue", String(32)),
    Column("treatment", String(32)),
)

gene_homologs = Table(
    "gene_homologs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("gene_id", String(64)),
    Column("homolog_species", String(128)),
    Column("homolog_gene_id", String(64)),
    Column("homolog_type", String(16)),
    Column("source", String(128)),
)

gene_data_cache = Table(
    "gene_data_cache",
    metadata,
    Column("gene_id", String(64), primary_key=True),
    Column("data", JSON),
    Column("updated_at", DateTime(timezone=True)),
)

import_tasks = Table(
    "import_tasks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("status", String(32)),
    Column("progress", Integer),
    Column("total_records", Integer),
    Column("processed_records", Integer),
    Column("error_message", Text),
    Column("completed_at", DateTime(timezone=True)),
)

blast_jobs = Table(
    "blast_jobs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("status", String(32)),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("error_message", Text),
    Column("result_path", String(2048)),
    Column("query_len", Integer),
    Column("hit_count", Integer),
)

#: Online-analysis jobs (fastp, scanpy).  The API side (W1-B) owns the
#: migration (:mod:`app.models.analysis_job`); the worker only reads/writes
#: the columns declared below.  ``status`` mirrors the shared state machine
#: and is persisted with its canonical spelling (``succeeded``, not
#: ``completed``), matching the PostgreSQL enum ``analysis_job_status_enum``.
analysis_jobs = Table(
    "analysis_jobs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("status", String(32)),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("error_message", Text),
    Column("result_summary", JSON),
)

blast_hits = Table(
    "blast_hits",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("job_id", UUID(as_uuid=True)),
    Column("hsp_num", Integer),
    Column("subject_id", String(256)),
    Column("subject_title", String(1024)),
    Column("percent_identity", Float),
    Column("alignment_length", Integer),
    Column("mismatches", Integer),
    Column("gap_opens", Integer),
    Column("query_start", Integer),
    Column("query_end", Integer),
    Column("subject_start", Integer),
    Column("subject_end", Integer),
    Column("evalue", Float),
    Column("bit_score", Float),
    Column("query_strand", String(8)),
    Column("subject_strand", String(8)),
)


def utcnow() -> datetime:
    """Timezone-aware current time for status timestamps."""

    return datetime.now(UTC)


__all__ = [
    "analysis_jobs",
    "blast_hits",
    "blast_jobs",
    "chromosomes",
    "expression_data",
    "expression_libraries",
    "gene_data_cache",
    "gene_homologs",
    "genes",
    "import_tasks",
    "metadata",
    "utcnow",
]
