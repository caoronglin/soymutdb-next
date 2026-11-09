"""Capture and EXPLAIN the SQL that real hot paths actually execute.

Why this exists
---------------
Query-count and plan questions about this service cannot be answered from the
code alone: what reaches PostgreSQL is whatever SQLAlchemy compiled from the
ORM models, including the ``EXISTS`` subqueries and scalar subqueries the
hand-written SQL in the service layer never shows. This harness therefore
drives the *production* callables (``SearchService.global_search``, the stats
loaders, ``VariantService``) against a disposable PostgreSQL database and
captures every statement at ``before_cursor_execute``, so

* the per-request query count is measured, not estimated, and
* each captured statement is replayed through
  ``EXPLAIN (ANALYZE, BUFFERS)`` on the same data.

Safety
------
Refuses to run unless the target database name is explicitly opted in, and the
seed step truncates the tables it writes. It never touches a database other
than the one named in the DSN it was given.

Usage::

    export SOYMUTDB_PERF_DATABASE_URL='postgresql+asyncpg://.../soymutdb_perf_r2'
    python scripts/dev/explain_search_paths.py --seed
    python scripts/dev/explain_search_paths.py --json out.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

#: Databases this script may seed. Anything else is refused outright.
ALLOWED_DATABASES = {
    "soymutdb_perf",
    "soymutdb_perf_r2",
    "soymutdb_perf_r3",
    "soymutdb_perf_seed_r2",
}

#: The active recorder, so ``explain_captured`` can mute capture while it
#: replays statements through the same engine.
_ACTIVE: list[StatementRecorder] = []

#: asyncpg renders driver-level binds as ``$1``; renamed back for replay.
_DOLLAR_PARAM = re.compile(r"\$(\d+)")

RELEASE_ID = 1
ASSEMBLY_V4 = 1
ASSEMBLY_V5 = 2
SEARCH_TERM = "Glyma.05G042100"
BROAD_TERM = "Glyma"
PUBLIC_ID_TERM = "SMQ7F3Z9P2A"


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

_SEED_SQL: tuple[str, ...] = (
    ("TRUNCATE gene_crosswalks, gene_aliases, genes, chromosomes, assemblies, "
    "releases, mutant_lines, publications RESTART IDENTITY CASCADE"),
    # ---- release + assemblies -------------------------------------------
    f"""
    INSERT INTO releases (id, name, version, status, assembly, published_at,
                          variant_count, gene_count, mutant_line_count)
    VALUES ({RELEASE_ID}, 'SoyMutDB v5', '5.0', 'published', 'Glycine_max_v5.0',
            now() - interval '30 days', 400000, 300000, 20000)
    """,
    f"""
    INSERT INTO assemblies (id, name, species, version, is_default, release_id)
    VALUES ({ASSEMBLY_V4}, 'Glycine_max_v4.0', 'Glycine max', '4.0', false, {RELEASE_ID}),
           ({ASSEMBLY_V5}, 'Glycine_max_v5.0', 'Glycine max', '5.0', true,  {RELEASE_ID})
    """,
    # ---- chromosomes -----------------------------------------------------
    """
    INSERT INTO chromosomes (assembly_id, name, length, "order")
    SELECT a.id, 'Chr' || lpad(c::text, 2, '0'), 500000000 - c * 1000000, c
    FROM assemblies a, generate_series(1, 20) c
    """,
    # ---- genes -----------------------------------------------------------
    # 150k genes per assembly. v5 accessions carry the "Glyma.05G" prefix the
    # search term targets; v4 uses the historical "Glyma.16G" prefix, so the
    # two coordinate/identifier namespaces stay distinct as the contract
    # requires while both are searched by the same predicate.
    """
    INSERT INTO genes (accession, assembly_id, chromosome_id, name, biotype,
                       start, "end", strand, description)
    SELECT (CASE a.name WHEN 'Glycine_max_v5.0' THEN 'Glyma.05G' ELSE 'Glyma.16G' END)
              || lpad(g::text, 6, '0')
              || (CASE WHEN g % 3 = 0 THEN '.1' ELSE '' END),
           a.id,
           chrom.id,
           'Glyma' || lpad(g::text, 6, '0'),
           CASE WHEN g % 7 = 0 THEN 'lncRNA' ELSE 'protein_coding' END,
           1000 + g * 37,
           1000 + g * 37 + 1800,
           CASE WHEN g % 2 = 0 THEN '+' ELSE '-' END,
       'Soybean gene ' || g || ' encodes a conserved protein domain found in '
       || 'Glycine max; reviewed locus with functional annotation evidence.'
    FROM assemblies a
    CROSS JOIN generate_series(1, 150000) g
    JOIN LATERAL (
      SELECT c.id FROM chromosomes c
      WHERE c.assembly_id = a.id AND c."order" = (g % 20) + 1
    ) chrom ON true
    """,
    # ---- gene aliases ----------------------------------------------------
    """
    INSERT INTO gene_aliases (alias, source, gene_id)
    SELECT 'LEGACY_' || accession, 'legacy_v3', gene_pk
    FROM genes WHERE gene_pk % 50 = 0
    """,
    # ---- mutant lines ----------------------------------------------------
    ("""
    INSERT INTO mutant_lines (name, species, cultivar, mutagen, description,
                              is_public, release_id, is_deleted, public_id)
    SELECT 'mutant-' || n, 'Glycine max',
           'Williams' || (n % 7),
           (ARRAY['EMS','SA','gamma','Nt','DES'])[1 + (n % 5)],
           'Chemical induced mutant line ' || n
             || ' screened for drought tolerance in the field.',
           true, 1, false,
           'SM' || lpad(to_hex(n), 8, '0')
    FROM generate_series(1, 20000) n
    """),
    # ---- publications ----------------------------------------------------
    ("""
    INSERT INTO publications (title, authors, journal, year, doi, abstract)
    SELECT 'Soybean drought tolerance locus ' || n || ' identified by GWAS',
           'Zhang L; Wang H; Liu Q; et al.', 'The Plant Journal', 2010 + (n % 14),
           '10.1000/perf.' || n,
           'We report the fine mapping of drought tolerance in Glycine max. '
           || 'Field trials across three environments identified ' || n
           || ' associated loci with stable heritability estimates.'
    FROM generate_series(1, 5000) n
    """),
    # ---- cross-version links --------------------------------------------
    # One crosswalk per v5 gene, linking it to a v4 gene of the same ordinal.
    ("""
    INSERT INTO gene_crosswalks (source_gene_id, target_gene_id, relation_type,
                                 provenance_source, release_id)
    SELECT v5.gene_pk, v4.gene_pk, 'ortholog', 'phytozome_v13', 1
    FROM (SELECT gene_pk, row_number() OVER (ORDER BY gene_pk) AS rn
          FROM genes WHERE assembly_id = 2) v5
    JOIN (SELECT gene_pk, row_number() OVER (ORDER BY gene_pk) AS rn
          FROM genes WHERE assembly_id = 1) v4 USING (rn)
    WHERE v5.rn <= 40000
    """),
    "ANALYZE",
)


async def seed(engine: Any) -> dict[str, int]:
    async with engine.begin() as conn:
        for statement in _SEED_SQL:
            await conn.execute(text(statement))
        counts = {}
        for table in ("genes", "gene_aliases", "mutant_lines", "publications",
                      "gene_crosswalks", "assemblies", "releases"):
            counts[table] = int(
                (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            )
    return counts


# ---------------------------------------------------------------------------
# Statement capture
# ---------------------------------------------------------------------------


class StatementRecorder:
    """Record every statement the engine sends to the server.

    Capturing at the dialect boundary (rather than at the service boundary)
    means a round trip hidden inside a helper is still counted.
    """

    def __init__(self) -> None:
        self.statements: list[dict[str, Any]] = []
        self.paused = False

    def install(self, engine: Any) -> None:
        event.listen(engine.sync_engine, "before_execute", self._record)

    def remove(self, engine: Any) -> None:
        event.remove(engine.sync_engine, "before_execute", self._record)

    def _record(self, conn, clauseelement, multiparams, params, execution_options) -> None:
        if self.paused:
            return
        self.statements.append({"statement": clauseelement, "params": params})

    def reset(self) -> None:
        self.statements.clear()

    def take(self) -> list[dict[str, Any]]:
        """Return and clear what has been captured since the last call."""
        captured, self.statements = self.statements, []
        return captured

    @staticmethod
    def prepares(captured: dict[str, Any], dialect: Any) -> tuple[str, list[Any]]:
        """Return an ``EXPLAIN``-ready (sql, named params) pair.

        Capture happens on ``before_execute`` rather than
        ``before_cursor_execute`` precisely so the SQLAlchemy-level statement
        and its named parameters are still intact here: by the time the driver
        boundary is reached, asyncpg has rewritten every bind to a positional
        ``$n`` that cannot be replayed.
        """
        statement = captured["statement"]
        if isinstance(statement, str):
            return statement, dict(captured["params"] or {})
        compiled = statement.compile(
            dialect=dialect, compile_kwargs={"render_postcompile": True}
        )
        # Embedded literals (``func.lower(query)``) live in the compiled
        # params, not in the execute-time mapping, so they are resolved here.
        values = compiled.construct_params(params=dict(captured["params"] or {}))
        order = list(compiled.positiontup or sorted(values))
        # The asyncpg dialect renders positional ``$n`` binds and emits the
        # casts that give asyncpg its argument types; replaying through
        # ``exec_driver_sql`` keeps that pairing intact.
        return str(compiled), [values[name] for name in order]


async def explain_captured(
    engine: Any, captured: dict[str, Any]
) -> dict[str, Any]:
    """Run EXPLAIN (ANALYZE, BUFFERS) for one captured statement."""
    sql, params = StatementRecorder.prepares(captured, engine.dialect)
    prefix = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
    recorder = _ACTIVE[0]
    recorder.paused = True
    try:
        async with engine.connect() as conn:
            # Executed on the raw asyncpg connection: the statement already
            # carries ``$n`` binds and the casts asyncpg needs, and going
            # through SQLAlchemy again would re-derive the parameter mapping.
            driver = (await conn.get_raw_connection()).driver_connection
            raw = await driver.fetchval(prefix + sql, *params)
    finally:
        recorder.paused = False
    plan = json.loads(raw) if isinstance(raw, str) else raw
    return {"sql": " ".join(sql.split())[:400], **_summarise_plan(plan)}


def _root(plan: Any) -> dict[str, Any]:
    """Unwrap EXPLAIN's ``[{"Plan": {...}}]`` envelope."""
    if isinstance(plan, list) and plan and isinstance(plan[0], dict) and "Plan" in plan[0]:
        return plan[0]["Plan"]
    return plan if isinstance(plan, dict) else {}


def _walk(plan: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    stack = [_root(plan)]
    while stack:
        node = stack.pop(0)
        if "Node Type" in node:
            nodes.append(node)
        stack = list(node.get("Plans", [])) + stack
    return nodes


def _summarise_plan(plan: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = _walk(plan)
    indexes: list[str] = []
    node_types: list[str] = []
    for node in nodes:
        node_types.append(node.get("Node Type", "?"))
        for key in ("Index Name",):
            if node.get(key) and node[key] not in indexes:
                indexes.append(node[key])
    root = nodes[0] if nodes else {}
    return {
        "node_types": node_types,
        "indexes_used": indexes,
        "execution_time_ms": root.get("Actual Total Time"),
        "shared_hit_blocks": root.get("Shared Hit Blocks"),
        "shared_read_blocks": root.get("Shared Read Blocks"),
        "actual_rows": root.get("Actual Rows"),
    }


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


async def run_global_search(engine: Any, recorder: StatementRecorder) -> dict[str, Any]:
    from app.core.site_variant import SiteVariant
    from app.services.search_service import SearchService

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    service = SearchService()
    async with session_factory() as db:
        started = time.perf_counter()
        response = await service.global_search(
            db,
            SEARCH_TERM,
            limit=20,
            site_variant=SiteVariant.EXTERNAL,
            release_id=RELEASE_ID,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        captured = recorder.take()
        plans = [
            await explain_captured(engine, item) for item in captured if _is_select(item)
        ]
    return {
        "scenario": "search.global_search",
        "results": len(response.results),
        "wall_ms": round(elapsed_ms, 2),
        "query_count": len(captured),
        "plans": plans,
    }


async def run_homepage_stats(engine: Any, recorder: StatementRecorder) -> dict[str, Any]:
    from app.api.v1 import stats as stats_module

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        started = time.perf_counter()
        payload = await stats_module._load_homepage_stats(db)
        elapsed_ms = (time.perf_counter() - started) * 1000
        captured = recorder.take()
    return {
        "scenario": "stats._load_homepage_stats",
        "gene_count": payload["gene_count"],
        "wall_ms": round(elapsed_ms, 2),
        "query_count": len(captured),
        "sql": [_one_line(item) for item in captured],
    }


async def run_dashboard_stats(engine: Any, recorder: StatementRecorder) -> dict[str, Any]:
    from app.api.v1 import stats as stats_module

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        started = time.perf_counter()
        payload = await stats_module._load_dashboard_stats(db, RELEASE_ID)
        elapsed_ms = (time.perf_counter() - started) * 1000
        captured = recorder.take()
    return {
        "scenario": "stats._load_dashboard_stats",
        "total_genes": payload["total_genes"],
        "wall_ms": round(elapsed_ms, 2),
        "query_count": len(captured),
        "sql": [_one_line(item) for item in captured],
    }


def _is_select(captured: dict[str, Any]) -> bool:
    statement = captured["statement"]
    sql = statement if isinstance(statement, str) else str(statement)
    return sql.lstrip().upper().startswith(("SELECT", "WITH"))


def _one_line(captured: dict[str, Any]) -> str:
    statement = captured["statement"]
    sql = statement if isinstance(statement, str) else str(statement)
    return " ".join(sql.split())[:200]


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _install_legacy_gene_match() -> None:
    """Restore the pre-0048 gene match predicate for a like-for-like A/B.

    Same rows, same release scope, same pattern — only the shape of the match
    predicate differs, so the two EXPLAIN runs differ solely in whether the
    trigram indexes can be used.
    """
    from app.models.genomic import Assembly, Gene, GeneAlias
    from app.services import search_service
    from sqlalchemy import and_, or_, select

    def legacy(query: str, pattern: str, *, release_id: int, assembly_id: int | None):
        scope = [Assembly.release_id == release_id]
        if assembly_id is not None:
            scope.append(Gene.assembly_id == assembly_id)
        text_match = or_(
            Gene.accession.ilike(pattern, escape="\\"),
            Gene.name.ilike(pattern, escape="\\"),
            Gene.description.ilike(pattern, escape="\\"),
        )
        alias_exists = (
            select(GeneAlias.gene_id)
            .where(
                GeneAlias.gene_id == Gene.gene_pk,
                search_service.func.lower(GeneAlias.alias)
                == search_service.func.lower(query.strip()),
            )
            .exists()
        )
        return (
            select(Gene.gene_pk)
            .join(Assembly, Assembly.id == Gene.assembly_id)
            .where(and_(or_(text_match, alias_exists), *scope))
        )

    search_service._gene_match_query = legacy


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.environ.get("SOYMUTDB_PERF_DATABASE_URL"))
    parser.add_argument("--seed", action="store_true", help="load synthetic data first")
    parser.add_argument(
        "--legacy-gene-match",
        action="store_true",
        help=(
            "measure the pre-0048 gene match shape (OR of text tests and a "
            "correlated alias EXISTS) so the two plans can be compared on one "
            "database"
        ),
    )
    parser.add_argument("--json", help="write the captured report here")
    args = parser.parse_args()

    if not args.dsn:
        parser.error("set SOYMUTDB_PERF_DATABASE_URL or pass --dsn")
    database = args.dsn.rsplit("/", 1)[-1].split("?")[0]
    if database not in ALLOWED_DATABASES:
        parser.error(
            f"refusing to touch database {database!r}; allowed: {sorted(ALLOWED_DATABASES)}"
        )

    os.environ.setdefault("SOYMUTDB_JWT_SECRET", "perf_harness_secret")
    os.environ["SOYMUTDB_DATABASE_URL"] = args.dsn
    os.environ["SOYMUTDB_REDIS_URL"] = os.environ.get(
        "SOYMUTDB_REDIS_URL", "redis://127.0.0.1:1/0"
    )

    engine = create_async_engine(args.dsn, future=True)
    report: dict[str, Any] = {"database": database}
    if args.seed:
        started = time.perf_counter()
        report["seed_rows"] = await seed(engine)
        report["seed_seconds"] = round(time.perf_counter() - started, 2)

    recorder = StatementRecorder()
    _ACTIVE.append(recorder)
    recorder.install(engine)
    # PostgresVariantService opens its own sessions through the global factory;
    # pointing it at this engine keeps those round trips inside the capture.
    from app.core import database as database_module

    database_module._engine = engine
    database_module._session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    if args.legacy_gene_match:
        _install_legacy_gene_match()
    report["scenarios"] = [
        await run_global_search(engine, recorder),
        await run_homepage_stats(engine, recorder),
        await run_dashboard_stats(engine, recorder),
    ]
    await engine.dispose()

    print(json.dumps(report, indent=2, default=str))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
