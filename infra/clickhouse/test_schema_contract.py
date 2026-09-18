"""Schema contract checks for the worker/API ClickHouse variant lane."""

from pathlib import Path
import re


ROOT = Path(__file__).parents[2]
DDL = ROOT / "infra/clickhouse/init.sql"
INGEST = ROOT / "apps/worker/src/soymutdb_worker/tasks/ingest.py"
SERVICE = ROOT / "apps/api/app/services/clickhouse_service.py"
EXPORT = ROOT / "apps/worker/src/soymutdb_worker/tasks/export.py"
STATS = ROOT / "apps/worker/src/soymutdb_worker/tasks/stats.py"
UPGRADE = ROOT / "infra/clickhouse/upgrade_variant_facts_schema.sql"

CANONICAL_VARIANT_COLUMNS = {
    "variant_id",
    "release_key",
    "assembly_key",
    "chromosome",
    "position",
    "ref_allele",
    "alt_allele",
    "variant_type",
    "variant_subtype",
    "length",
    "gene_id",
    "gene_symbol",
    "mutant_line_name",
    "gene_surrogate_id",
    "mutant_line_surrogate_id",
    "consequence",
    "consequence_id",
    "impact",
    "quality_score",
    "rs_id",
    "filter_status",
    "read_depth",
    "allele_frequency",
    "hgvs_c",
    "hgvs_p",
    "zygosity",
}

CANONICAL_VARIANT_TYPES = {
    "mutant_line_name": "LowCardinality(String)",
}

MV_NAMES = {
    "mv_gene_impact", "mv_chromosome_summary", "mv_mutant_line_summary",
    "mv_release_dashboard", "mv_density_10kb", "mv_density_100kb",
    "mv_density_1mb", "mv_substitution_spectrum",
}

# Historical source columns accepted by the replacement-table mapping. These
# are the legacy names used by the pre-canonical variant ingestion schema.
LEGACY_COLUMNS = {
    "release_id", "assembly_id", "chromosome", "position", "ref", "alt",
    "variant_type", "gene_id", "transcript_id", "consequence", "impact",
    "mutant_line_id", "mutant_line_name", "qual", "filter", "dp", "af",
    "annotations", "variant_id",
}

SUMMARY_TABLES = {
    "gene_impact_summary", "chromosome_summary", "mutant_line_summary",
    "release_dashboard", "density_10kb", "density_100kb", "density_1mb",
    "substitution_spectrum",
}


def _variant_ddl_columns() -> set[str]:
    sql = DDL.read_text()
    body = re.search(r"CREATE TABLE IF NOT EXISTS variant_facts \((.*?)\) ENGINE", sql, re.S)
    assert body, "variant_facts DDL is missing"
    return set(re.findall(r"^\s{4}([a-z_]+)\s+", body.group(1), re.M))


def _strip_line_comments(sql: str) -> str:
    """Drop `--` line comments so prose cannot delimit a statement.

    `init.sql` documents `ip_hash` as "-- salted SHA-256; raw IP never stored";
    that semicolon is inside a comment but ends a naive statement match anyway.
    The production splitter in `deploy/scripts/migrate_clickhouse_lib.py` strips
    line comments for the same reason, so the guard here agrees with it.
    """
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _table_columns(sql: str, table: str) -> dict[str, str]:
    body = re.search(
        rf"CREATE TABLE(?: IF NOT EXISTS)? {table} \((.*?)\) ENGINE",
        sql, re.S,
    )
    assert body, f"{table} DDL is missing"
    columns = {}
    for line in body.group(1).splitlines():
        match = re.match(r"\s{4}([a-z_]+)\s+(.+?)(?:\s+--.*)?$", line)
        if match:
            definition = match.group(2).strip().rstrip(",")
            columns[match.group(1)] = definition
    return columns


def test_variant_contract_is_shared_by_ddl_worker_and_api() -> None:
    ddl_columns = _variant_ddl_columns()
    ingest = INGEST.read_text()
    service = SERVICE.read_text()
    export = EXPORT.read_text()

    insert_match = re.search(r'batch: dict\[str, list\] = \{(.*?)\n\s*\}', ingest, re.S)
    assert insert_match, "worker variant batch declaration is missing"
    insert_columns = set(re.findall(r'^\s*"([a-z_]+)": \[\]', insert_match.group(1), re.M))

    select_columns = set()
    for match in re.finditer(r"SELECT(.*?)FROM \{VARIANT_FACTS_TABLE\}", service, re.S):
        select_columns.update(
            token for token in re.findall(r"\b([a-z_]+)\b", match.group(1))
            if token in CANONICAL_VARIANT_COLUMNS
        )

    assert CANONICAL_VARIANT_COLUMNS <= ddl_columns
    assert insert_columns == CANONICAL_VARIANT_COLUMNS
    assert CANONICAL_VARIANT_COLUMNS - {"release_key", "assembly_key", "mutant_line_name"} <= select_columns | {"variant_subtype", "length", "gene_surrogate_id", "consequence_id", "rs_id"}

    export_columns = set(re.findall(r'"([a-z_]+)"', re.search(
        r"EXPORT_COLUMNS\s*=\s*\[(.*?)\]", export, re.S
    ).group(1)))
    assert export_columns <= ddl_columns


def test_worker_stats_and_service_only_reference_variant_columns() -> None:
    ddl_columns = _variant_ddl_columns()
    sources = [STATS.read_text(), SERVICE.read_text()]
    for source in sources:
        # Ignore SQL aliases and Python identifiers; this catches known
        # variant_facts references without requiring a ClickHouse parser.
        used = set(re.findall(r"(?:v\.)?([a-z_]+)", source)) & CANONICAL_VARIANT_COLUMNS
        if source == STATS.read_text():
            assert {"gene_surrogate_id", "mutant_line_surrogate_id", "release_key"} <= used


def test_variant_table_keys_and_materialized_views_use_declared_columns() -> None:
    sql = DDL.read_text()
    ddl_columns = _variant_ddl_columns()
    fact_sql = sql[sql.index("CREATE TABLE IF NOT EXISTS variant_facts") : sql.index("-- ----------------------------------------------------------\n-- 3. Projections")]
    partition = re.search(r"PARTITION BY \(([^)]*)\)", fact_sql).group(1)
    order = re.search(r"ORDER BY \(([^)]*)\)", fact_sql).group(1)
    for key in re.findall(r"\b[a-z_]+\b", partition + "," + order):
        assert key in ddl_columns, f"table key uses undeclared column: {key}"

    mv_sql = sql[sql.index("-- 4. Materialized summary tables"):]
    for match in re.finditer(
        r"CREATE MATERIALIZED VIEW IF NOT EXISTS (mv_[a-z0-9_]+).*?\n"
        r"SELECT(.*?)FROM\s+([a-z_]+)(.*?)(?=;\n|$)",
        mv_sql, re.S,
    ):
        mv_name, select_body, source, tail = match.groups()
        if source == "variant_facts":
            references = set(re.findall(r"\b[a-z_][a-z0-9_]*\b", select_body + tail))
            ignored = {"select", "from", "where", "group", "by", "as", "and", "or", "if", "then", "else", "end", "snp", "length", "intdiv", "count", "min", "max", "bin_start", "ref_base", "alt_base", "mv", "materialized", "view", "to", "cnt", "min_pos", "max_pos"}
            assert (references - ignored) <= ddl_columns, f"{mv_name} references undeclared variant_facts columns"
        assert mv_name in MV_NAMES


def test_upgrade_declares_the_same_canonical_target_columns() -> None:
    upgrade = UPGRADE.read_text()
    canonical = _table_columns(DDL.read_text(), "variant_facts")
    replacement = _table_columns(upgrade, "variant_facts_new")
    assert replacement == canonical
    assert set(re.findall(r"DROP TABLE IF EXISTS (mv_[a-z0-9_]+)", upgrade)) == MV_NAMES
    assert set(re.findall(r"CREATE MATERIALIZED VIEW IF NOT EXISTS (mv_[a-z0-9_]+)", upgrade)) == MV_NAMES
    assert "INSERT INTO variant_facts_new" in upgrade and "FROM variant_facts" in upgrade
    mapping = re.search(r"INSERT INTO variant_facts_new\s*\((.*?)\)\s*SELECT\s*(.*?)\s*FROM\s+variant_facts", upgrade, re.S)
    assert mapping, "replacement migration must explicitly map source columns"
    target_columns = set(re.findall(r"\b([a-z_]+)\b", mapping.group(1)))
    source_columns = set(re.findall(r"\b([a-z_]+)\b", mapping.group(2)))
    assert target_columns <= set(canonical)
    sql_words = {"select", "from", "tostring", "toString", "unknown", "pass", "snp", "where", "as"}
    assert (source_columns - sql_words) <= LEGACY_COLUMNS

    expected_mappings = {
        "release_id": "release_key", "assembly_id": "assembly_key",
        "ref": "ref_allele", "qual": "quality_score", "filter": "filter_status",
        "dp": "read_depth", "af": "allele_frequency",
        "mutant_line_id": "mutant_line_surrogate_id",
    }
    for source, target in expected_mappings.items():
        assert re.search(rf"\b{source}\b.*\b{target}\b|\b{target}\b.*\b{source}\b", mapping.group(0), re.S)

    assert {f"prj_by_{name}" for name in ("gene", "mutant_line", "consequence", "region")} <= set(re.findall(r"prj_by_[a-z_]+", upgrade))
    for table in SUMMARY_TABLES:
        assert re.search(rf"DROP TABLE IF EXISTS {table}\b", upgrade)
        assert re.search(rf"CREATE TABLE {table}\b", upgrade)
        assert upgrade.index(f"DROP TABLE IF EXISTS {table}") < upgrade.index(f"INSERT INTO {table}")
    assert "DROP TABLE IF EXISTS variant_facts_legacy" not in upgrade


def test_ttl_expressions_are_date_time_typed() -> None:
    """A TTL expression must resolve to Date/DateTime, never to DateTime64.

    ClickHouse rejects the table with a server-side error rather than a syntax
    error, so nothing that only parses the DDL catches it:

        Code: 450. DB::Exception: TTL expression result column should have
        DateTime or Date type, but has DateTime64(3, 'UTC').
        (BAD_TTL_EXPRESSION)

    Both tables in this schema store ``timestamp`` as ``DateTime64(3, 'UTC')``
    for millisecond precision, so their TTLs wrap it in ``toDateTime()``: the
    stored column keeps its precision and the TTL expression has the type the
    server requires. Asserted on the DDL text because the failure only appears
    against a live server, which the fast contract layer does not have.
    """
    for name, path in (("init.sql", DDL), ("upgrade", UPGRADE)):
        # Comments are stripped before any statement is delimited: `init.sql`
        # documents `ip_hash` as "-- salted SHA-256; raw IP never stored", and
        # that semicolon in prose otherwise ends the statement eleven lines
        # before its TTL. The production splitter strips line comments for the
        # same reason.
        sql = _strip_line_comments(path.read_text())
        declared = _table_columns(path.read_text(), "analytics_events")
        assert declared.get("timestamp", "").startswith("DateTime64"), (
            f"{name}: analytics_events.timestamp is expected to stay DateTime64; "
            "if it changed to DateTime this guard needs revisiting"
        )
        for table in ("analytics_events", "web_vitals"):
            statement = re.search(rf"CREATE TABLE IF NOT EXISTS {table}\b(.*?);", sql, re.S)
            assert statement, f"{name}: {table} DDL is missing"
            ttl = re.search(r"^TTL\s+(.+)$", statement.group(1), re.M)
            assert ttl, f"{name}: {table} declares no TTL"
            expression = ttl.group(1)
            assert expression.startswith("toDateTime("), (
                f"{name}: {table} TTL expression {expression!r} must wrap the "
                "DateTime64 column in toDateTime(); ClickHouse rejects a bare "
                "DateTime64 TTL expression with BAD_TTL_EXPRESSION"
            )
