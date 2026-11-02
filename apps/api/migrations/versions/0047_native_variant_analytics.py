"""Native PostgreSQL variant facts, import staging and anonymous telemetry.

No existing data is removed or re-keyed. Cutover follows a verified backfill.
NUMERIC(20,0) preserves the full existing unsigned 64-bit variant identifier.
Release and assembly identities are mandatory foreign keys. Range and entity
indexes start with release identity, matching the public visibility boundary.
"""

from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


FACT_COLUMNS = """
    release_id INTEGER NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    assembly_id INTEGER NOT NULL REFERENCES assemblies(id) ON DELETE RESTRICT,
    variant_id NUMERIC(20,0) NOT NULL,
    assembly_key TEXT NOT NULL,
    chromosome TEXT NOT NULL,
    position BIGINT NOT NULL CHECK (position > 0),
    ref_allele TEXT NOT NULL,
    alt_allele TEXT NOT NULL,
    variant_type TEXT NOT NULL,
    variant_subtype TEXT NOT NULL DEFAULT '',
    length BIGINT NOT NULL DEFAULT 0 CHECK (length >= 0),
    gene_id TEXT NOT NULL DEFAULT '',
    gene_symbol TEXT NOT NULL DEFAULT '',
    gene_surrogate_id BIGINT NOT NULL DEFAULT 0,
    mutant_line_surrogate_id BIGINT NOT NULL DEFAULT 0,
    mutant_line_name TEXT NOT NULL DEFAULT '',
    consequence TEXT NOT NULL DEFAULT '',
    consequence_id INTEGER NOT NULL DEFAULT 0,
    impact TEXT NOT NULL DEFAULT '',
    rs_id TEXT NOT NULL DEFAULT '',
    quality_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    filter_status TEXT NOT NULL DEFAULT 'PASS',
    read_depth BIGINT NOT NULL DEFAULT 0 CHECK (read_depth >= 0),
    allele_frequency DOUBLE PRECISION NOT NULL DEFAULT 0
        CHECK (allele_frequency >= 0 AND allele_frequency <= 1),
    hgvs_c TEXT NOT NULL DEFAULT '',
    hgvs_p TEXT NOT NULL DEFAULT '',
    zygosity TEXT NOT NULL DEFAULT 'unknown',
    CHECK (variant_id >= 0 AND variant_id <= 18446744073709551615)
"""


def upgrade() -> None:
    op.execute(
        "CREATE TABLE variant_facts (" + FACT_COLUMNS
        + ", PRIMARY KEY (release_id, assembly_id, variant_id), "
        "CONSTRAINT uq_variant_facts_release_identity UNIQUE (release_id, variant_id))"
    )
    op.execute(
        "CREATE INDEX ix_variant_facts_page ON variant_facts "
        "(release_id, position, variant_id)"
    )
    op.execute(
        "CREATE INDEX ix_variant_facts_assembly_page ON variant_facts "
        "(release_id, assembly_key, position, variant_id)"
    )
    op.execute(
        "CREATE INDEX ix_variant_facts_region ON variant_facts "
        "(release_id, assembly_key, chromosome, position, variant_id)"
    )
    op.execute(
        "CREATE INDEX ix_variant_facts_gene ON variant_facts "
        "(release_id, assembly_key, gene_id, position, variant_id)"
    )
    op.execute(
        "CREATE INDEX ix_variant_facts_mutant ON variant_facts "
        "(release_id, mutant_line_surrogate_id, assembly_key, position, variant_id)"
    )
    op.execute(
        "CREATE TABLE variant_facts_staging (" + FACT_COLUMNS
        + ", import_id VARCHAR(128) NOT NULL, batch_id VARCHAR(64) NOT NULL, "
        "PRIMARY KEY (import_id, assembly_id, variant_id))"
    )
    op.execute(
        "CREATE TABLE native_variant_backfills ("
        "release_id INTEGER PRIMARY KEY REFERENCES releases(id) ON DELETE CASCADE, "
        "source_version TEXT NOT NULL, source_count BIGINT NOT NULL CHECK (source_count >= 0), "
        "payload_sha256 VARCHAR(64) NOT NULL CHECK (length(payload_sha256) = 64), "
        "assembly_map JSONB NOT NULL, verified_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    op.execute(
        "CREATE TABLE analytics_events ("
        "event_pk BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
        "timestamp TIMESTAMPTZ NOT NULL, session_id UUID NOT NULL, "
        "event_type VARCHAR(32) NOT NULL, page VARCHAR(512) NOT NULL, "
        "path VARCHAR(512) NOT NULL, source VARCHAR(64) NOT NULL DEFAULT '', "
        "referrer VARCHAR(256) NOT NULL DEFAULT '', "
        "duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (duration_ms >= 0))"
    )
    op.execute("CREATE INDEX ix_analytics_events_time ON analytics_events (timestamp)")
    op.execute(
        "CREATE TABLE web_vitals ("
        "vital_pk BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
        "timestamp TIMESTAMPTZ NOT NULL, session_id UUID NOT NULL, "
        "metric_name VARCHAR(16) NOT NULL, value DOUBLE PRECISION NOT NULL "
        "CHECK (value >= 0 AND value < 'Infinity'::float8), "
        "rating VARCHAR(32) NOT NULL, path VARCHAR(512) NOT NULL)"
    )
    op.execute("CREATE INDEX ix_web_vitals_time ON web_vitals (timestamp)")


def downgrade() -> None:
    for table in (
        "web_vitals", "analytics_events", "native_variant_backfills",
        "variant_facts_staging", "variant_facts",
    ):
        op.execute("DROP TABLE " + table)
