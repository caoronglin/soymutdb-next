-- ============================================================
-- SoyMutDB ClickHouse DDL
-- Optimised for hundreds of millions of variant records.
--
-- Structure:
--   - 4 dimension tables (release_dim, gene_dim, mutant_line_dim, consequence_dim)
--   - 1 primary fact table (variant_facts) with 4 projections
--   - 8 materialized views (gene_impact, chromosome, mutant_line,
--     release_dashboard, density_10kb/100kb/1mb, substitution_spectrum)
-- ============================================================

CREATE DATABASE IF NOT EXISTS soymutdb;
USE soymutdb;

-- ----------------------------------------------------------
-- 1. Dimension tables
-- ----------------------------------------------------------

-- 1a. Release dimension
CREATE TABLE IF NOT EXISTS release_dim (
    release_id    UInt16,
    release_name  LowCardinality(String),
    release_date  Date,
    assembly      LowCardinality(String),
    description   String DEFAULT '',
    record_count  UInt64 DEFAULT 0,
    is_current    UInt8 DEFAULT 0
) ENGINE = ReplacingMergeTree(is_current)
ORDER BY (release_id);

-- 1b. Gene dimension
CREATE TABLE IF NOT EXISTS gene_dim (
    gene_id         LowCardinality(String),
    gene_surrogate_id UInt32 DEFAULT 0,
    release_key     String DEFAULT '',
    gene_symbol     LowCardinality(String),
    gene_name       LowCardinality(String) DEFAULT '',
    chromosome      LowCardinality(String),
    start_pos       UInt64,
    end_pos         UInt64,
    strand          LowCardinality(String),
    biotype         LowCardinality(String),
    description     String DEFAULT '',
    gene_family     LowCardinality(String) DEFAULT ''
) ENGINE = ReplacingMergeTree()
ORDER BY (gene_id);

-- 1c. Mutant line dimension
CREATE TABLE IF NOT EXISTS mutant_line_dim (
    mutant_line_id   UInt32,
    mutant_line_name LowCardinality(String),
    mutagen          LowCardinality(String),   -- EMS, gamma, fast-neutron, CRISPR
    background       LowCardinality(String),   -- Williams 82, Jack, etc.
    generation       LowCardinality(String),   -- M2, M3, M4
    source           LowCardinality(String),
    description      String DEFAULT ''
) ENGINE = ReplacingMergeTree()
ORDER BY (mutant_line_id);

-- 1d. Consequence dimension
CREATE TABLE IF NOT EXISTS consequence_dim (
    consequence      LowCardinality(String),
    impact           LowCardinality(String),   -- HIGH, MODERATE, LOW, MODIFIER
    category         LowCardinality(String),   -- coding, non-coding, regulatory
    description      String DEFAULT '',
    is_protein_affecting UInt8 DEFAULT 0
) ENGINE = ReplacingMergeTree()
ORDER BY (consequence, impact);

-- ----------------------------------------------------------
-- 2. Primary fact table
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS variant_facts (
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
    impact           LowCardinality(String),   -- HIGH, MODERATE, LOW, MODIFIER
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

-- ----------------------------------------------------------
-- 3. Projections (query-time index alternatives)
-- ----------------------------------------------------------

ALTER TABLE variant_facts ADD PROJECTION IF NOT EXISTS prj_by_gene (
    SELECT *
    ORDER BY (gene_surrogate_id, consequence, impact, release_key, chromosome, position)
);

ALTER TABLE variant_facts ADD PROJECTION IF NOT EXISTS prj_by_mutant_line (
    SELECT *
    ORDER BY (mutant_line_surrogate_id, chromosome, position, release_key)
);

ALTER TABLE variant_facts ADD PROJECTION IF NOT EXISTS prj_by_consequence (
    SELECT *
    ORDER BY (consequence, impact, chromosome, position, release_key)
);

ALTER TABLE variant_facts ADD PROJECTION IF NOT EXISTS prj_by_region (
    SELECT *
    ORDER BY (chromosome, position, release_key)
);

-- Materialize existing data into projections (run once after bulk load)
-- ALTER TABLE variant_facts MATERIALIZE PROJECTION prj_by_gene;
-- ALTER TABLE variant_facts MATERIALIZE PROJECTION prj_by_mutant_line;
-- ALTER TABLE variant_facts MATERIALIZE PROJECTION prj_by_consequence;
-- ALTER TABLE variant_facts MATERIALIZE PROJECTION prj_by_region;

-- ----------------------------------------------------------
-- 4. Materialized summary tables (8 views)
-- ----------------------------------------------------------

-- 4a. Gene-impact summary (SummingMergeTree)
CREATE TABLE IF NOT EXISTS gene_impact_summary (
    gene_surrogate_id UInt32,
    impact           LowCardinality(String),
    consequence      LowCardinality(String),
    variant_type     LowCardinality(String),
    release_key      String,
    cnt              UInt64
) ENGINE = SummingMergeTree((cnt))
ORDER BY (gene_surrogate_id, impact, consequence, variant_type, release_key);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_gene_impact TO gene_impact_summary AS
SELECT
    gene_surrogate_id,
    impact,
    consequence,
    variant_type,
    release_key,
    count() AS cnt
FROM variant_facts
GROUP BY gene_surrogate_id, impact, consequence, variant_type, release_key;

-- 4b. Chromosome summary (AggregatingMergeTree)
CREATE TABLE IF NOT EXISTS chromosome_summary (
    release_key  String,
    chromosome   LowCardinality(String),
    variant_type LowCardinality(String),
    cnt          SimpleAggregateFunction(sum, UInt64),
    min_pos      SimpleAggregateFunction(min, UInt64),
    max_pos      SimpleAggregateFunction(max, UInt64)
) ENGINE = AggregatingMergeTree()
ORDER BY (release_key, chromosome, variant_type);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_chromosome_summary TO chromosome_summary AS
SELECT
    release_key,
    chromosome,
    variant_type,
    count()       AS cnt,
    min(position) AS min_pos,
    max(position) AS max_pos
FROM variant_facts
GROUP BY release_key, chromosome, variant_type;

-- 4c. Mutant-line summary (SummingMergeTree)
CREATE TABLE IF NOT EXISTS mutant_line_summary (
    mutant_line_surrogate_id UInt32,
    mutant_line_name LowCardinality(String),
    chromosome       LowCardinality(String),
    variant_type     LowCardinality(String),
    impact           LowCardinality(String),
    release_key      String,
    cnt              UInt64
) ENGINE = SummingMergeTree((cnt))
ORDER BY (mutant_line_surrogate_id, mutant_line_name, chromosome, variant_type, impact, release_key);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_mutant_line_summary TO mutant_line_summary AS
SELECT
    mutant_line_surrogate_id,
    mutant_line_name,
    chromosome,
    variant_type,
    impact,
    release_key,
    count() AS cnt
FROM variant_facts
GROUP BY mutant_line_surrogate_id, mutant_line_name, chromosome, variant_type, impact, release_key;

-- 4d. Release dashboard (SummingMergeTree)
CREATE TABLE IF NOT EXISTS release_dashboard (
    release_key  String,
    variant_type LowCardinality(String),
    impact       LowCardinality(String),
    consequence  LowCardinality(String),
    cnt          UInt64
) ENGINE = SummingMergeTree((cnt))
ORDER BY (release_key, variant_type, impact, consequence);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_release_dashboard TO release_dashboard AS
SELECT
    release_key,
    variant_type,
    impact,
    consequence,
    count() AS cnt
FROM variant_facts
GROUP BY release_key, variant_type, impact, consequence;

-- 4e. Density 10 kb (SummingMergeTree)
CREATE TABLE IF NOT EXISTS density_10kb (
    release_key String,
    chromosome  LowCardinality(String),
    bin_start   UInt64,
    cnt         UInt64
) ENGINE = SummingMergeTree((cnt))
ORDER BY (release_key, chromosome, bin_start);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_density_10kb TO density_10kb AS
SELECT
    release_key,
    chromosome,
    intDiv(position, 10000) * 10000 AS bin_start,
    count()                         AS cnt
FROM variant_facts
GROUP BY release_key, chromosome, bin_start;

-- 4f. Density 100 kb (SummingMergeTree)
CREATE TABLE IF NOT EXISTS density_100kb (
    release_key String,
    chromosome  LowCardinality(String),
    bin_start   UInt64,
    cnt         UInt64
) ENGINE = SummingMergeTree((cnt))
ORDER BY (release_key, chromosome, bin_start);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_density_100kb TO density_100kb AS
SELECT
    release_key,
    chromosome,
    intDiv(position, 100000) * 100000 AS bin_start,
    count()                            AS cnt
FROM variant_facts
GROUP BY release_key, chromosome, bin_start;

-- 4g. Density 1 Mb (SummingMergeTree)
CREATE TABLE IF NOT EXISTS density_1mb (
    release_key String,
    chromosome  LowCardinality(String),
    bin_start   UInt64,
    cnt         UInt64
) ENGINE = SummingMergeTree((cnt))
ORDER BY (release_key, chromosome, bin_start);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_density_1mb TO density_1mb AS
SELECT
    release_key,
    chromosome,
    intDiv(position, 1000000) * 1000000 AS bin_start,
    count()                              AS cnt
FROM variant_facts
GROUP BY release_key, chromosome, bin_start;

-- 4h. Substitution spectrum (ref->alt for SNPs)
CREATE TABLE IF NOT EXISTS substitution_spectrum (
    release_key      String,
    mutant_line_surrogate_id UInt32,
    ref_base         LowCardinality(String),
    alt_base         LowCardinality(String),
    cnt              UInt64
) ENGINE = SummingMergeTree((cnt))
ORDER BY (release_key, mutant_line_surrogate_id, ref_base, alt_base);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_substitution_spectrum TO substitution_spectrum AS
SELECT
    release_key,
    mutant_line_surrogate_id,
    ref_allele AS ref_base,
    alt_allele AS alt_base,
    count() AS cnt
FROM variant_facts
WHERE variant_type = 'SNP' AND length(ref_allele) = 1 AND length(alt_allele) = 1
GROUP BY release_key, mutant_line_surrogate_id, ref_base, alt_base;

-- ----------------------------------------------------------
-- 5. Seed dimension data (consequence types)
-- ----------------------------------------------------------

INSERT INTO consequence_dim (consequence, impact, category, description, is_protein_affecting) VALUES
    ('stop_gained',            'HIGH',     'coding',    'Stop codon gained',                     1),
    ('stop_lost',              'HIGH',     'coding',    'Stop codon lost',                       1),
    ('start_lost',             'HIGH',     'coding',    'Start codon lost',                      1),
    ('frameshift_variant',     'HIGH',     'coding',    'Frameshift variant',                    1),
    ('splice_acceptor_variant','HIGH',     'splicing',  'Splice acceptor variant',               1),
    ('splice_donor_variant',   'HIGH',     'splicing',  'Splice donor variant',                  1),
    ('missense_variant',       'MODERATE', 'coding',    'Missense variant (amino acid change)',  1),
    ('inframe_insertion',      'MODERATE', 'coding',    'In-frame insertion',                    1),
    ('inframe_deletion',       'MODERATE', 'coding',    'In-frame deletion',                     1),
    ('splice_region_variant',  'MODERATE', 'splicing',  'Splice region variant',                 1),
    ('synonymous_variant',     'LOW',      'coding',    'Synonymous variant (silent)',           0),
    ('missense_variant',       'MODERATE', 'coding',    'Missense variant',                      1),
    ('initiator_codon_variant','LOW',      'coding',    'Initiator codon variant',               1),
    ('stop_retained_variant',  'LOW',      'coding',    'Stop retained variant',                 0),
    ('intron_variant',         'MODIFIER', 'non-coding','Intron variant',                        0),
    ('intergenic_variant',     'MODIFIER', 'non-coding','Intergenic variant',                    0),
    ('upstream_gene_variant',  'MODIFIER', 'regulatory','Upstream gene variant',                 0),
    ('downstream_gene_variant','MODIFIER', 'regulatory','Downstream gene variant',               0),
    ('3_prime_UTR_variant',    'MODIFIER', 'non-coding','3 prime UTR variant',                   0),
    ('5_prime_UTR_variant',    'MODIFIER', 'non-coding','5 prime UTR variant',                   0),
    ('non_coding_transcript_variant','MODIFIER','non-coding','Non-coding transcript variant',   0);

-- ----------------------------------------------------------
-- 6. Analytics events table (for track.gif pixel)
-- ----------------------------------------------------------

CREATE TABLE IF NOT EXISTS analytics_events (
    timestamp      DateTime64(3, 'UTC'),
    session_id     String,
    event_type     LowCardinality(String),   -- pageview | click | search | widget
    page           String DEFAULT '',
    path           String DEFAULT '',
    widget_name    String DEFAULT '',
    search_query   String DEFAULT '',
    source         String DEFAULT '',
    referrer       String DEFAULT '',
    user_agent     String DEFAULT '',
    ip_hash        String DEFAULT '',        -- salted SHA-256; raw IP never stored
    duration_ms    UInt32 DEFAULT 0
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (timestamp, event_type, session_id)
TTL toDateTime(timestamp) + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;

-- ----------------------------------------------------------
-- 7. Web Vitals (sampled frontend performance telemetry)
-- ----------------------------------------------------------

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
