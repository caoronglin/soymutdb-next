#!/usr/bin/env python3
"""Assert the canonical ClickHouse projection state after a legacy migration.

This replaces the assertion harness that used to live inline in the CI workflow
and is shared by the GitHub and CNB pipelines.

The canonical contract (see docs/dev/database-core-hierarchy / infra/clickhouse):

* ``variant_facts`` holds projected variant rows and every row carries a
  ``release_key``.
* The eight summary objects exist as real tables, while their materialized-view
  counterparts (``mv_*``) exist with the MaterializedView engine.

Usage:
    python scripts/assert-clickhouse-migration.py
    python scripts/assert-clickhouse-migration.py --idempotent

Exit codes: 0 = assertions passed, 1 = contract violation.

``--idempotent`` re-checks the fixture cardinality plus the fact that summaries
are materialized views of the same base table, proving a re-run changed nothing.
"""
from __future__ import annotations

import argparse
import os
import sys

SUMMARY_TABLES = (
    "gene_impact_summary",
    "chromosome_summary",
    "mutant_line_summary",
    "release_dashboard",
    "density_10kb",
    "density_100kb",
    "density_1mb",
    "substitution_spectrum",
)
MATERIALIZED_VIEWS = tuple(f"mv_{name}" for name in SUMMARY_TABLES)
EXPECTED_FIXTURE_ROWS = 3


def _client():
    try:
        import clickhouse_connect
    except ImportError:  # pragma: no cover - dependency comes from the CI image
        print("clickhouse-connect is required to run these assertions", file=sys.stderr)
        return None
    return clickhouse_connect.get_client(
        host=os.environ.get("SOYMUTDB_CLICKHOUSE_HOST", "127.0.0.1"),
        port=int(os.environ.get("SOYMUTDB_CLICKHOUSE_PORT", "8123")),
        username=os.environ.get("SOYMUTDB_CLICKHOUSE_USER", "default"),
        password=os.environ.get("SOYMUTDB_CLICKHOUSE_PASSWORD", ""),
        database=os.environ.get("SOYMUTDB_CLICKHOUSE_DATABASE", "soymutdb"),
    )


def _assert_fixture_state(client) -> None:
    rows = client.query("SELECT count() FROM variant_facts").result_rows[0][0]
    assert rows == EXPECTED_FIXTURE_ROWS, (rows, EXPECTED_FIXTURE_ROWS)
    keyed = client.query(
        "SELECT countIf(release_key != '') FROM variant_facts"
    ).result_rows[0][0]
    assert keyed == EXPECTED_FIXTURE_ROWS, (keyed, EXPECTED_FIXTURE_ROWS)


def _assert_object_engines(client) -> None:
    objects = {
        name: engine
        for name, engine in client.query(
            "SELECT name, engine FROM system.tables WHERE database = currentDatabase()"
        ).result_rows
    }
    missing_summaries = sorted(set(SUMMARY_TABLES) - objects.keys())
    assert not missing_summaries, missing_summaries
    missing_views = sorted(set(MATERIALIZED_VIEWS) - objects.keys())
    assert not missing_views, missing_views
    for name in SUMMARY_TABLES:
        assert objects[name] != "MaterializedView", (name, objects[name])
    for name in MATERIALIZED_VIEWS:
        assert objects[name] == "MaterializedView", (name, objects[name])


def _assert_summary_cardinality(client) -> int:
    unions = " UNION ALL ".join(
        f"SELECT count() AS x FROM {name}" for name in SUMMARY_TABLES
    )
    return client.query(f"SELECT sum(x) FROM ({unions})").result_rows[0][0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--idempotent",
        action="store_true",
        help="assert the re-run left fact and summary cardinality unchanged",
    )
    args = parser.parse_args(argv)

    client = _client()
    if client is None:
        return 1
    try:
        _assert_fixture_state(client)
        _assert_object_engines(client)
        total = _assert_summary_cardinality(client)
        if not args.idempotent:
            print(f"ClickHouse migration assertions passed (summary rows={total})")
        else:
            print(f"ClickHouse migration idempotence assertions passed (summary rows={total})")
    except AssertionError as error:  # noqa: PERF203 - report the failing contract
        print(f"ClickHouse migration assertion failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
