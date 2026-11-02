"""Release-scoped counting contract for the admin static-build trigger.

trigger_build used to report total_genes from GeneDataCache (empty on a first
build, so a genuine first build reported 0) and trusted a gene_ids list by
length without checking that the genes exist in the release being built. It
also read the active_release pointer directly, which may be NULL or point at
an unpublished release.

These tests run against real PostgreSQL: the count, the release filter and
the outbox kwargs must agree with what the worker will actually build.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.gene_data_cache import GeneDataCache
from app.models.genomic import Assembly, Chromosome, Gene
from app.models.import_task import ImportTask
from app.models.outbox import OutboxEvent

BUILD_URL = "/api/v1/admin/build-static"


def _user(role: str) -> SimpleNamespace:
    """Minimal stand-in for the authenticated User dependency result."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        role_rel=SimpleNamespace(name=role),
        is_superuser=False,
    )


@pytest.fixture
def client_factory(app) -> Callable[[SimpleNamespace], AsyncClient]:
    """Return a client factory that authenticates as the given user."""

    def _build(user: SimpleNamespace) -> AsyncClient:
        async def _override_current_user() -> SimpleNamespace:
            return user

        app.dependency_overrides[get_current_user] = _override_current_user
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    return _build


async def _seed_release(
    db: AsyncSession,
    *,
    version: str,
    accessions: tuple[str, ...],
    status: str = ReleaseStatus.PUBLISHED.value,
    activate: bool = False,
) -> tuple[Release, Assembly]:
    """Seed release -> assembly -> chromosome -> genes, one row per accession."""
    release = Release(name=f"Static {version}", version=version, status=status)
    db.add(release)
    await db.flush()

    assembly = Assembly(
        name=f"Wm82 {version}", version=f"asm-{version}", release_id=release.id
    )
    db.add(assembly)
    await db.flush()

    chromosome = Chromosome(
        assembly_id=assembly.id, name="Chr01", length=100_000, order=0
    )
    db.add(chromosome)
    await db.flush()

    for index, accession in enumerate(accessions):
        db.add(
            Gene(
                accession=accession,
                assembly_id=assembly.id,
                chromosome_id=chromosome.id,
                start=1_000 * (index + 1),
                end=1_000 * (index + 1) + 500,
                strand="+",
                biotype="protein_coding",
            )
        )
    await db.flush()

    if activate:
        db.add(ActiveRelease(id=1, release_id=release.id))
        await db.flush()
    return release, assembly


async def _outbox_payload(db: AsyncSession, task_id: int) -> dict:
    """Return the outbox payload recorded for the queued build task."""
    result = await db.execute(
        select(OutboxEvent).where(
            OutboxEvent.aggregate_type == "import_task",
            OutboxEvent.aggregate_id == str(task_id),
        )
    )
    return result.scalar_one().payload


async def _count(db: AsyncSession, model: type) -> int:
    return int((await db.execute(select(func.count()).select_from(model))).scalar() or 0)


# ---------------------------------------------------------------------------
# Counting is release-scoped and independent of the gene cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_total_genes_counts_released_genes_when_cache_is_empty(
    db_session: AsyncSession,
    client_factory,
) -> None:
    """A first build has no GeneDataCache rows yet and must still count genes."""
    release, _ = await _seed_release(
        db_session,
        version="static-r1",
        accessions=("Glyma.01G000100", "Glyma.01G000200", "Glyma.01G000300"),
        activate=True,
    )
    assert await _count(db_session, GeneDataCache) == 0

    async with client_factory(_user("administrator")) as ac:
        response = await ac.post(BUILD_URL, json={})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body == {"task_id": body["task_id"], "total_genes": 3, "status": "queued"}

    # The queued job builds the same release the count was taken from.
    payload = await _outbox_payload(db_session, body["task_id"])
    assert payload["kwargs"] == {"gene_ids": None, "release_id": release.id}


@pytest.mark.asyncio
async def test_total_genes_excludes_genes_of_other_releases(
    db_session: AsyncSession,
    client_factory,
) -> None:
    """Genes of a different (non-active) release are never counted."""
    active, _ = await _seed_release(
        db_session,
        version="static-active",
        accessions=("Glyma.01G000100", "Glyma.01G000200"),
        activate=True,
    )
    await _seed_release(
        db_session,
        version="static-other",
        accessions=("Glyma.01G000100", "Glyma.02G000200", "Glyma.02G000300"),
    )

    async with client_factory(_user("administrator")) as ac:
        response = await ac.post(BUILD_URL, json={})

    assert response.status_code == 201, response.text
    assert response.json()["total_genes"] == 2
    payload = await _outbox_payload(db_session, response.json()["task_id"])
    assert payload["kwargs"]["release_id"] == active.id


# ---------------------------------------------------------------------------
# Explicit gene_ids selections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gene_ids_are_counted_against_real_released_genes(
    db_session: AsyncSession,
    client_factory,
) -> None:
    """Only existing genes of the release count, not the request list length."""
    await _seed_release(
        db_session,
        version="static-subset",
        accessions=("Glyma.01G000100", "Glyma.01G000200", "Glyma.01G000300"),
        activate=True,
    )

    async with client_factory(_user("administrator")) as ac:
        response = await ac.post(
            BUILD_URL,
            json={"gene_ids": ["Glyma.01G000200", "Glyma.99G999999"]},
        )

    assert response.status_code == 201, response.text
    assert response.json()["total_genes"] == 1
    payload = await _outbox_payload(db_session, response.json()["task_id"])
    assert payload["kwargs"]["gene_ids"] == ["Glyma.01G000200", "Glyma.99G999999"]


@pytest.mark.asyncio
async def test_gene_ids_from_another_release_are_not_counted(
    db_session: AsyncSession,
    client_factory,
) -> None:
    """Accessions that exist only in another release count zero."""
    await _seed_release(
        db_session,
        version="static-active-subset",
        accessions=("Glyma.01G000100",),
        activate=True,
    )
    await _seed_release(
        db_session,
        version="static-foreign-subset",
        accessions=("Glyma.02G000200", "Glyma.02G000300"),
    )

    async with client_factory(_user("administrator")) as ac:
        response = await ac.post(
            BUILD_URL, json={"gene_ids": ["Glyma.02G000200", "Glyma.02G000300"]}
        )

    assert response.status_code == 201, response.text
    assert response.json()["total_genes"] == 0


@pytest.mark.asyncio
async def test_empty_gene_ids_selects_nothing_and_counts_zero(
    db_session: AsyncSession,
    client_factory,
) -> None:
    """An empty selection is empty, it does not fall back to all genes."""
    await _seed_release(
        db_session,
        version="static-empty",
        accessions=("Glyma.01G000100", "Glyma.01G000200"),
        activate=True,
    )

    async with client_factory(_user("administrator")) as ac:
        response = await ac.post(BUILD_URL, json={"gene_ids": []})

    assert response.status_code == 201, response.text
    assert response.json()["total_genes"] == 0
    payload = await _outbox_payload(db_session, response.json()["task_id"])
    assert payload["kwargs"]["gene_ids"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"gene_ids": "Glyma.01G000100"},
        {"gene_ids": [1, 2]},
        {"gene_ids": ["x" * 65]},
        {"gene_ids": [" " * 64 + "Glyma.01G000100"]},
        {"gene_ids": [f"G{i:06d}" for i in range(201)]},
    ],
    ids=[
        "not_a_list", "non_string_entries", "entry_too_long",
        "padded_entry_too_long", "too_many_entries",
    ],
)
async def test_invalid_gene_ids_are_rejected(
    db_session: AsyncSession,
    client_factory,
    payload: dict,
) -> None:
    """Malformed selections are refused before any task or event is written."""
    await _seed_release(
        db_session,
        version="static-invalid",
        accessions=("Glyma.01G000100",),
        activate=True,
    )

    async with client_factory(_user("administrator")) as ac:
        response = await ac.post(BUILD_URL, json=payload)

    assert response.status_code == 422, response.text
    assert await _count(db_session, ImportTask) == 0
    assert await _count(db_session, OutboxEvent) == 0


# ---------------------------------------------------------------------------
# Release gating and permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_published_release_is_503_and_queues_nothing(
    db_session: AsyncSession,
    client_factory,
) -> None:
    """A draft-only installation refuses to queue a build."""
    await _seed_release(
        db_session,
        version="static-draft",
        accessions=("Glyma.01G000100",),
        status=ReleaseStatus.DRAFT.value,
        activate=True,
    )

    async with client_factory(_user("administrator")) as ac:
        response = await ac.post(BUILD_URL, json={})

    assert response.status_code == 503, response.text
    assert await _count(db_session, ImportTask) == 0
    assert await _count(db_session, OutboxEvent) == 0


@pytest.mark.asyncio
async def test_non_administrator_cannot_trigger_a_build(
    db_session: AsyncSession,
    client_factory,
) -> None:
    """The trigger stays administrator-only and writes nothing for a viewer."""
    await _seed_release(
        db_session,
        version="static-forbidden",
        accessions=("Glyma.01G000100",),
        activate=True,
    )

    async with client_factory(_user("viewer")) as ac:
        response = await ac.post(BUILD_URL, json={})

    assert response.status_code == 403, response.text
    assert await _count(db_session, ImportTask) == 0
    assert await _count(db_session, OutboxEvent) == 0
