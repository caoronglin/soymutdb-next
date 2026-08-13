CREATE TABLE IF NOT EXISTS variant_facts (
    release_id UInt16,
    assembly_id UInt16,
    chromosome LowCardinality(String),
    position UInt64,
    ref String,
    alt String,
    variant_type LowCardinality(String),
    gene_id String,
    transcript_id String,
    consequence LowCardinality(String),
    impact LowCardinality(String),
    mutant_line_id UInt32,
    mutant_line_name String,
    qual Float32,
    filter LowCardinality(String),
    dp UInt32,
    af Float32,
    annotations String,
    variant_id UInt64
) ENGINE = MergeTree()
PARTITION BY (release_id, chromosome)
ORDER BY (release_id, assembly_id, chromosome, position, variant_id);

INSERT INTO variant_facts VALUES
    (1, 101, 'Chr01', 1001, 'A', 'G', 'SNP', 'Glyma.01G000100', 'Glyma.01G000100.1', 'missense_variant', 'MODERATE', 7, 'Wm82', 99.5, 'PASS', 42, 0.25, '{}', 1000001),
    (1, 101, 'Chr02', 2050, 'C', 'T', 'SNP', 'Glyma.02G000200', 'Glyma.02G000200.1', 'synonymous_variant', 'LOW', 7, 'Wm82', 88.0, 'PASS', 31, 0.50, '{}', 1000002),
    (2, 102, 'Chr03', 3099, 'AT', 'A', 'INDEL', 'Glyma.03G000300', 'Glyma.03G000300.1', ' frameshift_variant', 'HIGH', 9, 'Williams82', 77.25, 'PASS', 19, 0.125, '{}', 2000001);
