-- SoyMutDB ClickHouse migration. Execute in stage order from migrate-clickhouse.sh.
-- Derived summaries are intentionally rebuilt: backup/confirm they are reproducible first.
USE soymutdb;

-- ============================================================
-- STAGE 1: canonical replacement and legacy-to-canonical copy
-- ============================================================
CREATE TABLE IF NOT EXISTS variant_facts_new (
    variant_id       UInt64,
    release_key      String,
    assembly_key     String,
    chromosome       LowCardinality(String),
    position         UInt64,
    ref_allele       String,
    alt_allele       String,
    variant_type     LowCardinality(String),
    variant_subtype  LowCardinality(String) DEFAULT '',
    length           UInt32 DEFAULT 0,
    gene_id          LowCardinality(String),
    gene_symbol      LowCardinality(String) DEFAULT '',
    gene_surrogate_id UInt32 DEFAULT 0,
    mutant_line_surrogate_id UInt32 DEFAULT 0,
    mutant_line_name LowCardinality(String) DEFAULT '',
    consequence      LowCardinality(String),
    consequence_id   UInt32 DEFAULT 0,
    impact           LowCardinality(String),
    rs_id            String DEFAULT '',
    quality_score    Float32 DEFAULT 0,
    filter_status    LowCardinality(String) DEFAULT 'PASS',
    read_depth       UInt32 DEFAULT 0,
    allele_frequency Float32 DEFAULT 0,
    hgvs_c           String DEFAULT '',
    hgvs_p           String DEFAULT '',
    zygosity         LowCardinality(String) DEFAULT 'unknown'
) ENGINE = MergeTree()
PARTITION BY (release_key, chromosome)
ORDER BY (release_key, assembly_key, chromosome, position, gene_surrogate_id, mutant_line_surrogate_id, variant_id)
SETTINGS index_granularity = 8192;

ALTER TABLE variant_facts_new ADD PROJECTION IF NOT EXISTS prj_by_gene (
    SELECT * ORDER BY (gene_surrogate_id, consequence, impact, release_key, chromosome, position)
);
ALTER TABLE variant_facts_new ADD PROJECTION IF NOT EXISTS prj_by_mutant_line (
    SELECT * ORDER BY (mutant_line_surrogate_id, chromosome, position, release_key)
);
ALTER TABLE variant_facts_new ADD PROJECTION IF NOT EXISTS prj_by_consequence (
    SELECT * ORDER BY (consequence, impact, chromosome, position, release_key)
);
ALTER TABLE variant_facts_new ADD PROJECTION IF NOT EXISTS prj_by_region (
    SELECT * ORDER BY (chromosome, position, release_key)
);

-- transcript_id and annotations are deliberately dropped: canonical storage has
-- no transcript dimension; retain them in the source/archive if that dimension returns.
INSERT INTO variant_facts_new (
    variant_id, release_key, assembly_key, chromosome, position, ref_allele, alt_allele,
    variant_type, variant_subtype, length, gene_id, gene_symbol, gene_surrogate_id,
    mutant_line_surrogate_id, mutant_line_name, consequence, consequence_id, impact,
    rs_id, quality_score, filter_status, read_depth, allele_frequency, hgvs_c, hgvs_p, zygosity
)
SELECT
    variant_id, toString(release_id), toString(assembly_id), chromosome, position, ref, alt,
    variant_type, '', 0, gene_id, '', 0, mutant_line_id, mutant_line_name, consequence,
    0, impact, '', qual, filter, dp, af, '', '', 'unknown'
FROM variant_facts;

-- ============================================================
-- STAGE 1 GATE: compare counts and reject empty release keys
-- ============================================================
SELECT count() AS legacy_count FROM variant_facts;
SELECT count() AS replacement_count FROM variant_facts_new;
SELECT countIf(release_key = '') AS empty_release_keys FROM variant_facts_new;
SELECT countIf(variant_id = 0) AS zero_variant_ids FROM variant_facts_new;

-- ============================================================
-- STAGE 2: atomic switch; variant_facts_legacy is retained for rollback
-- ============================================================
RENAME TABLE variant_facts TO variant_facts_legacy, variant_facts_new TO variant_facts;

-- Summaries are derived data. DROP before CREATE makes a complete rerun safe and
-- prevents SummingMergeTree duplicate backfills from doubling counts.
DROP TABLE IF EXISTS mv_gene_impact;
DROP TABLE IF EXISTS mv_chromosome_summary;
DROP TABLE IF EXISTS mv_mutant_line_summary;
DROP TABLE IF EXISTS mv_release_dashboard;
DROP TABLE IF EXISTS mv_density_10kb;
DROP TABLE IF EXISTS mv_density_100kb;
DROP TABLE IF EXISTS mv_density_1mb;
DROP TABLE IF EXISTS mv_substitution_spectrum;
DROP TABLE IF EXISTS gene_impact_summary;
DROP TABLE IF EXISTS chromosome_summary;
DROP TABLE IF EXISTS mutant_line_summary;
DROP TABLE IF EXISTS release_dashboard;
DROP TABLE IF EXISTS density_10kb;
DROP TABLE IF EXISTS density_100kb;
DROP TABLE IF EXISTS density_1mb;
DROP TABLE IF EXISTS substitution_spectrum;

CREATE TABLE gene_impact_summary (gene_surrogate_id UInt32, impact LowCardinality(String), consequence LowCardinality(String), variant_type LowCardinality(String), release_key String, cnt UInt64) ENGINE = SummingMergeTree((cnt)) ORDER BY (gene_surrogate_id, impact, consequence, variant_type, release_key);
CREATE TABLE chromosome_summary (release_key String, chromosome LowCardinality(String), variant_type LowCardinality(String), cnt UInt64, min_pos SimpleAggregateFunction(min, UInt64), max_pos SimpleAggregateFunction(max, UInt64)) ENGINE = AggregatingMergeTree() ORDER BY (release_key, chromosome, variant_type);
CREATE TABLE mutant_line_summary (mutant_line_surrogate_id UInt32, mutant_line_name LowCardinality(String), chromosome LowCardinality(String), variant_type LowCardinality(String), impact LowCardinality(String), release_key String, cnt UInt64) ENGINE = SummingMergeTree((cnt)) ORDER BY (mutant_line_surrogate_id, mutant_line_name, chromosome, variant_type, impact, release_key);
CREATE TABLE release_dashboard (release_key String, variant_type LowCardinality(String), impact LowCardinality(String), consequence LowCardinality(String), cnt UInt64) ENGINE = SummingMergeTree((cnt)) ORDER BY (release_key, variant_type, impact, consequence);
CREATE TABLE density_10kb (release_key String, chromosome LowCardinality(String), bin_start UInt64, cnt UInt64) ENGINE = SummingMergeTree((cnt)) ORDER BY (release_key, chromosome, bin_start);
CREATE TABLE density_100kb (release_key String, chromosome LowCardinality(String), bin_start UInt64, cnt UInt64) ENGINE = SummingMergeTree((cnt)) ORDER BY (release_key, chromosome, bin_start);
CREATE TABLE density_1mb (release_key String, chromosome LowCardinality(String), bin_start UInt64, cnt UInt64) ENGINE = SummingMergeTree((cnt)) ORDER BY (release_key, chromosome, bin_start);
CREATE TABLE substitution_spectrum (release_key String, mutant_line_surrogate_id UInt32, ref_base LowCardinality(String), alt_base LowCardinality(String), cnt UInt64) ENGINE = SummingMergeTree((cnt)) ORDER BY (release_key, mutant_line_surrogate_id, ref_base, alt_base);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_gene_impact TO gene_impact_summary AS SELECT gene_surrogate_id, impact, consequence, variant_type, release_key, count() AS cnt FROM variant_facts GROUP BY gene_surrogate_id, impact, consequence, variant_type, release_key;
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_chromosome_summary TO chromosome_summary AS SELECT release_key, chromosome, variant_type, count() AS cnt, min(position) AS min_pos, max(position) AS max_pos FROM variant_facts GROUP BY release_key, chromosome, variant_type;
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_mutant_line_summary TO mutant_line_summary AS SELECT mutant_line_surrogate_id, mutant_line_name, chromosome, variant_type, impact, release_key, count() AS cnt FROM variant_facts GROUP BY mutant_line_surrogate_id, mutant_line_name, chromosome, variant_type, impact, release_key;
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_release_dashboard TO release_dashboard AS SELECT release_key, variant_type, impact, consequence, count() AS cnt FROM variant_facts GROUP BY release_key, variant_type, impact, consequence;
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_density_10kb TO density_10kb AS SELECT release_key, chromosome, intDiv(position, 10000) * 10000 AS bin_start, count() AS cnt FROM variant_facts GROUP BY release_key, chromosome, bin_start;
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_density_100kb TO density_100kb AS SELECT release_key, chromosome, intDiv(position, 100000) * 100000 AS bin_start, count() AS cnt FROM variant_facts GROUP BY release_key, chromosome, bin_start;
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_density_1mb TO density_1mb AS SELECT release_key, chromosome, intDiv(position, 1000000) * 1000000 AS bin_start, count() AS cnt FROM variant_facts GROUP BY release_key, chromosome, bin_start;
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_substitution_spectrum TO substitution_spectrum AS SELECT release_key, mutant_line_surrogate_id, ref_allele AS ref_base, alt_allele AS alt_base, count() AS cnt FROM variant_facts WHERE variant_type = 'SNP' AND length(ref_allele) = 1 AND length(alt_allele) = 1 GROUP BY release_key, mutant_line_surrogate_id, ref_base, alt_base;

-- Each summary is empty after DROP, so each backfill occurs exactly once.
INSERT INTO gene_impact_summary SELECT gene_surrogate_id, impact, consequence, variant_type, release_key, count() FROM variant_facts GROUP BY gene_surrogate_id, impact, consequence, variant_type, release_key;
INSERT INTO chromosome_summary SELECT release_key, chromosome, variant_type, count(), min(position), max(position) FROM variant_facts GROUP BY release_key, chromosome, variant_type;
INSERT INTO mutant_line_summary SELECT mutant_line_surrogate_id, mutant_line_name, chromosome, variant_type, impact, release_key, count() FROM variant_facts GROUP BY mutant_line_surrogate_id, mutant_line_name, chromosome, variant_type, impact, release_key;
INSERT INTO release_dashboard SELECT release_key, variant_type, impact, consequence, count() FROM variant_facts GROUP BY release_key, variant_type, impact, consequence;
INSERT INTO density_10kb SELECT release_key, chromosome, intDiv(position, 10000) * 10000 AS bin_start, count() FROM variant_facts GROUP BY release_key, chromosome, bin_start;
INSERT INTO density_100kb SELECT release_key, chromosome, intDiv(position, 100000) * 100000 AS bin_start, count() FROM variant_facts GROUP BY release_key, chromosome, bin_start;
INSERT INTO density_1mb SELECT release_key, chromosome, intDiv(position, 1000000) * 1000000 AS bin_start, count() FROM variant_facts GROUP BY release_key, chromosome, bin_start;
INSERT INTO substitution_spectrum SELECT release_key, mutant_line_surrogate_id, ref_allele, alt_allele, count() FROM variant_facts WHERE variant_type = 'SNP' AND length(ref_allele) = 1 AND length(alt_allele) = 1 GROUP BY release_key, mutant_line_surrogate_id, ref_allele, alt_allele;

-- ============================================================
-- STAGE 4: privacy-preserving operational analytics
-- ============================================================
-- These tables are additive and idempotent. Raw IPs are never stored; the API
-- writes a deployment-salted hash to ``ip_hash``.
CREATE TABLE IF NOT EXISTS analytics_events (
    timestamp      DateTime64(3, 'UTC'),
    session_id     String,
    event_type     LowCardinality(String),
    page           String DEFAULT '',
    path           String DEFAULT '',
    widget_name    String DEFAULT '',
    search_query   String DEFAULT '',
    source         String DEFAULT '',
    referrer       String DEFAULT '',
    user_agent     String DEFAULT '',
    ip_hash        String DEFAULT '',
    duration_ms    UInt32 DEFAULT 0
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (timestamp, event_type, session_id)
TTL toDateTime(timestamp) + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS web_vitals (
    timestamp      DateTime64(3, 'UTC'),
    session_id     String,
    metric_name    LowCardinality(String),
    value          Float64,
    rating         LowCardinality(String),
    path           String DEFAULT '',
    user_agent     String DEFAULT '',
    ip_hash        String DEFAULT ''
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (metric_name, toDate(timestamp), session_id)
TTL toDateTime(timestamp) + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;
