"""Ablation guards for the public statistics release boundary.

The review found the public stats surface was effectively release-free and, in
one place, disclosed internal operational data:

* ``/stats/dashboard`` counted every gene/mutant/phenotype/assembly row, exposed
  the real account population anonymously, and cached one global key;
* ``/stats/variant-types`` and ``/stats/density`` queried the variant facts
  without a release, so bins and distributions spanned every release's facts;
* ``/summary/{variant-types,impact,chromosome-density,mutagens}`` accepted an
  arbitrary ``release_id`` (including a draft's) and only filtered when the
  caller supplied one;
* ``/stats/releases`` defaulted to listing every release, drafts and rollbacks
  included.

The contract now is: each endpoint resolves ``ReleaseContext`` (published-only)
and filters unconditionally; cache keys carry the resolved release.

Unit-level guards (no PostgreSQL): the route coroutines are driven with a fake
session / fake PostgreSQL variant service that records what was asked.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.api.v1 import stats as stats_module
from app.services.release_context import ReleaseContext

_RELEASE_ID = 7


def _context(release_id: int = _RELEASE_ID) -> ReleaseContext:
    return ReleaseContext(release_id=release_id, assembly_id=3, assembly="Wm82.a4.v1")


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def scalars(self) -> _Rows:
        return self

    def one(self):
        return self._rows[0]

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0] if self._rows else 0


class _Release:
    """Minimal release row for the dashboard's version lookup."""

    version = "2026.09"


class _RecordingDb:
    """Records statements and replays a scripted list of results.

    The dashboard issues two different queries (an aggregate row then the
    release row), so results are queued rather than shared.
    """

    def __init__(self, results: list[Any] | None = None) -> None:
        self.statements: list[Any] = []
        self._results = list(results or [])

    async def execute(self, statement: Any) -> _Rows:
        self.statements.append(statement)
        result = self._results.pop(0) if self._results else []
        if isinstance(result, _Rows):
            return result
        if isinstance(result, list):
            # An empty/queued row *list* is a result set, not a single row.
            return _Rows(result)
        return _Rows([result])

    async def scalar(self, statement: Any):
        self.statements.append(statement)
        return 0

    def sql(self, index: int = -1) -> str:
        return str(self.statements[index])


class _CapturingVariantService:
    """Records the parameters a PostgreSQL variant query was called with."""

    def __init__(self, result: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._result = result

    async def get_dashboard_stats(self, release_key: str | None = None):
        self.calls.append({"release_key": release_key})
        return self._result or {"total_variants": 0}

    async def get_variant_type_distribution(
        self, assembly: str | None = None, release_key: str | None = None
    ):
        self.calls.append({"assembly": assembly, "release_key": release_key})
        return self._result or {}

    async def get_chromosome_density(self, **kwargs: Any):
        self.calls.append(kwargs)
        return self._result or []


# ---------------------------------------------------------------------------
# 1. Dashboard: release-scoped counts, no anonymous account population.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_counts_are_bound_to_the_release():
    """Ablation: dropping the release predicates counts every release's rows."""
    db = _RecordingDb(results=[(10, 4, 3, 2), _Release()])
    ch = _CapturingVariantService()

    import app.api.v1.stats as mod

    original = mod.variant_service
    mod.variant_service = ch
    try:
        payload = await stats_module._load_dashboard_stats(db, _RELEASE_ID)  # noqa: SLF001
    finally:
        mod.variant_service = original

    sql = db.sql(0)
    # Genes are bounded by the release's assemblies; mutants/phenotypes/assemblies
    # are filtered directly.
    assert "genes.assembly_id IN" in sql or "genes.assembly_id in" in sql, sql
    assert "assemblies.release_id" in sql, sql
    assert "mutant_lines.release_id" in sql, sql
    assert payload["total_genes"] == 10
    # The PostgreSQL variant aggregate is bound to the same release key.
    assert ch.calls[0]["release_key"] == str(_RELEASE_ID)


@pytest.mark.asyncio
async def test_dashboard_never_exposes_the_account_population():
    db = _RecordingDb(results=[(10, 4, 3, 2), _Release()])

    import app.api.v1.stats as mod

    ch = _CapturingVariantService()
    original = mod.variant_service
    mod.variant_service = ch
    try:
        payload = await stats_module._load_dashboard_stats(db, _RELEASE_ID)  # noqa: SLF001
    finally:
        mod.variant_service = original

    assert payload["total_users"] == 0
    # The User table is not even queried any more.
    assert "users" not in db.sql(0).lower()


# ---------------------------------------------------------------------------
# 2. Aggregate endpoints filter unconditionally on the published release.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_variant_type_summary_filters_without_a_caller_supplied_pin():
    db = _RecordingDb(results=[("SNP", 5)])

    await stats_module.variant_type_summary(db=db, release_context=_context())

    where = db.sql(0).split("WHERE", 1)[-1]
    assert "variant_summaries.release_id" in where, db.sql(0)
    bound = set(db.statements[0].compile().params.values())
    assert _RELEASE_ID in bound, bound


@pytest.mark.asyncio
async def test_impact_summary_filters_unconditionally():
    db = _RecordingDb(results=[("HIGH", 3)])

    await stats_module.impact_summary(db=db, release_context=_context())

    where = db.sql(0).split("WHERE", 1)[-1]
    assert "variant_summaries.release_id" in where, db.sql(0)


@pytest.mark.asyncio
async def test_mutagen_statistics_filters_unconditionally():
    db = _RecordingDb(results=[("EMS", 3)])

    await stats_module.mutagen_statistics(db=db, release_context=_context())

    where = db.sql(0).split("WHERE", 1)[-1]
    assert "mutant_lines.release_id" in where, db.sql(0)


@pytest.mark.asyncio
async def test_chromosome_density_summary_caches_per_release():
    db = _RecordingDb(results=[])
    seen: list[dict[str, Any]] = []

    async def _fake_get_or_set(key, ttl, *, loader, params=None):
        seen.append({"key": key, "params": params})
        return await loader()

    import app.api.v1.stats as mod

    original = mod.get_or_set
    mod.get_or_set = _fake_get_or_set
    try:
        await stats_module.chromosome_density_summary(
            db=db, release_context=_context()
        )
    finally:
        mod.get_or_set = original

    assert seen[0]["params"] == {
        "release_id": _RELEASE_ID, "variant_visibility": "public-v2",
    }


# ---------------------------------------------------------------------------
# 3. PostgreSQL variant aggregates receive the release key.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_variant_type_distribution_passes_the_release_key():
    ch = _CapturingVariantService(result={"SNP": 2, "INS": 1})

    import app.api.v1.stats as mod

    original = mod.variant_service
    mod.variant_service = ch
    try:
        result = await stats_module.variant_type_distribution(
            release_context=_context(), assembly="Wm82.a4.v1"
        )
    finally:
        mod.variant_service = original

    assert ch.calls[0]["release_key"] == str(_RELEASE_ID)
    assert ch.calls[0]["assembly"] == "Wm82.a4.v1"
    assert result.snp_count == 2


def test_clickhouse_dashboard_query_binds_the_release_key():
    """The SQL must carry a bound release predicate, never a bare aggregate."""
    import inspect

    from app.services.clickhouse_service import ClickHouseService

    source = inspect.getsource(ClickHouseService.get_dashboard_stats)
    assert "release_key = %(release_key)s" in source
    assert "parameters=parameters" in source


def test_clickhouse_density_query_binds_the_release_key():
    import inspect

    from app.services.clickhouse_service import ClickHouseService

    source = inspect.getsource(ClickHouseService.get_chromosome_density)
    assert "release_key = %(release_key)s" in source


# ---------------------------------------------------------------------------
# 4. Public release statistics list published releases only.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_statistics_is_published_only():
    """Ablation: the default used to list drafts and rolled-back releases."""
    db = _RecordingDb(results=[])
    seen: list[str] = []

    async def _fake_get_or_set(key, ttl, *, loader, params=None):
        seen.append(key)
        return await loader()

    import app.api.v1.stats as mod

    original = mod.get_or_set
    mod.get_or_set = _fake_get_or_set
    try:
        await stats_module.release_statistics(db=db)
    finally:
        mod.get_or_set = original

    sql = db.sql(0)
    assert "releases.published_at IS NOT NULL" in sql, sql
    assert "releases.status" in sql, sql
    # No caller-supplied "include unpublished" switch remains.
    assert "only_active" not in seen[0]
