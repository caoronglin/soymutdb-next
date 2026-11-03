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
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID

metadata = MetaData()

# These PostgreSQL types are declared only to compile worker Core statements
# against the API-owned schema. ``create_type=False`` is deliberate: migrations
# remain the sole owner of enum lifecycle.
release_status_enum = ENUM(
    "draft",
    "validated",
    "ready",
    "published",
    "rolled_back",
    name="release_status_enum",
    create_type=False,
)
page_definition_status_enum = ENUM(
    "draft",
    "preview",
    "requested",
    "published",
    name="page_definition_status_enum",
    create_type=False,
)
import_status_enum = ENUM(
    "uploading",
    "validating",
    "ingesting",
    "ready",
    "published",
    "failed",
    "rolled_back",
    name="import_status_enum",
    create_type=False,
)

# ``releases`` stays intentionally narrow: worker imports only lock/read the
# state needed to protect release-scoped writes.
releases = Table(
    "releases",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("version", String(32)),
    Column("status", release_status_enum, nullable=False),
)

genes = Table(
    "genes",
    metadata,
    Column("gene_pk", BigInteger, primary_key=True),
    Column("accession", String(64), nullable=False),
    Column("assembly_id", Integer, nullable=False),
    Column("chromosome_id", Integer, nullable=False),
    Column("name", String(256)),
    Column("biotype", String(64)),
    Column("start", BigInteger),
    Column("end", BigInteger),
    Column("strand", String(1)),
    Column("description", Text),
)

assemblies = Table(
    "assemblies",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(128), nullable=False),
    Column("version", String(64), nullable=False),
    # Release scoping for a gene build.  ``assemblies.release_id`` is API-owned
    # and nullable (an assembly can predate release assignment), so the worker
    # only ever filters on it -- it never writes it.  Kept narrow on purpose:
    # the worker needs the join key, not the rest of the assembly record.
    Column("release_id", Integer, ForeignKey("releases.id", ondelete="SET NULL")),
)

chromosomes = Table(
    "chromosomes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("assembly_id", Integer, nullable=False),
    Column("name", String(64)),
)

transcripts = Table(
    "transcripts",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("gene_id", BigInteger),
    Column("is_canonical", Boolean),
)

gene_aliases = Table(
    "gene_aliases",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("gene_id", BigInteger),
    Column("alias", String(256)),
    Column("source", String(128)),
)

expression_data = Table(
    "expression_data",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("gene_id", BigInteger, nullable=False),
    Column("library_id", Integer, nullable=False),
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
    Column("gene_id", BigInteger, nullable=False),
    Column("homolog_species", String(128), nullable=False),
    Column("homolog_gene_id", String(64), nullable=False),
    Column("homolog_type", String(16), nullable=False),
    Column("source", String(128)),
)

gene_data_cache = Table(
    "gene_data_cache",
    metadata,
    Column("gene_id", BigInteger, primary_key=True),
    Column("data", JSONB, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

import_tasks = Table(
    "import_tasks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("status", import_status_enum),
    Column("progress", Integer),
    Column("total_records", Integer),
    Column("processed_records", Integer),
    Column("error_message", Text),
    Column("error_detail", JSONB),
    Column("failed_batch", Integer),
    Column("completed_at", DateTime(timezone=True)),
)

data_sets = Table(
    "data_sets",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("type", String(32)),
    Column("release_id", Integer, ForeignKey("releases.id", ondelete="SET NULL")),
    Column("source_objects", JSONB),
    Column("status", import_status_enum),
    Column("validation_evidence", JSONB),
    Column("manifest", JSONB),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

module_data_rows = Table(
    "module_data_rows",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("module_key", String(80), nullable=False, index=True),
    Column(
        "release_id",
        Integer,
        ForeignKey("releases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("row_key", String(512), nullable=False),
    Column("data", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "module_key",
        "release_id",
        "row_key",
        name="uq_module_data_rows_module_release_row",
    ),
)

blast_databases = Table(
    "blast_databases",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(256)),
    Column("engine", String(16)),
    Column("db_type", String(4)),
    Column("build_status", String(20)),
    Column("build_error", Text),
    Column("build_attempt", Integer),
    Column("build_started_at", DateTime(timezone=True)),
    Column("build_finished_at", DateTime(timezone=True)),
    Column("index_health_checked_at", DateTime(timezone=True)),
    Column("file_path", String(2048)),
    Column("index_version", String(256)),
    Column("fasta_sha256", String(64)),
    Column("sequence_count", BigInteger),
    Column("total_length", BigInteger),
    Column("is_active", Boolean),
    Column("is_default", Boolean),
    Column("annotation_version", String(256)),
    Column("source_url", String(2048)),
    Column("source_version", String(256)),
    Column("license", Text),
    Column("assembly_id", Integer),
    Column("release_id", Integer),
    Column("assembly_version", String(64)),
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
    Column("parameters", JSONB),
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

#: Owner-scoped variant export records.  The API side owns the migration
#: (:mod:`app.models.variant_export`); the worker only advances the lifecycle
#: and records the produced artifact's object key.  ``status`` uses the shared
#: job vocabulary (``pending``/``running``/``succeeded``/``failed``), matching
#: the PostgreSQL enum ``variant_export_status_enum``.
variant_exports = Table(
    "variant_exports",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("status", String(32)),
    Column("artifact_path", String(2048)),
    Column("record_count", Integer),
    Column("file_size", Integer),
    Column("error_message", Text),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True)),
    # The row's own bookkeeping column: the worker's updates refresh it,
    # so "last touched" does not stay at creation time.
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

blast_hits = Table(
    "blast_hits",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("job_id", UUID(as_uuid=True)),
    Column("hsp_num", Integer),
    Column("query_id", String(256)),
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
    # Protein/transcript -> gene genomic coordinates, resolved through
    # explicit assembly-scoped relations. NULL means "no proven link".
    Column("genome_resolution", JSONB),
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

#: Page Builder version activation. The worker updates only the lifecycle
#: fields after consuming a durable publish request; schema remains API-owned.
page_definition_versions = Table(
    "page_definition_versions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("page_id", UUID(as_uuid=True), nullable=False),
    Column("status", page_definition_status_enum, nullable=False),
    Column("published_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
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

#: Import manifest control plane (ADR-0005 / Phase A).  The API owns the
#: table + the enum via migration 0037; the worker (P2-3) persists the same
#: lifecycle while it drives an import.  Mirroring the other tables here keeps
#: the worker image free of API source (H4).
import_manifest_status_enum = ENUM(
    "created",
    "parsing",
    "writing",
    "verifying",
    "published",
    "failed",
    name="import_manifest_status_enum",
    create_type=False,
)
import_manifests = Table(
    "import_manifests",
    metadata,
    Column("import_id", String(64), primary_key=True),
    Column("fingerprint", String(64), nullable=False, index=True, unique=True),
    Column("source_sha256", String(64), nullable=False),
    Column("release_id", Integer, nullable=False, index=True),
    Column("assembly_id", Integer, nullable=False),
    Column("importer_version", String(64), nullable=False),
    Column("schema_version", String(64), nullable=False),
    Column("normalization_version", String(64), nullable=False),
    Column("config_hash", String(64), nullable=False),
    Column(
        "status",
        import_manifest_status_enum,
        nullable=False,
        server_default="created",
    ),
    Column("expected_rows", BigInteger),
    Column("written_rows", BigInteger),
    Column("failure_code", String(128)),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


def utcnow() -> datetime:
    """Timezone-aware current time for status timestamps."""

    return datetime.now(UTC)


__all__ = [
    "analysis_jobs",
    "assemblies",
    "blast_hits",
    "blast_jobs",
    "chromosomes",
    "expression_data",
    "expression_libraries",
    "gene_data_cache",
    "gene_homologs",
    "genes",
    "gwas_jobs",
    "import_manifest_status_enum",
    "import_manifests",
    "import_tasks",
    "metadata",
    "notifications",
    "page_definition_versions",
    "publication_target_leases",
    "releases",
    "static_publications",
    "utcnow",
    "variant_exports",
]
