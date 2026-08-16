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
    Column("error_detail", JSON),
    Column("failed_batch", Integer),
    Column("completed_at", DateTime(timezone=True)),
)

data_sets = Table(
    "data_sets",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("type", String(32)),
    Column("release_id", Integer),
    Column("source_objects", JSON),
    Column("status", String(32)),
    Column("validation_evidence", JSON),
    Column("manifest", JSON),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

module_data_rows = Table(
    "module_data_rows",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("module_key", String(80)),
    Column("release_id", Integer),
    Column("row_key", String(512)),
    Column("data", JSON),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

blast_jobs = Table(
    "blast_jobs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True)),
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
    Column("user_id", UUID(as_uuid=True)),
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

#: GWAS association jobs (EMMAX / GEMMA).  The API side (B5) owns the
#: migration (:mod:`app.models.gwas`); the worker only reads/writes the
#: columns declared below.  ``status`` uses the BLAST-style spelling
#: (``completed``, not ``succeeded``), matching the PostgreSQL enum
#: ``gwas_job_status_enum``.
gwas_jobs = Table(
    "gwas_jobs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True)),
    Column("status", String(32)),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("error_message", Text),
    Column("result_summary", JSON),
)

#: In-app notification centre rows (D2).  The worker writes these directly
#: via :class:`soymutdb_worker.repositories.NotifyStore`; the API owns the
#: migration (:mod:`app.models.notification`) and reads them back for the
#: authenticated notification endpoints.  ``link`` carries the app route
#: opened on click (e.g. ``/blast/jobs/{job_id}``) and doubles as the
#: worker-side dedup key (one row per user + job link).
notifications = Table(
    "notifications",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True)),
    Column("type", String(64)),
    Column("title", String(256)),
    Column("body", Text),
    Column("link", String(512)),
    Column("read_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
)

#: Immutable static publication rows (Phase 3).  The worker reads/writes the
#: status columns only; the API owns the migration.  Column set mirrors
#: ``app.models.publication.StaticPublication``.
static_publications = Table(
    "static_publications",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("publication_id", Integer),
    Column("target", String(32)),
    Column("status", String(32)),
    Column("release_id", Integer),
    Column("page_definition_version", Integer),
    Column("manifest_digest", String(64)),
    Column("artifact_url", Text),
    Column("remote_id", Text),
    Column("previous_publication_id", Integer),
    Column("evidence", JSON),
    Column("error_message", Text),
    Column("requested_by", String(64)),
    Column("superseded_by_publication_id", Integer),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

#: Target-scoped lease row (latest request id per target, Phase 3).
publication_target_leases = Table(
    "publication_target_leases",
    metadata,
    Column("target", String(32), primary_key=True),
    Column("latest_publication_id", Integer),
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
    "gwas_jobs",
    "import_tasks",
    "metadata",
    "notifications",
    "publication_target_leases",
    "static_publications",
    "utcnow",
]
