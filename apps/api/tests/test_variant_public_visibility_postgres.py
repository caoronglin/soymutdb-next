"""Public facts, details and aggregates exclude private metadata on real PG."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.v1 import stats, variants
from app.core.database import get_db
from app.core.exceptions import (
    SoyMutDBError,
    http_exception_handler,
    soy_mut_db_exception_handler,
)
from app.models.content import Release, ReleaseStatus
from app.models.variant import MutantLine, Phenotype
from app.schemas.variant import VariantFilterParams
from app.services import postgres_variant_service as store_module
from app.services.release_context import ReleaseContext, get_release_context
from app.services.variant_repository import VariantRepository


@pytest.fixture
def public_store(monkeypatch):
    url = os.environ.get("SOYMUTDB_PG_MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SOYMUTDB_PG_MIGRATION_TEST_DATABASE_URL is required")
    schema = "public_variants_" + uuid.uuid4().hex[:12]
    engine = create_async_engine(
        url, poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema + ",public"}},
    )

    def migrate(connection):
        path = Path(__file__).resolve().parents[1] / (
            "migrations/versions/0047_native_variant_analytics.py"
        )
        spec = importlib.util.spec_from_file_location("public_native_0047", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()

    async def seed():
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            for ddl in (
                "CREATE TYPE release_status_enum AS ENUM ('draft','published')",
                "CREATE TABLE releases (id integer PRIMARY KEY, "
                "status release_status_enum NOT NULL)",
                "CREATE TABLE assemblies (id integer PRIMARY KEY)",
                "CREATE TABLE mutant_lines (id integer PRIMARY KEY, release_id integer, "
                "name text, public_id text, is_public boolean, is_deleted boolean)",
                "CREATE TABLE chromosomes (id integer PRIMARY KEY, name text, length integer)",
                "CREATE TABLE variant_summaries (id integer PRIMARY KEY, release_id integer, "
                "mutant_line_id integer, chromosome_id integer, variant_type text, impact text)",
                "INSERT INTO releases VALUES (1,'published'),(2,'published'),(3,'draft')",
                "INSERT INTO assemblies VALUES (4),(5)",
                "INSERT INTO chromosomes VALUES (1,'Chr01',1000000)",
                "INSERT INTO mutant_lines VALUES "
                "(1,1,'visible','SM7QF3Z9P2A',true,false),"
                "(2,1,'PRIVATE_SENTINEL','SM7QF3Z9P2B',false,false),"
                "(3,1,'DELETED_SENTINEL','SM7QF3Z9P2C',true,true),"
                "(4,1,'NO_PUBLIC_ID_SENTINEL',NULL,true,false),"
                "(5,1,'SAME_NAME_SENTINEL','SM7QF3Z9P2D',false,false),"
                "(6,2,'SAME_NAME_SENTINEL','SM7QF3Z9P2E',true,false)",
            ):
                await conn.execute(text(ddl))
            await conn.run_sync(migrate)
            rows = [
                (1,4,101,'v4','visible',2),  # public name, surrogate != real FK
                (1,4,102,'v4','',0),
                (1,4,103,'v4','PRIVATE_SENTINEL',1),  # private name, public FK collision
                (1,4,104,'v4','DELETED_SENTINEL',3),
                (1,4,105,'v4','NO_PUBLIC_ID_SENTINEL',4),
                (1,4,106,'v4','ORPHAN_SENTINEL',0),
                (1,4,107,'v4','SAME_NAME_SENTINEL',6),
                (1,5,108,'v5','visible',2),
                (2,4,201,'v4','SAME_NAME_SENTINEL',6),
                (3,4,301,'v4','',0),
            ]
            for release, assembly, identity, key, name, surrogate in rows:
                await conn.execute(text(
                    "INSERT INTO variant_facts (release_id,assembly_id,variant_id,assembly_key,"
                    "chromosome,position,ref_allele,alt_allele,variant_type,mutant_line_name,"
                    "mutant_line_surrogate_id) VALUES "
                    "(:release,:assembly,:identity,:key,'Chr01',:position,'A','T','SNP',"
                    ":name,:surrogate)"
                ), dict(release=release, assembly=assembly, identity=identity, key=key,
                        name=name, surrogate=surrogate, position=identity))
            for identity, release, mutant in (
                (1,1,1),(2,1,None),(3,1,2),(4,1,3),(5,1,4),
                (6,1,6),(7,2,6),(8,3,None),
            ):
                await conn.execute(text(
                    "INSERT INTO variant_summaries VALUES "
                    "(:identity,:release,:mutant,1,'SNP','HIGH')"
                ), dict(identity=identity, release=release, mutant=mutant))

    asyncio.run(seed())
    monkeypatch.setattr(store_module, "get_session_factory", lambda: async_sessionmaker(engine))
    try:
        yield engine, store_module.PostgresVariantService()
    finally:
        async def cleanup():
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await engine.dispose()
        asyncio.run(cleanup())


def test_public_pages_counts_regions_and_details(public_store):
    engine, service = public_store
    context = ReleaseContext(release_id=1, assembly_id=4)

    async def exercise():
        async with AsyncSession(engine) as db:
            repo = VariantRepository(db)
            filters = VariantFilterParams(assembly="v4")
            assert await repo.count(filters, context=context) == 2
            first = await repo.list(filters, context=context, limit=1)
            assert [row["variant_id"] for row in first] == [101]
            second = await repo.list(filters, context=context, limit=1, cursor_key=(101,101))
            assert [row["variant_id"] for row in second] == [102]
            assert await repo.list(filters, context=context, limit=10, cursor_key=(102,102)) == []
            assert await repo.count(
                VariantFilterParams(assembly="v5"), context=context,
            ) == 1
            assert await repo.count(
                VariantFilterParams(assembly="v4", mutant_line_name="PRIVATE_SENTINEL"),
                context=context,
            ) == 0
            assert await repo.count(
                filters, context=ReleaseContext(release_id=3, assembly_id=4),
            ) == 0
        rows = await service.query_variants_by_region(
            "v4", "Chr01", 1, 1000, release_context=context,
        )
        assert [row["variant_id"] for row in rows] == [101,102]
        for identity in (103,104,105,106,107,201,301):
            assert await service.get_variant_by_id(str(identity), release_context=context) is None
        detail = await service.get_variant_by_id("101", release_context=context)
        assert detail["variant_id"] == 101
        assert await service.get_variant_by_id(
            "301", release_context=ReleaseContext(release_id=3, assembly_id=4),
        ) is None

    asyncio.run(exercise())


def test_native_public_aggregates_and_explicit_admin_total(public_store):
    _, service = public_store

    async def exercise():
        assert (await service.get_dashboard_stats("1"))["total_variants"] == 3
        assert (await service.get_dashboard_stats())["total_variants"] == 4
        assert (await service.get_dashboard_stats(public_only=False))["total_variants"] == 10
        assert (await service.get_dashboard_stats("3"))["total_variants"] == 0
        assert await service.get_variant_type_distribution("v4", "1") == {"SNP": 2}
        density = await service.get_chromosome_density("v4", "Chr01", 1000, "1")
        assert sum(row["count"] for row in density) == 2
        assert await service.get_dashboard_distinct_counts("1") == {
            "total_genes": 0, "total_mutant_lines": 1,
        }

    asyncio.run(exercise())


def test_summary_public_stats_exclude_private_deleted_and_cross_release_fk(public_store):
    engine, _ = public_store
    context = ReleaseContext(release_id=1, assembly_id=4)

    async def exercise():
        async with AsyncSession(engine) as db:
            assert await stats._variant_type_counts_from_pg(db, 1) == {"SNP": 2}
            assert await stats._variant_type_counts_from_pg(db, 3) == {}
            assert await stats._variant_type_counts_from_pg(db) == {"SNP": 3}
            impacts = await stats.impact_summary(db=db, release_context=context)
            assert [(item.impact, item.count) for item in impacts] == [("HIGH",2)]
            density = await stats._load_chromosome_density_summary(db, 1)
            assert len(density) == 1
            assert density[0]["variant_count"] == 2

    asyncio.run(exercise())


def test_anonymous_http_pages_region_detail_and_private_public_id(public_store):
    engine, _ = public_store
    application = FastAPI()
    application.include_router(variants.router, prefix="/api/v1")
    application.include_router(stats.router, prefix="/api/v1")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.add_exception_handler(HTTPException, http_exception_handler)

    async def get_session():
        async with AsyncSession(engine) as session:
            yield session

    application.dependency_overrides[get_db] = get_session
    application.dependency_overrides[get_release_context] = lambda: ReleaseContext(
        release_id=1, assembly_id=4,
    )

    async def exercise():
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test",
        ) as client:
            page = await client.get("/api/v1/variants", params={"assembly": "v4", "limit": 1})
            assert page.status_code == 200
            assert [item["variant_id"] for item in page.json()["items"]] == ["101"]
            cursor = page.json()["next_cursor"]
            assert cursor
            next_page = await client.get("/api/v1/variants", params={
                "assembly": "v4", "limit": 1, "cursor": cursor,
            })
            assert [item["variant_id"] for item in next_page.json()["items"]] == ["102"]
            assert not next_page.json()["has_more"]
            region = await client.get("/api/v1/variants/region", params={
                "assembly": "v4", "chromosome": "Chr01", "start": 1, "end": 1000,
            })
            assert region.status_code == 200
            assert [item["variant_id"] for item in region.json()] == ["101", "102"]
            for identity in (103, 104, 105, 106, 107, 201, 301, 999):
                detail = await client.get(f"/api/v1/variants/{identity}")
                assert detail.status_code == 404
                assert detail.json()["error"]["code"] == "not_found"
                assert "SENTINEL" not in detail.text
                assert "mutant_line_surrogate_id" not in detail.text
            assert (await client.get("/api/v1/variants/101")).status_code == 200
            for public_id in ("SM7QF3Z9P2B", "SM7QF3Z9P2Z"):
                filtered = await client.get("/api/v1/variants", params={
                    "assembly": "v4", "mutant_line_public_id": public_id,
                })
                assert filtered.status_code == 404
            assert "SENTINEL" not in page.text + next_page.text + region.text
            assert "mutant_line_surrogate_id" not in page.text + next_page.text + region.text
            distribution = await client.get("/api/v1/stats/variant-types?assembly=v4")
            assert distribution.status_code == 200
            assert distribution.json()["total"] == 2

    asyncio.run(exercise())


@pytest.mark.asyncio
async def test_public_mutant_and_phenotype_metadata_counters(db_session, monkeypatch):
    release = Release(id=8801, version="public-privacy-8801", name="Public privacy",
                      status=ReleaseStatus.PUBLISHED)
    db_session.add(release)
    await db_session.flush()
    for identity, public_id, public, deleted in (
        (8801, "SM7QF3Z9P2A", True, False),
        (8802, "SM7QF3Z9P2B", False, False),
        (8803, "SM7QF3Z9P2C", True, True),
        (8804, None, True, False),
    ):
        db_session.add(MutantLine(
            id=identity, name=f"privacy-metadata-{identity}", public_id=public_id,
            release_id=8801, is_public=public, is_deleted=deleted, mutagen="EMS",
        ))
    await db_session.flush()
    # Explicitly simulate pre-publication legacy metadata without an issued ID.
    await db_session.execute(text("UPDATE mutant_lines SET public_id=NULL WHERE id=8804"))
    for identity in (8801, 8802, 8803, 8804):
        db_session.add(Phenotype(mutant_line_id=identity, trait_category="growth",
                                 trait_name="height", trait_value="10"))
    await db_session.flush()
    # Only isolate the unrelated native-fact aggregate; metadata queries below
    # run against the full production ORM schema on real PostgreSQL.
    monkeypatch.setattr(stats, "_variant_type_summary_from_pg", AsyncMock(return_value={}))
    dashboard = await stats._load_dashboard_stats(db_session, 8801)
    assert dashboard["total_mutant_lines"] == 1
    assert dashboard["total_phenotypes"] == 1
    homepage = await stats._load_homepage_stats(db_session, 8801)
    assert homepage["mutant_line_count"] == 1
    mutagens = await stats.mutagen_statistics(
        db=db_session, release_context=ReleaseContext(release_id=8801),
    )
    assert [(item.mutagen, item.count) for item in mutagens] == [("EMS", 1)]
