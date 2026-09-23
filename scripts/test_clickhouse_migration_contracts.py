"""Cross-check the ClickHouse summary/materialized-view names the gate asserts.

Regression for the red clickhouse-migration gate (main run 35822630107,
d17c0a96b):

    ClickHouse migration assertion failed: ['mv_gene_impact_summary']

``scripts/assert-clickhouse-migration.py`` derived the materialized-view names
as ``mv_{summary_table}``, producing ``mv_gene_impact_summary``. Every canonical
source names that one view ``mv_gene_impact`` (without ``_summary``), so the
real migration was correct and only the assertion was wrong. Deriving the name
is what allowed a green migration to be reported as a failure, so the mapping
now lives explicitly in four places that must agree; this suite pins them:

* ``scripts/assert-clickhouse-migration.py`` (the gate)
* ``deploy/scripts/migrate_clickhouse_lib.py`` (the executor that validates them)
* ``infra/clickhouse/init.sql`` (fresh-database DDL)
* ``infra/clickhouse/upgrade_variant_facts_schema.sql`` (the legacy-migration SQL)
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]

SUMMARY_TABLES = {
    "gene_impact_summary",
    "chromosome_summary",
    "mutant_line_summary",
    "release_dashboard",
    "density_10kb",
    "density_100kb",
    "density_1mb",
    "substitution_spectrum",
}

# The irregular member: the schema never gained the `_summary` suffix here.
GENE_IMPACT_VIEW = "mv_gene_impact"
GENE_IMPACT_TABLE = "gene_impact_summary"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _materialized_view_pairs(sql: str) -> dict[str, str]:
    """Map each ``CREATE MATERIALIZED VIEW ... TO <table>`` view to its table."""
    return {
        view: table
        for view, table in re.findall(
            r"CREATE MATERIALIZED VIEW IF NOT EXISTS (\w+) TO (\w+)", sql
        )
    }


def test_every_source_agrees_on_the_summary_and_view_names() -> None:
    assertion = _load(ROOT / "scripts/assert-clickhouse-migration.py", "assert_clickhouse")
    executor = _load(
        ROOT / "deploy/scripts/migrate_clickhouse_lib.py", "migrate_clickhouse_lib"
    )

    assert set(assertion.SUMMARY_TABLES) == SUMMARY_TABLES
    assert set(executor.SUMMARY_TABLES) == SUMMARY_TABLES
    assert set(assertion.MATERIALIZED_VIEWS) == set(executor.MATERIALIZED_VIEWS)

    for relative in (
        "infra/clickhouse/init.sql",
        "infra/clickhouse/upgrade_variant_facts_schema.sql",
    ):
        sql = (ROOT / relative).read_text(encoding="utf-8")
        pairs = _materialized_view_pairs(sql)
        assert set(pairs) == set(executor.MATERIALIZED_VIEWS), relative
        assert set(pairs.values()) == SUMMARY_TABLES, relative
        assert len(pairs) == len(SUMMARY_TABLES), relative


def test_gene_impact_view_keeps_its_irregular_name() -> None:
    assertion = _load(ROOT / "scripts/assert-clickhouse-migration.py", "assert_clickhouse")
    views = set(assertion.MATERIALIZED_VIEWS)

    assert GENE_IMPACT_VIEW in views
    assert "mv_gene_impact_summary" not in views
    assert len(views) == len(SUMMARY_TABLES)
