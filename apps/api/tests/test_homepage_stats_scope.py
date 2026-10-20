"""Release-scope guards for the public home page statistics.

The public home page aggregate used to count the whole database: every gene,
every mutant line (public or not), every assembly, every seed lot and every
variant fact. An anonymous visitor therefore learned the size of unpublished
data — a draft release's variants, another release's assemblies, the lines that
are not public.

The contract now is:

* the aggregate is bound to the resolved published release, exactly like the
  sibling statistics endpoints;
* the Redis cache key carries that release, so one release's aggregate is
  never served for another;
* a database without a published release answers an empty aggregate instead of
  failing the public home page.

The PostgreSQL-backed tests seed a published release (the active one), a
second published release and a draft release, each with its own assemblies,
genes, mutant lines, seed lots and native variant facts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import stats as stats_module
from app.core.public_ids import generate_public_id
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.genomic import Assembly, Chromosome, Gene
from app.models.seed import SeedInventory
from app.models.variant import MutantLine
from app.models.variant_facts import variant_facts
from app.services import cache as cache_module
from app.services import postgres_variant_service as pg_module
from app.services.release_context import ReleaseContext

_PUBLISHED_AT = datetime(2026, 9, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _BoundSession:
    """Async context manager handing the test's own session to a service.

    The native variant projection owns its own session factory. Binding it to
    the test transaction lets the aggregate read the facts the test seeded
    instead of an unrelated database.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


@pytest.fixture
def bind_variant_service(monkeypatch, db_session: AsyncSession) -> None:
    """Run the native PostgreSQL variant projection in the test transaction."""
    monkeypatch.setattr(
        pg_module,
        "get_session_factory",
        lambda: lambda: _BoundSession(db_session),
    )


class _FakeRedis:
    """Minimal in-memory Redis so the cache-aside path is observable."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value


@pytest.fixture
def fake_redis(monkeypatch) -> _FakeRedis:
    """Replace the unavailable Redis of the test suite with a real store."""
    redis = _FakeRedis()
    monkeypatch.setattr(cache_module, "get_redis", lambda: redis)
    return redis


async def _seed_release(
    db: AsyncSession,
    *,
    version: str,
    status: str,
    assembly_name: str,
    genes: int = 0,
    public_lines: int = 0,
    hidden_lines: int = 0,
    seeds: int = 0,
    facts: int = 0,
) -> Release:
    """Create one release with its assembly, genes, lines, seeds and facts."""
    release = Release(
        version=version,
        name=f"Release {version}",
        status=status,
        published_at=_PUBLISHED_AT if status == ReleaseStatus.PUBLISHED.value else None,
        assembly=assembly_name,
    )
    db.add(release)
    await db.flush()

    assembly = Assembly(
        name=assembly_name,
        species="Glycine max",
        version="a4",
        release_id=release.id,
    )
    db.add(assembly)
    await db.flush()

    chromosome = Chromosome(
        assembly_id=assembly.id,
        name="Gm01",
        length=100_000,
        order=1,
    )
    db.add(chromosome)
    await db.flush()

    for index in range(genes):
        db.add(
            Gene(
                accession=f"{assembly_name}.G{index:03d}",
                assembly_id=assembly.id,
                chromosome_id=chromosome.id,
                name=f"gene-{assembly_name}-{index}",
                biotype="protein_coding",
                start=index * 1_000 + 1,
                end=index * 1_000 + 900,
                strand="+",
            )
        )

    lines: list[MutantLine] = []
    for index in range(public_lines):
        line = MutantLine(
            name=f"{assembly_name}-line-{index}",
            species="Glycine max",
            mutagen="EMS",
            is_public=True,
            public_id=generate_public_id(),
            release_id=release.id,
        )
        db.add(line)
        lines.append(line)
    for index in range(hidden_lines):
        db.add(
            MutantLine(
                name=f"{assembly_name}-hidden-{index}",
                species="Glycine max",
                mutagen="EMS",
                is_public=False,
                release_id=release.id,
            )
        )
    await db.flush()

    for index in range(seeds):
        db.add(
            SeedInventory(
                mutant_line_id=lines[index].id,
                seed_lot=f"{assembly_name}-lot-{index}",
                quantity_grams=1.5,
            )
        )

    for index in range(facts):
        await db.execute(
            variant_facts.insert(),
            {
                "release_id": release.id,
                "assembly_id": assembly.id,
                "variant_id": index + 1,
                "assembly_key": assembly_name,
                "chromosome": "Gm01",
                "position": 100 + index,
                "ref_allele": "A",
                "alt_allele": "T",
                "variant_type": "SNP" if index % 2 == 0 else "INS",
            },
        )
    await db.flush()
    return release


async def _seed_world(db: AsyncSession) -> dict[str, Release]:
    """Seed the released, the other published and the draft release."""
    released = await _seed_release(
        db,
        version="2026.09",
        status=ReleaseStatus.PUBLISHED.value,
        assembly_name="GmWm82.a4.v1",
        genes=2,
        public_lines=3,
        hidden_lines=1,
        seeds=2,
        facts=4,
    )
    other = await _seed_release(
        db,
        version="2026.08",
        status=ReleaseStatus.PUBLISHED.value,
        assembly_name="GmWm82.a2.v1",
        genes=7,
        public_lines=6,
        seeds=3,
        facts=12,
    )
    draft = await _seed_release(
        db,
        version="2026.10-draft",
        status=ReleaseStatus.DRAFT.value,
        assembly_name="GmWm82.a5.v1",
        genes=5,
        public_lines=4,
        seeds=3,
        facts=9,
    )
    db.add(ActiveRelease(id=1, release_id=released.id))
    await db.flush()
    return {"released": released, "other": other, "draft": draft}


# ---------------------------------------------------------------------------
# 1. The aggregate counts the released release only.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_homepage_counts_only_the_resolved_release(
    client, db_session: AsyncSession, bind_variant_service: None
) -> None:
    """Draft data, other-release data and non-public lines are not counted."""
    releases = await _seed_world(db_session)

    response = await client.get("/api/v1/stats/homepage")
    assert response.status_code == 200
    body = response.json()

    # Genes and assemblies are counted through the release's assemblies.
    assert body["gene_count"] == 2
    assert body["assembly_count"] == 1
    # Only the release's public, non-deleted lines count.
    assert body["mutant_line_count"] == 3
    # Seed lots hang off a mutant line, so they follow the same scope.
    assert body["seed_accessions"] == 2
    # Variant facts of the draft and of the other release are not counted.
    assert body["total_variants"] == 4
    assert body["snp_count"] == 2
    assert body["indel_count"] == 2
    assert body["sv_count"] == 0
    # The release the aggregate is bound to is the resolved one.
    assert body["last_release_name"] == releases["released"].version
    assert datetime.fromisoformat(body["last_release_date"]) == _PUBLISHED_AT
    # Drafts are not published, so they are not part of the release history.
    assert body["release_count"] == 2


@pytest.mark.asyncio
async def test_a_pinned_release_reports_its_own_data(
    client, db_session: AsyncSession, bind_variant_service: None
) -> None:
    """A pinned published release answers with that release's numbers."""
    releases = await _seed_world(db_session)

    response = await client.get(f"/api/v1/stats/homepage?release_id={releases['other'].id}")
    assert response.status_code == 200
    body = response.json()

    assert body["gene_count"] == 7
    assert body["assembly_count"] == 1
    assert body["mutant_line_count"] == 6
    assert body["seed_accessions"] == 3
    assert body["total_variants"] == 12


# ---------------------------------------------------------------------------
# 2. The cache entry is bound to the release.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_entries_are_not_shared_between_releases(
    client,
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    bind_variant_service: None,
) -> None:
    """Two releases must not be served from one cache entry."""
    releases = await _seed_world(db_session)

    first = await client.get("/api/v1/stats/homepage")
    second = await client.get(f"/api/v1/stats/homepage?release_id={releases['other'].id}")

    assert first.status_code == 200
    assert second.status_code == 200
    # Each release answers with its own numbers, not with a cached neighbour.
    assert first.json()["gene_count"] == 2
    assert second.json()["gene_count"] == 7
    # Two distinct cache entries, one per release.
    homepage_keys = [key for key in fake_redis.store if "stats:homepage" in key]
    assert len(homepage_keys) == 2
    assert len(set(homepage_keys)) == 2


@pytest.mark.asyncio
async def test_cache_key_carries_the_release(
    client, db_session: AsyncSession, fake_redis: _FakeRedis
) -> None:
    """The cache key names the release, so a collision is impossible."""
    releases = await _seed_world(db_session)

    await client.get("/api/v1/stats/homepage")
    keys = [key for key in fake_redis.store if "stats:homepage" in key]
    assert len(keys) == 1

    await client.get(f"/api/v1/stats/homepage?release_id={releases['other'].id}")
    keys = [key for key in fake_redis.store if "stats:homepage" in key]
    assert len(keys) == 2
    assert len(set(keys)) == 2


# ---------------------------------------------------------------------------
# 3. No published release answers an empty aggregate, not a 5xx.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_without_a_published_release_the_homepage_answers_zeroes(
    client, db_session: AsyncSession
) -> None:
    """A draft-only database renders the home page instead of failing it."""
    draft = await _seed_release(
        db_session,
        version="2026.10-draft",
        status=ReleaseStatus.DRAFT.value,
        assembly_name="GmWm82.a5.v1",
        genes=5,
        public_lines=4,
        seeds=3,
        facts=9,
    )
    db_session.add(ActiveRelease(id=1, release_id=draft.id))
    await db_session.flush()

    response = await client.get("/api/v1/stats/homepage")
    assert response.status_code == 200
    body = response.json()
    assert body["total_variants"] == 0
    assert body["snp_count"] == 0
    assert body["indel_count"] == 0
    assert body["sv_count"] == 0
    assert body["gene_count"] == 0
    assert body["mutant_line_count"] == 0
    assert body["assembly_count"] == 0
    assert body["seed_accessions"] == 0
    assert body["last_release_name"] is None
    assert body["last_release_date"] is None


# ---------------------------------------------------------------------------
# 4. Unit guards: the queries and the projection carry the release.
# ---------------------------------------------------------------------------


class _Rows:
    """Minimal result stub for the statement-recording session."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def scalars(self) -> _Rows:
        return self

    def one(self) -> Any:
        return self._rows[0]

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _RecordingDb:
    """Records the statements the loader issues."""

    def __init__(self, results: list[Any] | None = None) -> None:
        self.statements: list[Any] = []
        self._results = list(results or [])

    async def execute(self, statement: Any) -> _Rows:
        self.statements.append(statement)
        result = self._results.pop(0) if self._results else []
        return _Rows(result if isinstance(result, list) else [result])

    def sql(self, index: int = -1) -> str:
        return str(self.statements[index])


class _CapturingVariantService:
    """Records the release key the native projection is queried with."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def get_dashboard_stats(self, release_key: str | None = None) -> dict[str, int]:
        self.calls.append({"release_key": release_key})
        return {"total_variants": 0}


@pytest.mark.asyncio
async def test_the_aggregate_is_bound_to_the_release_in_sql() -> None:
    """Ablation: dropping the release predicates counts every release."""
    db = _RecordingDb(results=[(2, 3, 1, 1, 2, _PUBLISHED_AT, "2026.09", 7)])
    service = _CapturingVariantService()
    original = stats_module.variant_service
    stats_module.variant_service = service
    try:
        await stats_module._load_homepage_stats(db, 7)
    finally:
        stats_module.variant_service = original

    sql = db.sql(0)
    assert "assemblies.release_id" in sql, sql
    assert "mutant_lines.release_id" in sql, sql
    assert "mutant_lines.is_public" in sql, sql
    assert "mutant_lines.is_deleted" in sql, sql
    assert "genes.assembly_id IN" in sql or "genes.assembly_id in" in sql, sql
    # The native projection is queried for that release only.
    assert service.calls[0]["release_key"] == "7"


@pytest.mark.asyncio
async def test_the_cache_key_carries_the_release_id() -> None:
    """The Redis key names the release, so no two releases can collide."""
    seen: list[dict[str, Any]] = []

    async def _fake_get_or_set(key, ttl, *, loader, params=None):
        seen.append({"key": key, "params": params})
        return await loader()

    db = _RecordingDb(
        results=[
            (2, 3, 1, 1, 2, _PUBLISHED_AT, "2026.09", 7),
            (9, 9, 1, 1, 9, _PUBLISHED_AT, "2026.08", 8),
        ]
    )
    original = stats_module.get_or_set
    service = _CapturingVariantService()
    original_service = stats_module.variant_service
    stats_module.get_or_set = _fake_get_or_set
    stats_module.variant_service = service
    try:
        await stats_module.homepage_stats(
            db=db, release_context=ReleaseContext(release_id=7)
        )
        await stats_module.homepage_stats(
            db=db, release_context=ReleaseContext(release_id=8)
        )
    finally:
        stats_module.get_or_set = original
        stats_module.variant_service = original_service

    assert seen[0]["params"] == {"release_id": 7}
    assert seen[1]["params"] == {"release_id": 8}
    assert seen[0]["params"] != seen[1]["params"]
    assert cache_module.make_cache_key(seen[0]["key"], seen[0]["params"]) != (
        cache_module.make_cache_key(seen[1]["key"], seen[1]["params"])
    )
