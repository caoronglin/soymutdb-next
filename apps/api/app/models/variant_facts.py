"""PostgreSQL bulk facts and privacy-minimized telemetry table metadata.

Core tables avoid eagerly loading relationships for bulk reads and imports.
Surrogate hashes retained from legacy imports are factual payload, not foreign
keys to genes or mutant lines; only release and assembly keys are authoritative.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base


def _fact_columns() -> list[Column]:
    return [
        Column("release_id", Integer, ForeignKey("releases.id", ondelete="CASCADE"),
               nullable=False),
        Column("assembly_id", Integer, ForeignKey("assemblies.id", ondelete="RESTRICT"),
               nullable=False),
        Column("variant_id", Numeric(20, 0), nullable=False),
        Column("assembly_key", Text, nullable=False),
        Column("chromosome", Text, nullable=False),
        Column("position", BigInteger, nullable=False),
        Column("ref_allele", Text, nullable=False),
        Column("alt_allele", Text, nullable=False),
        Column("variant_type", Text, nullable=False),
        *[Column(name, Text, nullable=False, server_default="") for name in (
            "variant_subtype", "gene_id", "gene_symbol", "mutant_line_name", "consequence",
            "impact", "rs_id", "hgvs_c", "hgvs_p",
        )],
        *[Column(name, BigInteger, nullable=False, server_default="0") for name in (
            "length", "gene_surrogate_id", "mutant_line_surrogate_id", "read_depth",
        )],
        Column("consequence_id", Integer, nullable=False, server_default="0"),
        Column("quality_score", Double, nullable=False, server_default="0"),
        Column("filter_status", Text, nullable=False, server_default="PASS"),
        Column("allele_frequency", Double, nullable=False, server_default="0"),
        Column("zygosity", Text, nullable=False, server_default="unknown"),
    ]


def _fact_constraints() -> list[CheckConstraint]:
    return [CheckConstraint(expression) for expression in (
        "position > 0", "length >= 0", "read_depth >= 0",
        "allele_frequency >= 0 AND allele_frequency <= 1",
        "variant_id >= 0 AND variant_id <= 18446744073709551615",
    )]


variant_facts = Table(
    "variant_facts", Base.metadata, *_fact_columns(), *_fact_constraints(),
    PrimaryKeyConstraint("release_id", "assembly_id", "variant_id"),
    UniqueConstraint("release_id", "variant_id", name="uq_variant_facts_release_identity"),
    Index("ix_variant_facts_page", "release_id", "position", "variant_id"),
    Index("ix_variant_facts_assembly_page", "release_id", "assembly_key", "position", "variant_id"),
    Index("ix_variant_facts_region", "release_id", "assembly_key", "chromosome",
          "position", "variant_id"),
    Index("ix_variant_facts_gene", "release_id", "assembly_key", "gene_id",
          "position", "variant_id"),
    Index("ix_variant_facts_mutant", "release_id", "mutant_line_surrogate_id",
          "assembly_key", "position", "variant_id"),
)
variant_facts_staging = Table(
    "variant_facts_staging", Base.metadata, *_fact_columns(), *_fact_constraints(),
    Column("import_id", String(128), nullable=False),
    Column("batch_id", String(64), nullable=False),
    PrimaryKeyConstraint("import_id", "assembly_id", "variant_id"),
)

native_variant_backfills = Table(
    "native_variant_backfills", Base.metadata,
    Column("release_id", Integer, ForeignKey("releases.id", ondelete="CASCADE"),
           primary_key=True),
    Column("source_version", Text, nullable=False),
    Column("source_count", BigInteger, nullable=False),
    Column("payload_sha256", String(64), nullable=False),
    Column("assembly_map", JSONB, nullable=False),
    Column("verified_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("source_count >= 0"),
    CheckConstraint("length(payload_sha256) = 64"),
)

analytics_events = Table(
    "analytics_events", Base.metadata,
    Column("event_pk", BigInteger, Identity(always=True), primary_key=True),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("session_id", UUID(as_uuid=True), nullable=False),
    Column("event_type", String(32), nullable=False),
    Column("page", String(512), nullable=False),
    Column("path", String(512), nullable=False),
    Column("source", String(64), nullable=False, server_default=""),
    Column("referrer", String(256), nullable=False, server_default=""),
    Column("duration_ms", Double, nullable=False, server_default="0"),
    CheckConstraint("duration_ms >= 0"),
    Index("ix_analytics_events_time", "timestamp"),
)

web_vitals = Table(
    "web_vitals", Base.metadata,
    Column("vital_pk", BigInteger, Identity(always=True), primary_key=True),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("session_id", UUID(as_uuid=True), nullable=False),
    Column("metric_name", String(16), nullable=False),
    Column("value", Double, nullable=False),
    Column("rating", String(32), nullable=False),
    Column("path", String(512), nullable=False),
    CheckConstraint("value >= 0 AND value < 'Infinity'::float8"),
    Index("ix_web_vitals_time", "timestamp"),
)
