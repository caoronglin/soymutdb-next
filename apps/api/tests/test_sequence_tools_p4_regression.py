"""P4 regression: kernel semantics that HTTP-level happy paths miss.

These assertions are pinned against the REAL compiled wheel (CPython 3.15),
not a mock. They cover the traps found by differential testing of the P2/P3
service layer against ``packages/bio-core``:

* ``match.limited`` must distinguish "exactly at cap" from "truncated";
* a palindromic pattern is intentionally NOT de-duplicated across strands;
* RNA validation is asymmetric between reverse-complement and stats/kmers;
* k-mer ``max_items`` truncation is stable and reports ``limited``;
* ``mode='count'`` omits the per-record hit list (spec §7.3).

Tests that need the kernel are skipped (with a reason) when the wheel is
absent -- a missing wheel must never masquerade as a green result.
"""

from __future__ import annotations

import importlib.util

import pytest

from app.schemas import sequence_tools as s

WHEEL_AVAILABLE = importlib.util.find_spec("soymutdb_bio_core") is not None
requires_wheel = pytest.mark.skipif(
    not WHEEL_AVAILABLE, reason="compiled bio-core wheel not installed"
)


@requires_wheel
@pytest.mark.asyncio
async def test_match_limited_only_when_truly_truncated() -> None:
    """A result that exactly fills max_hits is NOT limited.

    Regression: the service used ``len(hits) >= max_hits``, which reported a
    false truncation whenever the hit count landed exactly on the cap.
    """
    from app.services import sequence_tools_service as service

    exactly_full = await service.match(
        s.SequenceMatchRequest(
            pattern="AA",
            target={"kind": "inline", "sequence": "AAAA"},
            both_strands=False,
            max_hits=3,
        )
    )
    assert exactly_full.count == 3
    assert exactly_full.limited is False, "exactly-at-cap must not be reported as truncated"

    truncated = await service.match(
        s.SequenceMatchRequest(
            pattern="AA",
            target={"kind": "inline", "sequence": "AAAA"},
            both_strands=False,
            max_hits=2,
        )
    )
    assert truncated.count == 2
    assert truncated.limited is True, "a real truncation must be reported"


@requires_wheel
@pytest.mark.asyncio
async def test_palindromic_pattern_is_not_deduplicated() -> None:
    """Forward and reverse hits are both returned for a palindromic pattern.

    The kernel does not test ``rc_pat == pat``; reporting a de-duplicated
    count here would silently disagree with the compiled engine.
    """
    from app.services import sequence_tools_service as service

    result = await service.match(
        s.SequenceMatchRequest(
            pattern="ACGT",
            target={"kind": "inline", "sequence": "ACGTACGT"},
            both_strands=True,
            max_hits=100,
        )
    )
    assert result.count == 4, "2 forward + 2 reverse hits, not 2 de-duplicated"
    assert {h.strand for h in result.matches} == {"+", "-"}


@requires_wheel
@pytest.mark.asyncio
async def test_rna_validation_paths_are_intentionally_asymmetric() -> None:
    """RNA stats/kmers reject T; reverse-complement's table still maps T->A.

    Do not 'fix' this into one shared validator: the two paths are separate
    contracts in the kernel and the difference is deliberate.
    """
    import soymutdb_bio_core as core

    # stats uses validate_sequence; the RNA allowed set excludes T.
    with pytest.raises(core.BioCoreException) as exc:
        core.sequence_statistics("ACGT", "rna", True)
    assert exc.value.args[0] == "INVALID_CHARACTER"

    # reverse_complement uses complement_byte; its RNA table maps T -> A and
    # A -> U, so it accepts a T that stats would reject. Do NOT collapse these
    # two validators into one: the asymmetry is a real kernel contract.
    assert core.reverse_complement("ACGT", alphabet="rna") == "ACGU"
    # U is counted in the T bucket; denominator excludes ambiguous bases.
    stats = core.sequence_statistics("AUG", "rna", True)
    assert stats["t"] == 1
    assert stats["denominator"] == 3


@requires_wheel
@pytest.mark.asyncio
async def test_kmer_max_items_truncation_is_stable() -> None:
    """max_items caps distinct kmers, flags limited, and keeps a stable sort."""
    from app.services import sequence_tools_service as service

    full = await service.kmers(
        s.KmerRequest(sequence="ACGTACGTNACG", k=4, canonical=True, max_items=1000)
    )
    assert (full.total_windows, full.valid_windows, full.skipped_windows) == (9, 5, 4)
    assert full.distinct_kmers == 3
    assert full.limited is False

    capped = await service.kmers(
        s.KmerRequest(sequence="ACGTACGTNACG", k=4, canonical=True, max_items=1)
    )
    assert capped.limited is True
    assert len(capped.items) == 1
    assert capped.distinct_kmers == 3, "distinct count is the full distinct count"
    # Stable order: count desc, then kmer asc. Two kmers have count 2, so the
    # lexicographically smaller one wins the single slot.
    assert capped.items[0].kmer == "ACGT"
    assert capped.items[0].count == 2


@requires_wheel
@pytest.mark.asyncio
async def test_interval_count_mode_omits_hits() -> None:
    """spec §7.3: mode='count' can omit the per-record hit list."""
    from app.services import interval_overlap_service as service
    from app.services.release_context import ReleaseContext

    class _Gene:
        def __init__(self, start: int, end: int, accession: str) -> None:
            self.start, self.end, self.accession = start, end, accession
            self.gene_pk = 999

    class _Result:
        def __init__(self, value) -> None:
            self._value = value

        def scalar_one_or_none(self):
            return self._value

        def scalars(self):
            return self

        def all(self):
            return self._value

    class _FakeDb:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            if self.calls == 1:
                class _A:
                    id, name, version, release_id = 7, "GmWm82.a2.v1", "a2.v1", 11
                return _Result(_A())
            if self.calls == 2:
                class _C:
                    id, name = 3, "chr1"
                return _Result(_C())
            return _Result([_Gene(10, 20, "Glyma.01G000100")])

    ctx = ReleaseContext(release_id=11, assembly_id=7, assembly="GmWm82.a2.v1")
    base = dict(assembly="GmWm82.a2.v1", reference_name="chr1",
                regions=[s.IntervalRegion(start=10, end=20)])

    hits = await service.overlap(_FakeDb(), s.OverlapRequest(**base, mode="hits"), ctx)
    count = await service.overlap(_FakeDb(), s.OverlapRequest(**base, mode="count"), ctx)

    assert hits.queries[0].hits, "hits mode must return per-record data"
    # Kernel hits are 0-based half-open [start0, end0). The service converts
    # back to 1-based inclusive as start0+1 / end0. Pin BOTH ends: a future
    # change that returned an exclusive end0 would silently lose the last base.
    for hit in hits.queries[0].hits:
        assert hit.start == 10, f"start0+1 must be 10, got {hit.start}"
        assert hit.end == 20, f"end0 is the 1-based inclusive end, got {hit.end}"
        assert hit.overlap_bp == 11, "overlap of [10,20] with itself is 11 bp"
    assert count.queries[0].hits is None, "count mode must omit the hit list"
    assert count.queries[0].hits != [], "an omitted list is not an empty list"
    # The count/coverage aggregates are still present and identical.
    assert count.queries[0].overlap_count == hits.queries[0].overlap_count
    assert count.queries[0].covered_bp == hits.queries[0].covered_bp
