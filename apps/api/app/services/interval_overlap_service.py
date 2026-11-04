"""Published-gene interval overlap, backed by the Rust rust-lapper index.

The Python layer is the sole owner of visibility decisions:

* the assembly is resolved by name and must carry the *published*
  ReleaseContext's release_id -- this is the release boundary, because ``Gene``
  has no ``release_id`` column of its own (only ``Assembly`` and
  ``GeneCrosswalk`` do);
* only genes of that (assembly, chromosome) are read from PostgreSQL;
* only public accessions are returned — never the private ``gene_pk``;
* an unresolved assembly / unpublished release fails closed with 404/503.

Nothing the client sends (a table name, a file path, a dataset id) can widen
the query.  The Rust kernel receives only validated half-open integer tuples.
"""

from __future__ import annotations

import anyio.to_thread
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import NotFoundError
from ..models.genomic import Assembly, Chromosome, Gene
from ..schemas import sequence_tools as s
from ..services.release_context import ReleaseContext
from . import bio_core_bridge as bridge


def _engine_meta() -> s.EngineMetadata:
    st = bridge.status()
    return s.EngineMetadata(
        engine=st.engine or "unavailable",
        engine_version=st.engine_version or "unavailable",
    )


async def overlap(
    db: AsyncSession,
    payload: s.OverlapRequest,
    release_context: ReleaseContext,
) -> s.OverlapResponse:
    core = bridge.require()

    assembly = (
        await db.execute(
            select(Assembly).where(
                Assembly.name == payload.assembly,
                Assembly.release_id == release_context.release_id,
            )
        )
    ).scalar_one_or_none()
    if assembly is None:
        raise NotFoundError(
            f"Assembly {payload.assembly!r} is not published in the active release"
        )

    chromosome = (
        await db.execute(
            select(Chromosome).where(
                Chromosome.assembly_id == assembly.id,
                Chromosome.name == payload.reference_name,
            )
        )
    ).scalar_one_or_none()
    if chromosome is None:
        raise NotFoundError(
            f"Reference {payload.reference_name!r} not found in assembly {payload.assembly!r}"
        )

    # All regions share one chromosome; query the smallest bounding span once.
    lo = min(r.start for r in payload.regions)
    hi = max(r.end for r in payload.regions)
    genes = list(
        (
            await db.execute(
                select(Gene)
                .where(Gene.assembly_id == assembly.id)
                .where(Gene.chromosome_id == chromosome.id)
                .where(Gene.start <= hi)
                .where(Gene.end >= lo)
                .order_by(Gene.start, Gene.gene_pk)
            )
        )
        .scalars()
        .all()
    )

    # 1-based inclusive DB coordinates -> 0-based half-open for the kernel.
    intervals: list[tuple[int, int, int]] = [
        (int(g.start) - 1, int(g.end), idx) for idx, g in enumerate(genes)
    ]
    half_open_regions: list[tuple[int, int]] = [
        (int(r.start) - 1, int(r.end)) for r in payload.regions
    ]

    if intervals:
        try:
            raw = await anyio.to_thread.run_sync(
                lambda: core.overlap_intervals(
                    intervals, half_open_regions, payload.max_hits
                )
            )
        except core.BioCoreException as exc:
            raise bridge.translate_error(exc) from exc
    else:
        raw = [
            {
                "overlap_count": 0,
                "covered_bp": 0,
                "limited": False,
                "hits": [],
            }
            for _ in payload.regions
        ]

    # spec §7.3: mode='count' omits the hit list. The overlap_count and
    # covered_bp are still computed by the kernel (they are cheap and distinct
    # metrics), but no per-record payload is shaped for a count-only request.
    include_hits = payload.mode == "hits"
    queries: list[s.OverlapQueryResult] = []
    for region, q in zip(payload.regions, raw):
        hits = [
            s.OverlapHit(
                public_id=genes[h[3]].accession,
                # Convert the hit interval back to 1-based inclusive.
                start=int(h[0]) + 1,
                end=int(h[1]),
                overlap_bp=int(h[2]),
                source=assembly.version,
            )
            for h in q["hits"]
            if int(h[3]) < len(genes)
        ] if include_hits else None
        queries.append(
            s.OverlapQueryResult(
                query=region,
                overlap_count=int(q["overlap_count"]),
                covered_bp=int(q["covered_bp"]),
                hits=hits,
                limited=bool(q["limited"]),
            )
        )

    return s.OverlapResponse(
        assembly=assembly.name,
        release=release_context.release_key,
        queries=queries,
        engine=_engine_meta(),
    )
