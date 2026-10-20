"""Native storage migration and lookup contracts on an isolated PostgreSQL schema."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.schemas.variant import VariantFilterParams
from app.services import postgres_variant_service as postgres_module
from app.services.analytics_service import AnalyticsService
from app.services.release_context import ReleaseContext
from app.services.variant_repository import VariantRepository, _predicates

REVISION = Path(__file__).resolve().parents[1] / (
    "migrations/versions/0047_native_variant_analytics.py"
)


def _migration(connection, operation):
    spec = importlib.util.spec_from_file_location("native_0047", REVISION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, operation)()


def test_query_values_are_bound_and_scope_is_mandatory():
    attack = "v4' OR true --"
    where, values = _predicates(
        VariantFilterParams(assembly=attack, gene_id="private' OR true --"),
        ReleaseContext(release_id=17, assembly_id=5),
    )
    assert "release_id = :release_id" in where
    assert attack not in where
    assert values["release_id"] == 17
    assert values["assembly"] == attack
    # A release's primary assembly is context, not a restriction on explicitly
    # requested alternative assemblies. The filter owns the assembly scope.
    assert "context_assembly_id" not in where


def test_native_migration_and_unsigned_variant_lookup(monkeypatch):
    url = os.environ.get("SOYMUTDB_PG_MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SOYMUTDB_PG_MIGRATION_TEST_DATABASE_URL is required")

    async def exercise():
        schema = "native_variants_" + uuid.uuid4().hex[:12]
        engine = create_async_engine(
            url, connect_args={"server_settings": {"search_path": schema + ",public"}},
        )
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text("CREATE TABLE releases (id INTEGER PRIMARY KEY)"))
                await connection.execute(text("CREATE TABLE assemblies (id INTEGER PRIMARY KEY)"))
                await connection.execute(text("INSERT INTO releases VALUES (1), (2)"))
                await connection.execute(text("INSERT INTO assemblies VALUES (4), (5)"))
                await connection.run_sync(_migration, "upgrade")
                indexes = set((await connection.execute(text(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = :schema "
                    "AND tablename = 'variant_facts'"
                ), {"schema": schema})).scalars())
                assert {"ix_variant_facts_page", "ix_variant_facts_assembly_page"} <= indexes

            monkeypatch.setattr(
                postgres_module, "get_session_factory", lambda: async_sessionmaker(engine),
            )

            async with AsyncSession(engine) as db:
                statement = text(
                    "INSERT INTO variant_facts "
                    "(release_id, assembly_id, variant_id, assembly_key, chromosome, "
                    "position, ref_allele, alt_allele, variant_type) "
                    "VALUES (:release, :assembly, :variant, :key, 'Chr01', 100, 'A', 'T', 'SNP')"
                )
                maximum = 18446744073709551615
                for release, assembly, variant, key in (
                    (1, 4, maximum - 1, "v4"), (1, 4, maximum, "v4"),
                    (1, 5, 10, "v5"), (2, 4, 20, "v4"),
                ):
                    await db.execute(statement, {
                        "release": release, "assembly": assembly,
                        "variant": variant, "key": key,
                    })
                await db.commit()
                repository = VariantRepository(db)
                context = ReleaseContext(release_id=1, assembly_id=5)
                filters = VariantFilterParams(assembly="v4")
                assert await repository.count(filters, context=context) == 2
                first = await repository.list(filters, context=context, limit=1)
                assert first[0]["variant_id"] == maximum - 1
                assert first[0]["release_key"] == "1"
                second = await repository.list(
                    filters, context=context, limit=1, cursor_key=(100, maximum - 1),
                )
                assert second[0]["variant_id"] == maximum
                assert await repository.count(
                    VariantFilterParams(assembly="v5"), context=context,
                ) == 1
                assert await repository.count(
                    VariantFilterParams(assembly="v4' OR true --"), context=context,
                ) == 0
                with pytest.raises(ValueError):
                    await repository.list(filters, context=context, limit=0)
                await db.rollback()
                with pytest.raises(IntegrityError):
                    async with db.begin():
                        await db.execute(statement, {
                            "release": 1, "assembly": 4, "variant": maximum + 1, "key": "v4",
                        })
                with pytest.raises(IntegrityError):
                    async with db.begin():
                        await db.execute(statement, {
                            "release": 999, "assembly": 4, "variant": 1, "key": "v4",
                        })
                with pytest.raises(IntegrityError):
                    async with db.begin():
                        await db.execute(statement, {
                            "release": 1, "assembly": 5, "variant": maximum, "key": "v5",
                        })

            service = postgres_module.PostgresVariantService()
            assert await service.ping()
            # The cheap aggregate carries no distinct counts any more: every
            # caller discarded them and each one cost a full scan plus a sort.
            assert await service.get_dashboard_stats("1") == {
                "total_variants": 3,
                "snp_count": 3, "ins_count": 0, "del_count": 0, "mnv_count": 0, "sv_count": 0,
            }
            # The distinct counts stay available as an explicit, separately
            # billed call.
            assert await service.get_dashboard_distinct_counts("1") == {
                "total_genes": 0, "total_mutant_lines": 0,
            }
            assert await service.get_variant_type_distribution("v4", "1") == {"SNP": 2}
            assert await service.get_chromosome_density("v4", "Chr01", 100, "1") == [
                {"bin_start": 1, "bin_end": 100, "count": 2},
            ]
            assert await service.get_query_latency_percentile() == 0.0
            assert await service.get_query_latency_series() == []
            detail = await service.get_variant_by_id(str(maximum), release_context=context)
            assert detail and detail["assembly_key"] == "v4"
            assert await service.get_variant_by_id("20", release_context=context) is None
            assert await service.get_variant_by_id("' OR true --", release_context=context) is None
            region = await service.query_variants_by_region(
                "v5", "Chr01", 90, 101, release_context=context,
            )
            assert [row["variant_id"] for row in region] == [10]
            async with engine.begin() as connection:
                await connection.execute(text(
                    "INSERT INTO analytics_events "
                    "(timestamp, session_id, event_type, page, path, duration_ms) "
                    "VALUES (now(), :session, 'pageview', '/', '/', 100), "
                    "(now(), :session, 'pageview', '/', '/', 300)"
                ), {"session": uuid.uuid4()})
            assert await service.get_query_latency_percentile(0.5) == 200.0
            series = await service.get_query_latency_series()
            assert len(series) == 1
            assert series[0]["p50"] == 200.0
            assert series[0]["p95"] == 290.0
            async with engine.begin() as connection:
                await connection.execute(text("DELETE FROM analytics_events"))
            analytics = AnalyticsService(session_factory=async_sessionmaker(engine))
            tracking_session = uuid.uuid4().hex
            await analytics.record_event(
                session_id=tracking_session, event_type="pageview",
                page="/mutants/PRIVATE_INTERNAL_918273?query=SECRET",
                path="https://private.invalid/genes/PRIVATE_GENE?q=SECRET",
                search_query="SECRET", user_agent="PRIVATE_BROWSER", ip_hash="PRIVATE_IP",
                referrer="https://www.google.com/search?q=SECRET", duration_ms=10,
            )
            await analytics.record_event(
                session_id=tracking_session, event_type="search", page="/search?q=SECRET",
            )
            await analytics.record_web_vital(
                session_id=tracking_session, name="LCP", value=123, rating="good",
                path="/mutants/PRIVATE_INTERNAL_918273", user_agent="PRIVATE_BROWSER",
            )
            summary = await analytics.get_summary()
            assert summary.total_events == 2
            assert summary.unique_sessions == 1
            assert summary.total_events_available
            assert summary.top_searches == []
            assert not summary.top_searches_available
            assert "PRIVATE" not in summary.model_dump_json()
            assert "SECRET" not in summary.model_dump_json()
            assert summary.model_dump()["top_pages"] == [
                {"label": "/mutants/:publicId", "count": 1},
            ]
            async with engine.connect() as connection:
                row = (await connection.execute(text(
                    "SELECT page, path, referrer FROM analytics_events WHERE event_type='pageview'"
                ))).one()
                assert row == ("/mutants/:publicId", "/genes/:geneId", "search")
                assert (await connection.execute(text(
                    "SELECT metric_name, value, path FROM web_vitals"
                ))).one() == ("LCP", 123.0, "/mutants/:publicId")
            async with engine.begin() as connection:
                await connection.run_sync(_migration, "downgrade")
                assert (await connection.execute(text(
                    "SELECT to_regclass(:variants), to_regclass(:events)"
                ), {
                    "variants": f"{schema}.variant_facts",
                    "events": f"{schema}.analytics_events",
                })).one() == (None, None)
                remaining = await connection.execute(text("SELECT count(*) FROM releases"))
                assert remaining.scalar() == 2
        finally:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()

    asyncio.run(exercise())
