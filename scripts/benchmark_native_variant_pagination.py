"""Synthetic pagination benchmark; uses only its own temporary schema.

Requires an explicitly supplied disposable PostgreSQL DSN in
SOYMUTDB_BENCHMARK_DATABASE_URL. Run with the API Python environment.
"""

import argparse
import asyncio
import importlib.util
import json
import os
import time
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(
    description="Compare native variant pagination indexes on an isolated synthetic PostgreSQL schema"
)
parser.add_argument("--output", default="/tmp/native-variant-perf.json")
args = parser.parse_args()
spec = importlib.util.spec_from_file_location(
    "revision", root / "apps/api/migrations/versions/0047_native_variant_analytics.py"
)
revision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(revision)
schema = "native_perf_" + uuid.uuid4().hex[:12]
queries = {
    "assembly_first": "SELECT variant_id,position FROM variant_facts WHERE release_id=1 AND assembly_key='v4' ORDER BY position,variant_id LIMIT 50",
    "assembly_deep": "SELECT variant_id,position FROM variant_facts WHERE release_id=1 AND assembly_key='v4' AND (position,variant_id)>(8000,150000) ORDER BY position,variant_id LIMIT 50",
    "release_first": "SELECT variant_id,position FROM variant_facts WHERE release_id=1 ORDER BY position,variant_id LIMIT 50",
    "region": "SELECT variant_id,position FROM variant_facts WHERE release_id=1 AND assembly_key='v4' AND chromosome='Chr01' AND position BETWEEN 100 AND 1000 ORDER BY position,variant_id LIMIT 50",
}


def upgrade(conn):
    with Operations.context(MigrationContext.configure(conn)):
        revision.upgrade()


async def main():
    engine = create_async_engine(
        os.environ["SOYMUTDB_BENCHMARK_DATABASE_URL"],
        connect_args={"server_settings": {"search_path": schema + ",public"}},
    )
    report = {
        "scope": "synthetic 200000 variants / local warm queries; excludes HTTP, production data and concurrency",
        "rows": 200000,
    }
    try:
        async with engine.begin() as c:
            report["postgres_version"] = (
                await c.execute(text("SHOW server_version"))
            ).scalar_one()
            await c.execute(text(f'CREATE SCHEMA "{schema}"'))
            await c.execute(text("CREATE TABLE releases (id INTEGER PRIMARY KEY)"))
            await c.execute(text("CREATE TABLE assemblies (id INTEGER PRIMARY KEY)"))
            await c.execute(text("INSERT INTO releases VALUES (1)"))
            await c.execute(text("INSERT INTO assemblies VALUES (4)"))
            await c.run_sync(upgrade)
            await c.execute(text("DROP INDEX ix_variant_facts_page"))
            await c.execute(text("DROP INDEX ix_variant_facts_assembly_page"))
            await c.execute(
                text(
                    "INSERT INTO variant_facts (release_id,assembly_id,variant_id,assembly_key,chromosome,position,ref_allele,alt_allele,variant_type) SELECT 1,4,n,'v4','Chr'||lpad(((n%20)+1)::text,2,'0'),((n/20)%10000)+1,'A','T','SNP' FROM generate_series(1,200000) n"
                )
            )
            await c.execute(text("ANALYZE variant_facts"))
        for phase in ["before", "after"]:
            async with engine.begin() as c:
                if phase == "after":
                    await c.execute(
                        text(
                            "CREATE INDEX ix_variant_facts_page ON variant_facts (release_id,position,variant_id)"
                        )
                    )
                    await c.execute(
                        text(
                            "CREATE INDEX ix_variant_facts_assembly_page ON variant_facts (release_id,assembly_key,position,variant_id)"
                        )
                    )
                    await c.execute(text("ANALYZE variant_facts"))
                results = {}
                for name, query in queries.items():
                    await c.execute(text(query))
                    durations = []
                    for _ in range(25):
                        started = time.perf_counter()
                        await c.execute(text(query))
                        durations.append((time.perf_counter() - started) * 1000)
                    plan = (
                        await c.execute(
                            text("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + query)
                        )
                    ).scalar_one()
                    results[name] = {
                        "p95_ms": sorted(durations)[23],
                        "median_ms": sorted(durations)[12],
                        "plan": plan,
                    }
                report[phase] = results
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    phase: {k: round(v["p95_ms"], 3) for k, v in report[phase].items()}
                    for phase in ["before", "after"]
                }
            )
        )
    finally:
        async with engine.begin() as c:
            await c.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


asyncio.run(main())
