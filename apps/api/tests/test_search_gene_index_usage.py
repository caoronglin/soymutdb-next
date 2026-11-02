"""Global gene search must stay on the trigram indexes.

Background
----------
Adding the curated-alias test to the gene text match as ``OR EXISTS (...)`` made
PostgreSQL abandon the trigram indexes from migration 0046. A ``SubPlan``
inside an ``OR`` list cannot become a bitmap index condition, so the whole
disjunction degraded into a filter on a scan node and every identifier-shaped
search -- the normal case for a search box -- read ``genes`` end to end.

Measured on 300k genes with the same term, release and seed
(``scripts/dev/explain_search_paths.py``; ``--legacy-gene-match`` for "before"):

* ``OR EXISTS``   -> ``Index Scan using ix_gene_accession`` with
  ``Rows Removed by Filter: 299999``; 788 ms for the page query and 733 ms for
  the assembly-distribution aggregate; 1687 ms for the whole endpoint.
* ``UNION`` arms  -> ``BitmapOr`` over ``ix_genes_accession_trgm`` /
  ``ix_genes_name_trgm`` / ``ix_genes_description_trgm``; 9.8 ms and 6.6 ms;
  167 ms for the whole endpoint.
* ``SET enable_seqscan = off`` did **not** give the ``OR`` form its indexes back,
  so this is a structural limit of the query shape, not a cost estimate the
  planner merely got wrong.

The tests below pin that shape twice over: once on the compiled SQL, which needs
no database, and once on a real planner in a private schema, which fails if the
predicate ever drifts back.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import event, func, or_, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.site_variant import SiteVariant
from app.models.genomic import Assembly, Gene, GeneAlias
from app.services.search_service import SearchService, _gene_match_query

RELEASE_ID = 1
ASSEMBLY_V4 = 1
#: Identifier-shaped and single-token, so ``_is_exact_accession`` is true and the
#: alias arm is part of the statement -- the shape that used to disable the index.
QUERY = "Glyma.05G0421"
PATTERN = f"%{QUERY}%"
SEED_ROWS = 30_000
MATCHING_ROWS = 5
TRIGRAM_INDEXES = (
    "ix_genes_accession_trgm",
    "ix_genes_name_trgm",
    "ix_genes_description_trgm",
)


def _database_url() -> str | None:
    return os.environ.get("SOYMUTDB_TEST_DATABASE_URL")


def _compile(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def _render(rows) -> str:
    """EXPLAIN rows as one printable plan."""
    return "\n".join(row[0] for row in rows)


# --------------------------------------------------------------------------- #
# Compiled-SQL layer (no database required)
# --------------------------------------------------------------------------- #


def test_gene_match_query_unions_the_alias_arm_instead_of_or_ing_it() -> None:
    sql = _compile(
        _gene_match_query(QUERY, PATTERN, release_id=RELEASE_ID, assembly_id=None)
    )

    assert "UNION ALL" in sql, sql
    # The text arm must stay a pure disjunction of ILIKEs: one correlated
    # SubPlan anywhere in it is what disables the trigram indexes.
    text_arm = sql.split("UNION ALL")[0]
    assert "EXISTS" not in text_arm, text_arm
    assert text_arm.count("ILIKE") == 3, text_arm
    assert "lower(gene_aliases.alias)" in sql, sql


def test_gene_match_query_keeps_release_and_assembly_scope_in_both_arms() -> None:
    sql = _compile(
        _gene_match_query(
            QUERY, PATTERN, release_id=RELEASE_ID, assembly_id=ASSEMBLY_V4
        )
    )
    assert sql.count("assemblies.release_id") == 2, sql
    assert sql.count("genes.assembly_id =") == 2, sql

    unscoped = _compile(
        _gene_match_query(QUERY, PATTERN, release_id=RELEASE_ID, assembly_id=None)
    )
    assert "genes.assembly_id =" not in unscoped, unscoped


def test_free_text_query_needs_no_alias_arm() -> None:
    sql = _compile(
        _gene_match_query(
            "drought tolerance",
            "%drought tolerance%",
            release_id=RELEASE_ID,
            assembly_id=None,
        )
    )
    assert "UNION ALL" not in sql, sql
    assert "gene_aliases" not in sql, sql


@pytest.mark.asyncio
async def test_gene_search_statements_carry_no_subplan(db_session) -> None:
    """The page query and the ambiguity aggregate share one indexable shape.

    If either regains a SubPlan inside the text disjunction the planner loses the
    trigram indexes for that statement. That is invisible in the response body
    and only shows up as a full table scan under load.
    """
    service = SearchService()
    captured: list[str] = []

    @event.listens_for(db_session.sync_session, "do_orm_execute")
    def _record(execute_state) -> None:
        captured.append(_compile(execute_state.statement))

    try:
        await service._search_genes(
            db_session,
            QUERY,
            PATTERN,
            limit=21,
            release_id=RELEASE_ID,
            assembly_id=None,
            site_variant=SiteVariant.EXTERNAL,
        )
        await service._gene_assembly_distribution(
            db_session, QUERY, PATTERN, release_id=RELEASE_ID
        )
    finally:
        event.remove(db_session.sync_session, "do_orm_execute", _record)

    assert len(captured) == 2, captured
    for sql in captured:
        assert "genes.gene_pk IN (SELECT" in sql, sql
        # Only the match subquery matters. The ranking CASE in the projection
        # legitimately keeps a correlated alias test, and it runs once per
        # *matched* row rather than once per scanned row.
        match = sql[sql.index("genes.gene_pk IN (SELECT") : sql.index("UNION ALL")]
        assert "EXISTS" not in match, match
        assert match.count("ILIKE") == 3, match


# --------------------------------------------------------------------------- #
# Real PostgreSQL planner
# --------------------------------------------------------------------------- #

#: asyncpg prepares one statement at a time, so each is listed separately. These
#: are the columns migrations 0046/0048 index, trimmed to what search reads.
_DDL = (
    """CREATE TABLE {schema}.assemblies (
    id INTEGER PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    species VARCHAR(128) NOT NULL,
    version VARCHAR(64) NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT false,
    release_id INTEGER
)""",
    """CREATE TABLE {schema}.genes (
    gene_pk BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    accession VARCHAR(64) NOT NULL,
    assembly_id INTEGER NOT NULL,
    chromosome_id INTEGER NOT NULL,
    name VARCHAR(256),
    biotype VARCHAR(64) NOT NULL,
    start BIGINT NOT NULL,
    "end" BIGINT NOT NULL,
    strand VARCHAR(1) NOT NULL,
    description TEXT
)""",
    """CREATE TABLE {schema}.gene_aliases (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alias VARCHAR(256) NOT NULL,
    source VARCHAR(128),
    gene_id BIGINT NOT NULL
)""",
)

#: Exactly what migrations 0046 and 0048 provide, created inline so this test
#: does not depend on the Alembic runtime.
_INDEXES = (
    "CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA public",
    "CREATE INDEX ix_genes_accession_trgm ON {schema}.genes "
    "USING gin (accession gin_trgm_ops)",
    "CREATE INDEX ix_genes_name_trgm ON {schema}.genes USING gin (name gin_trgm_ops)",
    "CREATE INDEX ix_genes_description_trgm ON {schema}.genes "
    "USING gin (description gin_trgm_ops)",
    "CREATE INDEX ix_gene_aliases_alias_lower ON {schema}.gene_aliases (lower(alias))",
)

_SEED = (
    """INSERT INTO {schema}.assemblies (id, name, species, version, release_id)
VALUES (1, 'Glycine_max_v4.0', 'Glycine max', '4.0', 1),
       (2, 'Glycine_max_v5.0', 'Glycine max', '5.0', 1)""",
    # Only the first {matching} v5 accessions start with the searched prefix;
    # the rest of the table is noise a sequential scan would have to read.
    """INSERT INTO {schema}.genes (accession, assembly_id, chromosome_id, name,
                            biotype, start, "end", strand, description)
SELECT CASE WHEN n <= {matching}
            THEN 'Glyma.05G0421' || lpad(n::text, 2, '0')
            ELSE 'Glyma.16G' || lpad(n::text, 6, '0') END,
       CASE WHEN n % 2 = 0 THEN 2 ELSE 1 END,
       1,
       'Glyma.16G' || lpad(n::text, 6, '0'),
       'protein_coding', 1000 + n, 2000 + n, '+',
       'Filler annotation row ' || n
FROM generate_series(1, {rows}) AS n""",
    """INSERT INTO {schema}.gene_aliases (alias, source, gene_id)
SELECT 'LEGACY_' || n, 'legacy_v3', n
FROM generate_series(1, {rows}) AS n WHERE n % 50 = 0""",
    "ANALYZE {schema}.genes",
    "ANALYZE {schema}.gene_aliases",
    "ANALYZE {schema}.assemblies",
)


def _legacy_aggregate_statement():
    """The pre-0048 aggregate, kept as the evidence these tests rest on."""
    text_match = or_(
        Gene.accession.ilike(PATTERN, escape="\\"),
        Gene.name.ilike(PATTERN, escape="\\"),
        Gene.description.ilike(PATTERN, escape="\\"),
    )
    alias_exists = (
        select(GeneAlias.gene_id)
        .where(
            GeneAlias.gene_id == Gene.gene_pk,
            func.lower(GeneAlias.alias) == func.lower(QUERY),
        )
        .exists()
    )
    legacy = (
        select(Gene.gene_pk)
        .join(Assembly, Assembly.id == Gene.assembly_id)
        .where(or_(text_match, alias_exists), Assembly.release_id == RELEASE_ID)
    )
    return (
        select(Gene.assembly_id, func.count())
        .where(Gene.gene_pk.in_(legacy))
        .group_by(Gene.assembly_id)
    )


async def _explain_many(driver, dialect, statements, *, force_index: bool) -> list[str]:
    """EXPLAIN each statement, optionally with sequential scans priced out.

    Statements are compiled with the engine's own dialect and replayed
    positionally on the raw asyncpg connection: that is the only combination
    that keeps both the ``$n`` binds and the casts asyncpg uses to infer
    argument types.
    """
    compiled_pairs = []
    for statement, parameters in statements:
        compiled = statement.compile(
            dialect=dialect, compile_kwargs={"render_postcompile": True}
        )
        values = compiled.construct_params(params=dict(parameters or {}))
        order = list(compiled.positiontup or sorted(values))
        compiled_pairs.append((str(compiled), [values[name] for name in order]))

    if force_index:
        await driver.execute("SET enable_seqscan = off")
    try:
        return [
            _render(await driver.fetch("EXPLAIN (ANALYZE, BUFFERS) " + sql, *args))
            for sql, args in compiled_pairs
        ]
    finally:
        if force_index:
            await driver.execute("RESET enable_seqscan")


@pytest.fixture(scope="module")
def planned_schema() -> dict:
    """Run the real search in a private schema and report its plans.

    The schema is created and dropped here; nothing global is touched apart from
    the ``pg_trgm`` extension, which migrations 0027/0046 already require.
    """
    url = _database_url()
    if not url:
        pytest.skip(
            "no PostgreSQL URL: set SOYMUTDB_TEST_DATABASE_URL to run the "
            "planner layer"
        )
    if not url.startswith("postgresql+asyncpg://"):
        pytest.skip("PostgreSQL URL must use the postgresql+asyncpg:// scheme")

    schema = "gene_search_plan_" + uuid.uuid4().hex[:12]
    quoted = '"' + schema + '"'
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema + ",public"}}
    )

    async def run() -> dict:
        outcome: dict = {}
        try:
            async with engine.connect() as connection:
                await connection.execute(text(f"CREATE SCHEMA {quoted}"))
                for statement in (*_DDL, *_INDEXES, *_SEED):
                    await connection.execute(
                        text(
                            statement.format(
                                schema=quoted, rows=SEED_ROWS, matching=MATCHING_ROWS
                            )
                        )
                    )
                await connection.commit()

            issued: list[tuple] = []
            factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            async with factory() as db:

                @event.listens_for(db.sync_session, "do_orm_execute")
                def _capture(execute_state) -> None:
                    issued.append((execute_state.statement, execute_state.parameters))

                service = SearchService()
                try:
                    hits = await service._search_genes(
                        db,
                        QUERY,
                        PATTERN,
                        limit=21,
                        release_id=RELEASE_ID,
                        assembly_id=None,
                        site_variant=SiteVariant.EXTERNAL,
                    )
                    distribution = await service._gene_assembly_distribution(
                        db, QUERY, PATTERN, release_id=RELEASE_ID
                    )
                finally:
                    event.remove(db.sync_session, "do_orm_execute", _capture)

            outcome["hits"] = len(hits)
            outcome["distribution"] = distribution
            outcome["issued_count"] = len(issued)

            async with engine.connect() as connection:
                driver = (await connection.get_raw_connection()).driver_connection
                dialect = engine.dialect
                names = ("page", "distribution")
                plans: dict[str, dict[str, str]] = {}
                for key, force in (("default", False), ("forced", True)):
                    for name, plan in zip(
                        names,
                        await _explain_many(driver, dialect, issued, force_index=force),
                        strict=True,
                    ):
                        plans.setdefault(name, {})[key] = plan
                outcome["legacy_forced"] = (
                    await _explain_many(
                        driver,
                        dialect,
                        [(_legacy_aggregate_statement(), {})],
                        force_index=True,
                    )
                )[0]
                outcome["plans"] = plans
        finally:
            async with engine.connect() as connection:
                await connection.rollback()
                await connection.execute(text(f"DROP SCHEMA IF EXISTS {quoted} CASCADE"))
                await connection.commit()
            await engine.dispose()
        return outcome

    return asyncio.run(run())


def test_planned_search_returns_the_matching_genes(planned_schema: dict) -> None:
    """The index fix must not change which rows a search answers with."""
    assert planned_schema["issued_count"] == 2
    assert planned_schema["hits"] == MATCHING_ROWS
    # Odd ordinals land on the v4 assembly, even ones on v5.
    assert planned_schema["distribution"] == {"1": 3, "2": 2}


@pytest.mark.parametrize("statement", ["page", "distribution"])
def test_gene_search_statements_reach_the_trigram_indexes(
    planned_schema: dict, statement: str
) -> None:
    plan = planned_schema["plans"][statement]["forced"]
    for index in TRIGRAM_INDEXES:
        assert index in plan, plan


def test_pre_0048_shape_still_cannot_reach_the_trigram_indexes(
    planned_schema: dict,
) -> None:
    """Why the shape is pinned rather than left to the cost model.

    With sequential scans priced out, the old ``OR ... EXISTS`` predicate still
    finds no trigram index to use and falls back to reading the table. If this
    ever starts passing, the regression that motivated the UNION has been
    misdiagnosed and the test above is not proving what it claims.
    """
    plan = planned_schema["legacy_forced"]
    for index in TRIGRAM_INDEXES:
        assert index not in plan, plan
