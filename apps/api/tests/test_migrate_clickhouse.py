import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).parents[3]
LIB_PATH = ROOT / "deploy/scripts/migrate_clickhouse_lib.py"
SQL = (ROOT / "infra/clickhouse/upgrade_variant_facts_schema.sql").read_text()
spec = importlib.util.spec_from_file_location("migrate_clickhouse_lib", LIB_PATH)
assert spec is not None and spec.loader is not None
lib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lib)


class FakeClient:
    def __init__(self, tables=None, responses=None):
        self.tables = tables or {}
        self.responses = responses or {}
        self.commands = []

    def query(self, sql):
        if "system.columns" in sql:
            match = re.search(r"table\s*=\s*'([^']+)'", sql)
            assert match is not None
            return [(name,) for name in self.tables.get(match.group(1), {}).get("columns", [])]
        if "system.tables" in sql:
            if "engine" in sql:
                if "system.tables" in self.responses:
                    value = self.responses["system.tables"]
                    return value(sql) if callable(value) else value
                return [(name, data.get("engine", "MergeTree")) for name, data in self.tables.items()]
            return [(name,) for name in self.tables]
        for key, value in self.responses.items():
            if key in sql:
                return value(sql) if callable(value) else value
        raise AssertionError(sql)

    def command(self, sql):
        self.commands.append(sql)


def gate_responses(legacy=2, replacement=2, empty=0, zero=0, completion=True) -> dict[str, Any]:
    responses = {
        "legacy_count": [(legacy,)],
        "replacement_count": [(replacement,)],
        "empty_release_keys": [(empty,)],
        "zero_variant_ids": [(zero,)],
    }
    if completion:
        responses["system.tables"] = lambda _: [  # type: ignore[assignment]
            (name, "MaterializedView" if name.startswith("mv_") else "MergeTree")
            for name in lib.SUMMARY_TABLES + lib.MATERIALIZED_VIEWS
        ]
    return responses


def test_s0_executes_real_sql_in_all_stages():
    client = FakeClient({"variant_facts": {"columns": ["release_id"]}}, gate_responses())
    result = lib.run_migration(client, SQL, 0.05)
    assert result["state"] == "S0"
    assert any("release_id AS release_key" in command or "toString(release_id)" in command for command in client.commands)
    assert sum("SELECT" in command for command in client.commands) >= 4
    assert any(command.startswith("RENAME TABLE") for command in client.commands)
    assert sum("CREATE MATERIALIZED VIEW" in command for command in client.commands) == 8
    assert sum("CREATE TABLE gene_impact_summary" in command for command in client.commands) == 1
    assert sum(command.startswith("INSERT INTO") for command in client.commands) == 9


def test_s1_drops_partial_replacement_before_stage1():
    client = FakeClient(
        {"variant_facts": {"columns": ["release_id"]}, "variant_facts_new": {}},
        gate_responses(),
    )
    lib.run_migration(client, SQL, 0.05)
    assert client.commands[0] == "DROP TABLE IF EXISTS variant_facts_new"
    assert client.commands[1].startswith("CREATE TABLE IF NOT EXISTS variant_facts_new")


def test_s2_skips_stage1_gate_and_rename():
    client = FakeClient({"variant_facts": {"columns": ["release_key"]}}, gate_responses())
    lib.run_migration(client, SQL, 0.05)
    assert not any("variant_facts_new" in command for command in client.commands)
    assert not any(command.startswith("RENAME TABLE") for command in client.commands)
    assert any(command.startswith("CREATE MATERIALIZED VIEW") for command in client.commands)


def test_failed_gate_blocks_stage2():
    client = FakeClient({"variant_facts": {"columns": ["release_id"]}}, gate_responses(10, 5))
    with pytest.raises(lib.MigrationGateError):
        lib.run_migration(client, SQL, 0.05)
    assert not any(command.startswith("RENAME TABLE") for command in client.commands)
    assert not any("CREATE TABLE gene_impact_summary" in command for command in client.commands)


def test_empty_legacy_table_passes_gate():
    client = FakeClient({"variant_facts": {"columns": ["release_id"]}}, gate_responses(0, 0))
    assert lib.run_migration(client, SQL, 0.05)["state"] == "S0"


def test_completion_detects_missing_or_wrong_view():
    rows = [(name, "MergeTree") for name in lib.SUMMARY_TABLES] + [
        (name, "MaterializedView") for name in lib.MATERIALIZED_VIEWS[:-1]
    ]
    client = FakeClient({"variant_facts": {"columns": ["release_key"]}}, {"system.tables": rows})
    with pytest.raises(lib.CompletionError) as error:
        lib.run_migration(client, SQL, 0.05)
    assert "mv_substitution_spectrum" in str(error.value)


def test_completion_rejects_wrong_engine_types():
    rows = [(name, "MaterializedView") for name in lib.SUMMARY_TABLES] + [
        (name, "MaterializedView") for name in lib.MATERIALIZED_VIEWS
    ]
    client = FakeClient({"variant_facts": {"columns": ["release_key"]}}, {"system.tables": rows})
    with pytest.raises(lib.CompletionError) as error:
        lib.run_migration(client, SQL, 0.05)
    assert "gene_impact_summary" in str(error.value)

    rows = [(name, "MergeTree") for name in lib.SUMMARY_TABLES] + [
        (name, "MergeTree") for name in lib.MATERIALIZED_VIEWS
    ]
    client = FakeClient({"variant_facts": {"columns": ["release_key"]}}, {"system.tables": rows})
    with pytest.raises(lib.CompletionError) as error:
        lib.run_migration(client, SQL, 0.05)
    assert "mv_gene_impact" in str(error.value)


def test_dry_run_has_no_client_side_effects():
    client = FakeClient()
    result = lib.run_migration(client, SQL, 0.05, dry_run=True)
    assert result["state"] == "S0"
    assert client.commands == []


def test_statement_text_preserves_source_line_breaks():
    """Splitting must not fuse the last token of a line with the next line's first.

    The splitter used to concatenate only the characters of each line, dropping
    the line break. A statement whose clause starts on the next line then
    arrived with its first keyword glued to the previous line's last token, and
    the server reported the syntax error at the token *after* the glued one:

      TTL timestamp + INTERVAL 2 YEAR          ->  ... INTERVAL 2 YEARSETTINGS ...
      SETTINGS index_granularity = 8192

    which ClickHouse rejected with "failed at position 623 ('index_granularity')
    ... Expected one of: NANOSECOND, …, end of query". The reported position is
    a whole token away from the actual damage, which is why this is asserted on
    the splitter rather than only end-to-end.
    """
    text = "SELECT 1\nFROM t;\nSELECT 2\nFROM u;"
    assert lib._split_statements(text) == ["SELECT 1\nFROM t", "SELECT 2\nFROM u"]


def test_no_keyword_is_glued_to_the_previous_line():
    """The real migration SQL must carry no fused clause boundary.

    A general guard, because the specific damage depends on which two clauses
    happen to end up adjacent after an edit.
    """
    fused = re.compile(r"[A-Za-z0-9_](?=(?:SETTINGS|PARTITION|ORDER|ENGINE|TTL)\b)")
    offenders = [
        (stage, statement[:80])
        for stage, statements in lib.split_stages(SQL).items()
        for statement in statements
        if fused.search(statement)
    ]
    assert offenders == [], f"line break lost before a clause keyword: {offenders}"


def test_ttl_tables_keep_their_settings_clause_on_its_own_line():
    """The two TTL tables are the pair that regressed; pin the boundary."""
    statements = [
        statement
        for statements in lib.split_stages(SQL).values()
        for statement in statements
        if "TTL" in statement and "SETTINGS" in statement
    ]
    assert len(statements) == 2, "expected the two analytics TTL tables"
    for statement in statements:
        assert re.search(r"(?:YEAR|DAY|MONTH)\s*\n\s*SETTINGS", statement), statement[:200]
