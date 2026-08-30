# Slow-query baseline log

Weekly pg_stat_statements Top-20 exports. Query samples are normalized and capped.

> The committed entries below validate the collection path on the Mamba PostgreSQL test workload. They are not production SLO targets or evidence for production index decisions; append a production snapshot after a representative observation window.

## Operator procedure

1. Restart PostgreSQL with `shared_preload_libraries=pg_stat_statements` before applying Alembic revision `0025`; the Compose service does this by default.
2. After a representative observation window, run `make slow-query-report`. The report is scoped to the selected `POSTGRES_DB`, records the statistics reset timestamp, and never resets shared statistics.
3. Treat query IDs and normalized samples as investigation aids. Review a production snapshot before choosing an index or changing a query.

## 2026-08-29 · extension smoke test

| total ms | calls | mean ms | % | query sample |
| ---: | ---: | ---: | ---: | --- |
| 1.4 | 3 | 0.47 | 2.3 | `SELECT generate_series($1, $2)` |
| 0.0 | 1 | 0.01 | 0.0 | `SELECT pg_catalog.set_config($1, $2, $3)` |
| 0.0 | 1 | 0.01 | 0.0 | `SHOW shared_preload_libraries` |

## 2026-08-29 · 250k-row fixture and migration workload

| total ms | calls | mean ms | % | query sample |
| ---: | ---: | ---: | ---: | --- |
| 1066.0 | 1 | 1065.97 | 8.3 | `WITH assembly AS ( INSERT INTO assemblies (name, species, version, is_default, created_at, updated_at) VALUES ($1, $2, $3, $4, now(), now()) RETURNING id ), chromosome AS ( INSERT INTO chromosomes (assembly_id, name, length, "order") SELECT` |
| 171.7 | 3 | 57.22 | 1.3 | `ANALYZE genes` |
| 72.2 | 2 | 36.08 | 0.6 | `CREATE DATABASE soymutdb_testfixtures` |
| 47.0 | 2 | 23.52 | 0.4 | `DROP DATABASE IF EXISTS soymutdb_testfixtures` |
| 37.2 | 1 | 37.22 | 0.3 | `CREATE DATABASE soymutdb_performance` |
| 23.6 | 1 | 23.55 | 0.2 | `ALTER TABLE analysis_jobs ALTER COLUMN analysis_type TYPE analysis_type_enum USING lower(analysis_type::text)::analysis_type_enum` |
| 17.6 | 3 | 5.88 | 0.1 | `EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT id FROM genes WHERE description ILIKE $1` |
| 14.3 | 1 | 14.29 | 0.1 | `ALTER TABLE analysis_jobs ALTER COLUMN status TYPE analysis_job_status_enum USING lower(status::text)::analysis_job_status_enum` |
| 4.9 | 1 | 4.88 | 0.0 | `CREATE TABLE media_assets ( id UUID DEFAULT gen_random_uuid() NOT NULL, object_key VARCHAR(1024) NOT NULL, public_url VARCHAR(2048) NOT NULL, original_filename VARCHAR(512) NOT NULL, purpose VARCHAR(32) NOT NULL, content_type VARCHAR(128) N` |
| 4.8 | 1 | 4.83 | 0.0 | `ALTER TABLE outbox_events ALTER COLUMN status TYPE outbox_event_status_enum USING status::text::outbox_event_status_enum` |
| 4.7 | 1 | 4.70 | 0.0 | `CREATE TABLE seed_request_contacts ( id UUID DEFAULT gen_random_uuid() NOT NULL, name VARCHAR(256) NOT NULL, email VARCHAR(320) NOT NULL, institution VARCHAR(512) NOT NULL, country VARCHAR(128) NOT NULL, gene_ids JSONB DEFAULT '[]' NOT NULL` |
| 4.5 | 1 | 4.50 | 0.0 | `CREATE INDEX ix_gene_assembly_chr ON genes (assembly_id, chromosome_id)` |
| 4.5 | 1 | 4.49 | 0.0 | `CREATE TABLE blast_databases ( id SERIAL NOT NULL, name VARCHAR(256) NOT NULL, db_type blast_db_type_enum NOT NULL, assembly_id INTEGER NOT NULL, file_path VARCHAR(2048) NOT NULL, is_active BOOLEAN DEFAULT 'true' NOT NULL, created_at TIMEST` |
| 4.4 | 1 | 4.36 | 0.0 | `CREATE TABLE widgets ( id SERIAL NOT NULL, name VARCHAR(128) NOT NULL, display_name VARCHAR(256) NOT NULL, description TEXT, category widget_category_enum DEFAULT 'custom' NOT NULL, template_path VARCHAR(512) NOT NULL, data_source VARCHAR(2` |
| 4.3 | 1 | 4.32 | 0.0 | `CREATE TABLE tracks ( id SERIAL NOT NULL, name VARCHAR(255) NOT NULL, description TEXT, track_type VARCHAR(50) NOT NULL, track_subtype VARCHAR(50), visibility VARCHAR(20) DEFAULT 'public' NOT NULL, assembly_id INTEGER NOT NULL, release_id I` |
| 4.3 | 2 | 2.15 | 0.0 | `CREATE EXTENSION IF NOT EXISTS pg_trgm` |
| 4.3 | 1 | 4.28 | 0.0 | `CREATE TABLE publications ( id SERIAL NOT NULL, title VARCHAR(1024) NOT NULL, title_zh TEXT, authors TEXT NOT NULL, authors_zh TEXT, journal VARCHAR(256), year INTEGER, doi VARCHAR(256), pmid VARCHAR(32), abstract TEXT, abstract_zh TEXT, is` |
| 4.2 | 1 | 4.24 | 0.0 | `CREATE TABLE outbox_events ( id SERIAL NOT NULL, event_id UUID DEFAULT gen_random_uuid() NOT NULL, aggregate_type VARCHAR(64) NOT NULL, aggregate_id VARCHAR(64) NOT NULL, event_type VARCHAR(64) NOT NULL, payload JSONB NOT NULL, status outbo` |
| 4.2 | 1 | 4.17 | 0.0 | `CREATE TABLE publications ( id SERIAL NOT NULL, title VARCHAR(1024) NOT NULL, title_zh TEXT, authors TEXT NOT NULL, authors_zh TEXT, journal VARCHAR(256), year INTEGER, doi VARCHAR(256), pmid VARCHAR(32), abstract TEXT, abstract_zh TEXT, is` |
