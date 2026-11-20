"""Service integration layer between FastAPI and the Rust bio-core wheel.

Every method validates at the Pydantic boundary first, then delegates the
pure-CPU work to the compiled extension inside a worker thread so FastAPI's
event loop is never blocked.  Authorization, release context and provenance
stay in Python; the kernel never sees a DB credential or a path.
"""

from __future__ import annotations

import anyio.to_thread

from ..schemas import sequence_tools as s
from . import bio_core_bridge as bridge


def _engine_meta() -> s.EngineMetadata:
    st = bridge.status()
    return s.EngineMetadata(
        engine=st.engine or "unavailable",
        engine_version=st.engine_version or "unavailable",
    )


def _call(fn, *args, **kwargs):
    """Run a kernel call in a thread, mapping failures to the error envelope."""
    core = bridge.require()
    try:
        return getattr(core, fn)(*args, **kwargs)
    except core.BioCoreException as exc:
        raise bridge.translate_error(exc) from exc


async def reverse_complement(req: s.ReverseComplementRequest) -> s.ReverseComplementResponse:
    out = await anyio.to_thread.run_sync(
        lambda: _call("reverse_complement", req.sequence, req.alphabet, req.preserve_case)
    )
    return s.ReverseComplementResponse(
        sequence=out,
        length=len(out),
        alphabet=req.alphabet,
        engine=_engine_meta(),
    )


async def match(req: s.SequenceMatchRequest) -> s.SequenceMatchResponse:
    raw = await anyio.to_thread.run_sync(
        lambda: _call(
            "find_matches",
            req.target.sequence,
            req.pattern,
            req.alphabet,
            req.mode,
            req.both_strands,
            req.max_edits if req.mode == "approximate" else 0,
            # Probe one past the cap so "exactly full" is not reported as a
            # truncated result.  The kernel caps the returned Vec but does not
            # tell us whether more hits existed; asking for max_hits+1 makes
            # the distinction observable.  The extra hit is dropped before the
            # response is shaped, so the caller still sees exactly its cap.
            req.max_hits + 1,
        )
    )
    limited = len(raw) > req.max_hits
    raw = raw[: req.max_hits]
    hits = [
        s.MatchHit(
            start=h["start"],
            end=h["end"],
            strand=h["strand"],
            edit_distance=h["edit_distance"],
        )
        for h in raw
    ]
    return s.SequenceMatchResponse(
        matches=hits,
        count=len(hits),
        limited=limited,
        method=req.mode,
        engine=_engine_meta(),
    )


async def align(req: s.SequenceAlignRequest) -> s.SequenceAlignResponse:
    sc = req.scoring
    raw = await anyio.to_thread.run_sync(
        lambda: _call(
            "align_pairwise",
            req.query,
            req.target,
            req.alphabet,
            req.mode,
            sc.match,
            sc.mismatch,
            sc.gap_open,
            sc.gap_extend,
        )
    )
    return s.SequenceAlignResponse(
        score=raw["score"],
        query_range=tuple(raw["query_range"]),
        target_range=tuple(raw["target_range"]),
        cigar=raw["cigar"],
        identity=raw["identity"],
        mode=req.mode,
        engine=_engine_meta(),
    )


async def stats(req: s.SequenceStatsRequest) -> s.SequenceStatsResponse:
    raw = await anyio.to_thread.run_sync(
        lambda: _call(
            "sequence_statistics",
            req.sequence,
            req.alphabet,
            req.ambiguous_gc_policy == "exclude",
        )
    )
    return s.SequenceStatsResponse(**raw, engine=_engine_meta())


async def orfs(req: s.OrfRequest) -> s.OrfResponse:
    raw = await anyio.to_thread.run_sync(
        lambda: _call("find_orfs", req.sequence, req.min_len, req.limit)
    )
    items = [
        s.OrfCandidate(
            start=o["start"],
            end=o["end"],
            strand=o["strand"],
            frame=o["frame"],
        )
        for o in raw
    ]
    return s.OrfResponse(candidates=items, count=len(items), engine=_engine_meta())


async def translate(req: s.TranslateRequest) -> s.TranslateResponse:
    raw = await anyio.to_thread.run_sync(
        lambda: _call("translate_sequence", req.sequence, req.genetic_code_id, req.frame)
    )
    return s.TranslateResponse(**raw, engine=_engine_meta())


async def kmers(req: s.KmerRequest) -> s.KmerResponse:
    raw = await anyio.to_thread.run_sync(
        lambda: _call(
            "kmer_counts",
            req.sequence,
            req.k,
            req.canonical,
            req.ambiguity_policy,
            req.max_items,
        )
    )
    items = [s.KmerItem(kmer=k, count=c) for k, c in raw["items"]]
    return s.KmerResponse(
        k=raw["k"],
        canonical=raw["canonical"],
        total_windows=raw["total_windows"],
        valid_windows=raw["valid_windows"],
        skipped_windows=raw["skipped_windows"],
        distinct_kmers=raw["distinct_kmers"],
        items=items,
        limited=raw["limited"],
        engine=_engine_meta(),
    )


def capabilities() -> s.SequenceCapabilitiesResponse:
    """Advertise the limits the kernel enforces, with or without the engine.

    The numeric limits fall back to the Pydantic defaults (which mirror the Rust
    ``pub const`` values). They are deliberately NOT read from
    ``bridge.require()``: this endpoint must answer when the wheel is missing,
    reporting ``available: false`` plus a reason instead of a 503.

    Keeping ``SequenceCapabilitiesResponse`` in step with the keys the kernel
    advertises is enforced by ``scripts/check_bio_core_capability_parity.py``.
    A bound the kernel enforces but this response omits is invisible to a
    value-by-value comparison, so that guard also compares key presence.
    """
    st = bridge.status()
    payload = s.SequenceCapabilitiesResponse(
        available=st.available,
        engine=st.engine,
        engine_version=st.engine_version,
        reason=st.reason,
    )
    # Report the capability set of the engine that is actually loaded. The
    # compiled kernel answers code 1 and nine programs; the Biopython engine
    # carries the full codon-table set and six more operations. A client reads
    # this instead of inferring the difference from a 404.
    if st.available:
        advertised = bridge.advertised_capabilities()
        if advertised:
            payload.genetic_codes = advertised.get("genetic_codes", payload.genetic_codes)
            payload.programs = advertised.get("programs", payload.programs)
    return payload


# ---------------------------------------------------------------------------
# Capabilities beyond the original kernel. Each one validates at the Pydantic
# boundary and delegates to the engine in a worker thread, exactly like the
# operations above, so the event loop is never blocked.
# ---------------------------------------------------------------------------


async def convert_format(req: s.ConvertFormatRequest) -> s.ConvertFormatResponse:
    raw = await anyio.to_thread.run_sync(
        lambda: _call(
            "convert_format",
            req.data,
            req.source_format,
            req.target_format,
            req.max_records,
        )
    )
    return s.ConvertFormatResponse(**raw, engine=_engine_meta())


async def restriction_sites(req: s.RestrictionRequest) -> s.RestrictionResponse:
    raw = await anyio.to_thread.run_sync(
        lambda: _call(
            "restriction_sites",
            req.sequence,
            req.enzymes or None,
            req.circular,
            req.max_hits,
        )
    )
    return s.RestrictionResponse(
        sequence_length=raw["sequence_length"],
        circular=raw["circular"],
        enzyme_count=raw["enzyme_count"],
        total_cut_sites=raw["total_cut_sites"],
        enzymes=[s.RestrictionEnzymeResult(**item) for item in raw["enzymes"]],
        limited=raw["limited"],
        engine=_engine_meta(),
    )


async def protein_properties(
    req: s.ProteinPropertiesRequest,
) -> s.ProteinPropertiesResponse:
    raw = await anyio.to_thread.run_sync(
        lambda: _call("protein_properties", req.protein)
    )
    return s.ProteinPropertiesResponse(**raw, engine=_engine_meta())


async def melting_temp(req: s.MeltingTempRequest) -> s.MeltingTempResponse:
    raw = await anyio.to_thread.run_sync(
        lambda: _call(
            "melting_temp",
            req.sequence,
            req.method,
            req.dna_conc_nm,
            req.salt_conc_mm,
        )
    )
    return s.MeltingTempResponse(**raw, engine=_engine_meta())


async def multiple_alignment(
    req: s.MultipleAlignmentRequest,
) -> s.MultipleAlignmentResponse:
    raw = await anyio.to_thread.run_sync(
        lambda: _call(
            "multiple_alignment",
            req.sequences,
            req.alphabet,
            req.mode,
        )
    )
    return s.MultipleAlignmentResponse(**raw, engine=_engine_meta())


async def neighbor_joining_tree(req: s.TreeRequest) -> s.TreeResponse:
    raw = await anyio.to_thread.run_sync(
        lambda: _call(
            "neighbor_joining_tree",
            req.sequences,
            req.labels,
            req.alphabet,
        )
    )
    return s.TreeResponse(**raw, engine=_engine_meta())
