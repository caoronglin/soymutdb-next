-- Faithful test slice of the canonical ClickHouse schema (infra/clickhouse/init.sql)
-- used to accept the import staging/verify/finalize protocol on a real engine
-- (chdb). Kept as .sql so the long DDL lines are not linted as Python and so
-- the structure mirrors production. Tables are created into whatever database
-- the session has selected.

CREATE TABLE variant_facts (
    variant_id UInt64, release_key String, assembly_key String,
    chromosome LowCardinality(String), position UInt64, ref_allele String,
    alt_allele String, variant_type LowCardinality(String),
    variant_subtype LowCardinality(String) DEFAULT '', length UInt32 DEFAULT 0,
    gene_id LowCardinality(String), gene_symbol LowCardinality(String) DEFAULT '',
    gene_surrogate_id UInt32 DEFAULT 0, mutant_line_surrogate_id UInt32 DEFAULT 0,
    mutant_line_name LowCardinality(String) DEFAULT '', consequence LowCardinality(String),
    consequence_id UInt32 DEFAULT 0, impact LowCardinality(String),
    rs_id String DEFAULT '', quality_score Float32 DEFAULT 0,
    filter_status LowCardinality(String) DEFAULT 'PASS', read_depth UInt32 DEFAULT 0,
    allele_frequency Float32 DEFAULT 0, hgvs_c String DEFAULT '', hgvs_p String DEFAULT '',
    zygosity LowCardinality(String) DEFAULT 'unknown'
) ENGINE=MergeTree()
PARTITION BY (release_key, chromosome)
ORDER BY (release_key, assembly_key, chromosome, position, gene_surrogate_id, mutant_line_surrogate_id, variant_id);

CREATE TABLE variant_facts_staging (
    variant_id UInt64, release_key String, assembly_key String,
    chromosome LowCardinality(String), position UInt64, ref_allele String,
    alt_allele String, variant_type LowCardinality(String),
    variant_subtype LowCardinality(String) DEFAULT '', length UInt32 DEFAULT 0,
    gene_id LowCardinality(String), gene_symbol LowCardinality(String) DEFAULT '',
    gene_surrogate_id UInt32 DEFAULT 0, mutant_line_surrogate_id UInt32 DEFAULT 0,
    mutant_line_name LowCardinality(String) DEFAULT '', consequence LowCardinality(String),
    consequence_id UInt32 DEFAULT 0, impact LowCardinality(String),
    rs_id String DEFAULT '', quality_score Float32 DEFAULT 0,
    filter_status LowCardinality(String) DEFAULT 'PASS', read_depth UInt32 DEFAULT 0,
    allele_frequency Float32 DEFAULT 0, hgvs_c String DEFAULT '', hgvs_p String DEFAULT '',
    zygosity LowCardinality(String) DEFAULT 'unknown',
    import_id String, batch_id String
) ENGINE=MergeTree()
PARTITION BY (release_key, chromosome)
ORDER BY (release_key, chromosome, position, variant_id);

CREATE TABLE gene_impact_summary (
    gene_surrogate_id UInt32, impact LowCardinality(String),
    consequence LowCardinality(String), variant_type LowCardinality(String),
    release_key String, cnt UInt64
) ENGINE=SummingMergeTree(cnt)
ORDER BY (gene_surrogate_id, impact, consequence, variant_type, release_key);

CREATE MATERIALIZED VIEW mv_gene_impact TO gene_impact_summary AS
SELECT gene_surrogate_id, impact, consequence, variant_type, release_key, count() AS cnt
FROM variant_facts
GROUP BY gene_surrogate_id, impact, consequence, variant_type, release_key;

CREATE TABLE chromosome_summary (
    release_key String, chromosome LowCardinality(String),
    variant_type LowCardinality(String),
    cnt SimpleAggregateFunction(sum, UInt64),
    min_pos SimpleAggregateFunction(min, UInt64),
    max_pos SimpleAggregateFunction(max, UInt64)
) ENGINE=AggregatingMergeTree()
ORDER BY (release_key, chromosome, variant_type);

CREATE MATERIALIZED VIEW mv_chromosome_summary TO chromosome_summary AS
SELECT release_key, chromosome, variant_type, count() AS cnt,
    min(position) AS min_pos, max(position) AS max_pos
FROM variant_facts
GROUP BY release_key, chromosome, variant_type;

CREATE TABLE mutant_line_summary (
    mutant_line_surrogate_id UInt32, mutant_line_name LowCardinality(String),
    chromosome LowCardinality(String), variant_type LowCardinality(String),
    impact LowCardinality(String), release_key String, cnt UInt64
) ENGINE=SummingMergeTree(cnt)
ORDER BY (mutant_line_surrogate_id, mutant_line_name, chromosome, variant_type, impact, release_key);

CREATE MATERIALIZED VIEW mv_mutant_line_summary TO mutant_line_summary AS
SELECT mutant_line_surrogate_id, mutant_line_name, chromosome, variant_type, impact,
    release_key, count() AS cnt
FROM variant_facts
GROUP BY mutant_line_surrogate_id, mutant_line_name, chromosome, variant_type, impact, release_key;

CREATE TABLE release_dashboard (
    release_key String, variant_type LowCardinality(String),
    impact LowCardinality(String), consequence LowCardinality(String), cnt UInt64
) ENGINE=SummingMergeTree(cnt)
ORDER BY (release_key, variant_type, impact, consequence);

CREATE MATERIALIZED VIEW mv_release_dashboard TO release_dashboard AS
SELECT release_key, variant_type, impact, consequence, count() AS cnt
FROM variant_facts
GROUP BY release_key, variant_type, impact, consequence;

CREATE TABLE density_10kb (
    release_key String, chromosome LowCardinality(String), bin_start UInt64, cnt UInt64
) ENGINE=SummingMergeTree(cnt) ORDER BY (release_key, chromosome, bin_start);

CREATE MATERIALIZED VIEW mv_density_10kb TO density_10kb AS
SELECT release_key, chromosome, intDiv(position, 10000) * 10000 AS bin_start, count() AS cnt
FROM variant_facts
GROUP BY release_key, chromosome, bin_start;

CREATE TABLE density_100kb (
    release_key String, chromosome LowCardinality(String), bin_start UInt64, cnt UInt64
) ENGINE=SummingMergeTree(cnt) ORDER BY (release_key, chromosome, bin_start);

CREATE MATERIALIZED VIEW mv_density_100kb TO density_100kb AS
SELECT release_key, chromosome, intDiv(position, 100000) * 100000 AS bin_start, count() AS cnt
FROM variant_facts
GROUP BY release_key, chromosome, bin_start;

CREATE TABLE density_1mb (
    release_key String, chromosome LowCardinality(String), bin_start UInt64, cnt UInt64
) ENGINE=SummingMergeTree(cnt) ORDER BY (release_key, chromosome, bin_start);

CREATE MATERIALIZED VIEW mv_density_1mb TO density_1mb AS
SELECT release_key, chromosome, intDiv(position, 1000000) * 1000000 AS bin_start, count() AS cnt
FROM variant_facts
GROUP BY release_key, chromosome, bin_start;

CREATE TABLE substitution_spectrum (
    release_key String, mutant_line_surrogate_id UInt32,
    ref_base LowCardinality(String), alt_base LowCardinality(String), cnt UInt64
) ENGINE=SummingMergeTree(cnt)
ORDER BY (release_key, mutant_line_surrogate_id, ref_base, alt_base);

CREATE MATERIALIZED VIEW mv_substitution_spectrum TO substitution_spectrum AS
SELECT release_key, mutant_line_surrogate_id, ref_allele AS ref_base, alt_allele AS alt_base, count() AS cnt
FROM variant_facts
WHERE variant_type = 'SNP' AND length(ref_allele) = 1 AND length(alt_allele) = 1
GROUP BY release_key, mutant_line_surrogate_id, ref_base, alt_base;
