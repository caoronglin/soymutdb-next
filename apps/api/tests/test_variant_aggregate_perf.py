"""Regression guards for the variant aggregate cost and the pooled-connection use.

Two defects are covered here:

* the homepage/dashboard aggregate computed two ``count(DISTINCT ...)`` numbers
  that no caller reads, so every cache miss paid for two extra sorts over
  ``variant_facts`` (and no index supports either distinct);
* a variants-list request checked out a second pooled connection, because the
  store opened a session of its own next to the request-scoped one.

The public response shape is guarded as well: ``total_genes`` and
``total_mutant_lines`` stay part of the dashboard contract, so they must keep
coming from the relational tables instead of the variant projection.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import event, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.content import Release, ReleaseStatus
from app.models.genomic import Assembly
from app.models.variant import MutantLine
from app.models.variant_facts import variant_facts
from app.schemas.analytics import DashboardStats
from app.services import postgres_variant_service as postgres_module
from app.services.release_context import ReleaseContext, get_release_context

RELEASE_ID = 7001
ASSEMBLY_ID = 7001
OTHER_RELEASE_ID = 7002
OTHER_ASSEMBLY_ID = 7002
PUBLIC_LINE_ID = "SM7QF3Z9P2A"
SECOND_PUBLIC_LINE_ID = "SM8RF3Z9P2B"

VARIANTS_PREFIX = "/api/v1/variants"
STATS_PREFIX = "/api/v1/stats"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def release_context_override(app):
    """Resolve the seeded release for every request of this module."""
    app.dependency_overrides[get_release_context] = _release_context
    yield
    app.dependency_overrides.pop(get_release_context, None)


async def _release_context() -> ReleaseContext:
    return ReleaseContext(
        release_id=RELEASE_ID, assembly_id=ASSEMBLY_ID, assembly="v5",
    )


@pytest.fixture
def store_on_test_transaction(db_connection, monkeypatch) -> SimpleNamespace:
    """Point the variant store at the test transaction and count its sessions.

    The store's session joins the outer transaction, so the seeded rows are
    visible to the aggregate without a second pooled connection.
    """
    factory = async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    opened: list[str] = []

    def counting_factory():
        opened.append("session")
        return factory

    monkeypatch.setattr(postgres_module, "get_session_factory", counting_factory)
    return SimpleNamespace(factory=factory, opened=opened)


async def _seed_release_data(db: AsyncSession) -> None:
    """Seed two releases, three mutant lines and their variant facts.

    Release 7001 owns three distinct genes and one mutant-line surrogate;
    release 7002 owns a fourth gene and a second surrogate. The aggregates
    must therefore differ per release, which is what makes the release scope
    observable.
    """
    db.add_all([
        Release(
            id=RELEASE_ID, version="agg-v7001", name="aggregate release 7001",
            status=ReleaseStatus.PUBLISHED, assembly_id=ASSEMBLY_ID, assembly="v5",
        ),
        Release(
            id=OTHER_RELEASE_ID, version="agg-v7002", name="aggregate release 7002",
            status=ReleaseStatus.PUBLISHED, assembly_id=OTHER_ASSEMBLY_ID, assembly="v5",
        ),
    ])
    db.add_all([
        Assembly(
            id=ASSEMBLY_ID, name="agg-assembly-7001", species="Glycine max",
            version="v5", release_id=RELEASE_ID,
        ),
        Assembly(
            id=OTHER_ASSEMBLY_ID, name="agg-assembly-7002", species="Glycine max",
            version="v5", release_id=OTHER_RELEASE_ID,
        ),
    ])
    db.add_all([
        MutantLine(
            id=RELEASE_ID, public_id=PUBLIC_LINE_ID, name="agg-line-7001",
            release_id=RELEASE_ID, is_public=True, is_deleted=False,
        ),
        MutantLine(
            id=OTHER_RELEASE_ID, public_id=SECOND_PUBLIC_LINE_ID, name="agg-line-7002",
            release_id=OTHER_RELEASE_ID, is_public=True, is_deleted=False,
        ),
        # Keep the relational/dashboard distinction: this public line belongs
        # to the first release but has no variant facts. A fact in release7002
        # must not borrow visibility from a line in release7001.
        MutantLine(
            id=7003, public_id="SM9RF3Z9P2C", name="agg-line-7001-unobserved",
            release_id=RELEASE_ID, is_public=True, is_deleted=False,
        ),
    ])
    # The relational rows must exist before the facts that reference them.
    await db.flush()
    await db.execute(insert(variant_facts), [
        {
            "release_id": RELEASE_ID, "assembly_id": ASSEMBLY_ID, "variant_id": 1,
            "assembly_key": "v5", "chromosome": "Chr01", "position": 100,
            "ref_allele": "A", "alt_allele": "T", "variant_type": "SNP",
            "gene_id": "Glyma.01G000100", "mutant_line_surrogate_id": 709926958,
            "mutant_line_name": "agg-line-7001",
            "consequence": "missense_variant", "impact": "HIGH",
        },
        {
            "release_id": RELEASE_ID, "assembly_id": ASSEMBLY_ID, "variant_id": 2,
            "assembly_key": "v5", "chromosome": "Chr01", "position": 200,
            "ref_allele": "C", "alt_allele": "G", "variant_type": "SNP",
            "gene_id": "Glyma.01G000100", "mutant_line_surrogate_id": 709926958,
            "mutant_line_name": "agg-line-7001",
            "consequence": "missense_variant", "impact": "HIGH",
        },
        {
            "release_id": RELEASE_ID, "assembly_id": ASSEMBLY_ID, "variant_id": 3,
            "assembly_key": "v5", "chromosome": "Chr01", "position": 300,
            "ref_allele": "A", "alt_allele": "AAA", "variant_type": "INS",
            "gene_id": "Glyma.01G000200", "mutant_line_surrogate_id": 709926958,
            "mutant_line_name": "agg-line-7001",
            "consequence": "missense_variant", "impact": "HIGH",
        },
        {
            "release_id": RELEASE_ID, "assembly_id": ASSEMBLY_ID, "variant_id": 4,
            "assembly_key": "v5", "chromosome": "Chr01", "position": 400,
            "ref_allele": "TTT", "alt_allele": "A", "variant_type": "DEL",
            "gene_id": "Glyma.01G000300", "mutant_line_surrogate_id": 0,
            "mutant_line_name": "",
            "consequence": "missense_variant", "impact": "HIGH",
        },
        {
            "release_id": OTHER_RELEASE_ID, "assembly_id": OTHER_ASSEMBLY_ID,
            "variant_id": 5, "assembly_key": "v5", "chromosome": "Chr02",
            "position": 500, "ref_allele": "G", "alt_allele": "A", "variant_type": "SV",
            "gene_id": "Glyma.02G000100", "mutant_line_surrogate_id": OTHER_RELEASE_ID,
            "mutant_line_name": "agg-line-7002",
            "consequence": "missense_variant", "impact": "HIGH",
        },
    ])
    await db.flush()


# ---------------------------------------------------------------------------
# 1. The dashboard aggregate must not compute the unused distinct counts.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_aggregate_issues_no_distinct_aggregate(
    db_session, db_connection, store_on_test_transaction,
):
    """The homepage/dashboard aggregate must not sort ``variant_facts`` twice.

    Both distinct counts were read by nobody, and each one forces a full
    scan plus a DISTINCT sort that no index supports.
    """
    await _seed_release_data(db_session)
    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db_connection.sync_connection, "before_cursor_execute", _capture)
    try:
        stats = await postgres_module.PostgresVariantService().get_dashboard_stats(
            str(RELEASE_ID),
        )
    finally:
        event.remove(db_connection.sync_connection, "before_cursor_execute", _capture)

    assert statements, "the aggregate must actually reach the database"
    assert not any("count(distinct" in statement.lower() for statement in statements), (
        statements
    )
    # The two numbers are not part of the cheap aggregate any more.
    assert "total_genes" not in stats
    assert "total_mutant_lines" not in stats
    assert stats == {
        "total_variants": 4,
        "snp_count": 2, "ins_count": 1, "del_count": 1, "mnv_count": 0, "sv_count": 0,
    }


@pytest.mark.asyncio
async def test_distinct_counts_stay_available_through_an_explicit_call(
    db_session, db_connection, store_on_test_transaction,
):
    """The information is not lost: it has its own, separately billed call."""
    await _seed_release_data(db_session)
    service = postgres_module.PostgresVariantService()

    scoped = await service.get_dashboard_distinct_counts(str(RELEASE_ID))
    every = await service.get_dashboard_distinct_counts()

    assert scoped == {"total_genes": 3, "total_mutant_lines": 1}
    assert every == {"total_genes": 4, "total_mutant_lines": 2}


# ---------------------------------------------------------------------------
# 2. The release scope of the aggregate is unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_aggregate_stays_scoped_to_the_requested_release(
    db_session, db_connection, store_on_test_transaction,
):
    """A release-scoped aggregate must not see another release's facts."""
    await _seed_release_data(db_session)
    service = postgres_module.PostgresVariantService()

    scoped = await service.get_dashboard_stats(str(RELEASE_ID))
    unscoped = await service.get_dashboard_stats()

    # Release 7001 owns four facts; release 7002 owns the fifth one.
    assert scoped["total_variants"] == 4
    assert scoped["sv_count"] == 0
    assert unscoped["total_variants"] == 5
    assert unscoped["sv_count"] == 1
    assert scoped["total_variants"] < unscoped["total_variants"]


@pytest.mark.asyncio
async def test_distinct_counts_stay_scoped_to_the_requested_release(
    db_session, db_connection, store_on_test_transaction,
):
    """The explicit distinct call honours the same release scope."""
    await _seed_release_data(db_session)
    service = postgres_module.PostgresVariantService()

    scoped = await service.get_dashboard_distinct_counts(str(RELEASE_ID))
    every = await service.get_dashboard_distinct_counts()

    assert scoped["total_genes"] == 3
    assert scoped["total_mutant_lines"] == 1
    assert every["total_genes"] == 4
    assert every["total_mutant_lines"] == 2


# ---------------------------------------------------------------------------
# 3. A variants-list request holds one pooled connection, not two.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_variants_holds_a_single_pooled_connection(
    client, db_session, test_engine, monkeypatch, release_context_override,
):
    """One request must not check out a second pooled connection.

    The request-scoped session resolves the public mutant id; the store used
    to open a session of its own for the page, so the request held two of the
    five pooled connections of an API worker.
    """
    await _seed_release_data(db_session)

    opened: list[str] = []

    def counting_factory():
        opened.append("session")
        return async_sessionmaker(
            test_engine, class_=AsyncSession, expire_on_commit=False,
        )

    monkeypatch.setattr(postgres_module, "get_session_factory", counting_factory)

    connections: list[object] = []
    checked_out: list[int] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        connections.append(conn)
        checked_out.append(test_engine.sync_engine.pool.checkedout())

    event.listen(test_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        response = await client.get(
            VARIANTS_PREFIX, params={"mutant_line_public_id": PUBLIC_LINE_ID},
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _capture)

    assert response.status_code == 200
    # The store did not open a session of its own ...
    assert opened == []
    # ... and the whole request ran on a single pooled connection.
    unique: list[object] = []
    for conn in connections:
        if not any(conn is other for other in unique):
            unique.append(conn)
    assert len(unique) == 1
    assert max(checked_out) == 1
    # The page was really read: the store used the request's own session, so
    # it sees the rows the request's transaction holds.
    body = response.json()
    assert len(body["items"]) == 3


# ---------------------------------------------------------------------------
# 4. The public dashboard contract is unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_response_shape_is_unchanged(
    client, app, db_session, db_connection, monkeypatch, release_context_override,
):
    """``total_genes`` / ``total_mutant_lines`` stay in the public contract.

    They are part of the published OpenAPI schema, so they must keep being
    answered — from the relational tables, which is where the dashboard has
    always read them, not from the variant projection.
    """
    await _seed_release_data(db_session)
    factory = async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(postgres_module, "get_session_factory", lambda: factory)

    response = await client.get(f"{STATS_PREFIX}/dashboard")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == set(DashboardStats.model_fields)
    assert "total_genes" in body
    assert "total_mutant_lines" in body
    # The relational tables own these numbers: no gene row exists, while two
    # mutant lines belong to the release. The variant facts would have
    # reported 3 genes and 1 line instead.
    assert body["total_genes"] == 0
    assert body["total_mutant_lines"] == 2

    schema = app.openapi()["components"]["schemas"]["DashboardStats"]
    assert {"total_genes", "total_mutant_lines"} <= set(schema["required"])
    assert schema["properties"]["total_genes"]["type"] == "integer"
    assert schema["properties"]["total_mutant_lines"]["type"] == "integer"
