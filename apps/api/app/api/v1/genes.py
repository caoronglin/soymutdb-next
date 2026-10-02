"""Gene endpoints: search, detail, transcripts, assemblies, chromosomes."""

from __future__ import annotations

import hashlib
import math

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import SoyMutDBError
from ...schemas.genomic import (
    AssemblyResponse,
    ChromosomeResponse,
    GeneDetail,
    GeneListParams,
    GeneListResponse,
    RegionStructureResponse,
)
from ...services.cache import get_or_set
from ...services.gene_service import GeneService
from ...services.genome_view_svg import (
    StructurePart,
    SvgFeature,
    SvgTheme,
    SvgTrack,
    Viewport,
    genome_view_cache_key,
    merge_exon_spans,
    render_genome_view_svg,
)
from ...services.release_context import ReleaseContext, get_release_context

router = APIRouter(prefix="/genes", tags=["genes"])

#: A window wider than this is refused rather than modelled: the endpoint
#: returns every transcript and segment it finds, and a whole-chromosome request
#: would be tens of megabytes of JSON that no browser view can draw anyway. The
#: portal's locus picker asks for 20 kb.
REGION_STRUCTURE_MAX_SPAN_BP = 5_000_000
service = GeneService()


@router.get("/assemblies", response_model=list[AssemblyResponse], tags=["assemblies"])
async def list_assemblies(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> list[AssemblyResponse]:
    """List only genome assemblies in the resolved published release.

    Read-hot query cached in Redis (default TTL) via cache-aside; a Redis
    failure degrades to a direct query.  An empty assembly list is cached as
    well (short-circuit for a freshly seeded database) — that empty-result
    caching is the anti-cache-penetration behaviour shared by every
    ``get_or_set`` call site: once a loader result (even an empty one) is
    stored, repeated requests no longer hit the database until the TTL
    expires.
    """
    payload = await get_or_set(
        f"genes:assemblies:release:{release_context.release_id}",
        ttl=None,
        loader=lambda: _load_assemblies(db, release_context.release_id),
    )
    return [AssemblyResponse.model_validate(item) for item in payload]


async def _load_assemblies(db: AsyncSession, release_id: int) -> list[dict]:
    """Fetch published-release assemblies for the Redis cache."""
    rows = await service.list_assemblies(db, release_id=release_id)
    return [AssemblyResponse.model_validate(row).model_dump(mode="json") for row in rows]


@router.get(
    "/assemblies/{assembly_id}/chromosomes",
    response_model=list[ChromosomeResponse],
    tags=["assemblies"],
)
async def list_chromosomes(
    assembly_id: int,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> list[ChromosomeResponse]:
    """List chromosomes only when the assembly belongs to this release."""
    return await service.list_chromosomes(
        db, assembly_id, release_id=release_context.release_id
    )


@router.get("", response_model=GeneListResponse)
async def list_genes(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    assembly_id: int | None = Query(default=None),
    chromosome: str | None = Query(default=None),
    biotype: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=500),
    q: str | None = Query(default=None, max_length=500),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
    sort_by: str = Query(default="gene_id"),
    sort_dir: str = Query(default="asc"),
) -> GeneListResponse:
    """List genes with cursor pagination or the portal's page contract."""
    try:
        params = GeneListParams(
        assembly_id=str(assembly_id) if assembly_id else None,
        chromosome=chromosome,
        biotype=biotype,
        search=search or q,
        cursor=cursor,
        limit=limit,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    except ValueError as exc:
        # An unknown sort column/direction is client input, not a server bug.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await service.list_genes(
        db,
        params,
        release_context=release_context,
    )


@router.get("/region-structure", response_model=RegionStructureResponse)
async def get_region_structure(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    assembly_id: int = Query(ge=1),
    chromosome: str = Query(min_length=1, max_length=64),
    start: int = Query(ge=1),
    end: int = Query(ge=1),
    include_parts: bool = Query(
        default=True,
        description="Include CDS/UTR segments. False returns gene bodies only.",
    ),
) -> RegionStructureResponse:
    """Every gene in a coordinate window, with its modelled structure.

    This is what the portal's own genome view needs in order to show a locus
    rather than a gene: the genes that overlap the window, each with its
    transcripts and their typed ``cds`` / ``utr5`` / ``utr3`` segments. Before
    this endpoint the only genome picture the API could produce was centred on
    one gene (``/{gene_id}/genome-view.svg``), so "what surrounds this insertion
    site" had no answer.

    Declared **before** ``/{gene_id}`` on purpose: FastAPI matches routes in
    declaration order, and the parameterised route would otherwise swallow
    ``region-structure`` as a gene accession and 404.
    """
    if end < start:
        raise HTTPException(status_code=422, detail="`end` must not be less than `start`")
    if end - start > REGION_STRUCTURE_MAX_SPAN_BP:
        raise HTTPException(
            status_code=422,
            detail=(
                f"window of {end - start} bp exceeds the "
                f"{REGION_STRUCTURE_MAX_SPAN_BP} bp limit; request a narrower region"
            ),
        )

    try:
        return await service.get_region_structure(
            db,
            assembly_id=assembly_id,
            chromosome=chromosome,
            start=start,
            end=end,
            include_parts=include_parts,
            release_context=release_context,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{gene_id}", response_model=GeneDetail)
async def get_gene(
    gene_id: str,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    assembly_id: int | None = Query(default=None),
) -> GeneDetail:
    """Get gene detail with transcripts and aliases.

    ``gene_id`` is the assembly-scoped accession. When it exists in
    multiple assemblies, ``assembly_id`` is required; the API returns an
    explicit disambiguation error otherwise.

    Domain errors (e.g. ``NotFoundError``) propagate to the error envelope;
    unexpected exceptions are converted to a 500 HTTP error so the client
    always receives a structured response.
    """
    try:
        return await service.get_gene(
            db,
            gene_id,
            release_context=release_context,
            assembly_id=assembly_id,
        )
    except SoyMutDBError:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="An unexpected error occurred"
        ) from exc


# --------------------------------------------------------------------------- #
# Pre-rendered genome view
# --------------------------------------------------------------------------- #

#: Server-side palette for the pre-rendered picture.
#
# A static image cannot read `theme.useToken()`, so the values are pinned here.
# `primary` is the resolved value of `brandTokens.primary` (`oklch(0.46 0.13 152)`,
# packages/ui-react/src/design-tokens.ts) after antd derives its palette; the
# neutrals and `warn` are antd's own defaults. They exist to keep the
# pre-rendered picture visually identical to the client-rendered one — the
# *algorithm* parity is pinned separately by test_genome_view_svg_parity.py.
GENOME_VIEW_THEME = SvgTheme(
    background="#fafafa",
    surface="#ffffff",
    text="#262626",
    text_secondary="#8c8c8c",
    border="#f0f0f0",
    primary="#2f6f4f",
    warn="#faad14",
)

#: Window padding and floor, mirroring FLANK_FRACTION / MIN_SPAN_BP in the
#: portal component so the cached picture frames the gene the same way.
GENOME_VIEW_FLANK_FRACTION = 0.25
GENOME_VIEW_MIN_SPAN_BP = 200
GENOME_VIEW_DEFAULT_WIDTH_PX = 1200

#: Pre-rendered pictures are immutable for a given key, so they may be cached
#: hard at the edge. `private` is deliberately NOT used: the picture is derived
#: from released public coordinates only.
GENOME_VIEW_CACHE_CONTROL = "public, max-age=600, s-maxage=3600, stale-while-revalidate=86400"


def _build_genome_view_tracks(
    *,
    gene_id: str,
    chromosome: str,
    start_pos: int,
    end_pos: int,
    strand: str,
    transcripts: list,
    sites: list,
    include: str,
) -> list[SvgTrack]:
    """Assemble the track list; mirrors the portal's track mapping."""
    tracks: list[SvgTrack] = [SvgTrack(id="ruler", label=chromosome, kind="ruler")]

    if include != "sites":
        # The union of the gene's exon spans becomes its gene model. Overlapping
        # or abutting exons merge; a real intron gap survives — never a
        # fabricated single transcript.
        exon_parts = tuple(
            StructurePart(start=start, end=end, kind="exon")
            for start, end in merge_exon_spans(
                [
                    (exon.start, exon.end)
                    for transcript in transcripts
                    for exon in (getattr(transcript, "exons", None) or [])
                ]
            )
        )
        body = SvgFeature(
            id=gene_id,
            start=start_pos,
            end=end_pos,
            kind="gene",
            label=gene_id,
            strand="-" if strand == "-" else "+",
            parts=exon_parts,
        )
        tracks.append(
            SvgTrack(
                id="gene",
                label=f"{gene_id}{f' ({strand})' if strand else ''}",
                kind="feature",
                features=(body,),
            )
        )
        # Only worth its own lane once there is more than the gene body itself.
        if len(transcripts) > 1:
            tracks.append(
                SvgTrack(
                    id="transcripts",
                    label=f"转录本 ({len(transcripts)})",
                    kind="feature",
                    features=tuple(
                        SvgFeature(
                            id=t.id,
                            start=t.start,
                            end=t.end,
                            kind="gene",
                            label=f"{t.name or t.id}{' · canonical' if t.is_canonical else ''}",
                        )
                        for t in transcripts
                    ),
                )
            )

    if include != "gene":
        tracks.append(
            SvgTrack(
                id="sites",
                label=f"Mutation sites ({len(sites)})",
                kind="feature",
                features=tuple(
                    SvgFeature(
                        id=site.source_site_key,
                        start=site.position,
                        end=site.position + 1,
                        kind="mutation",
                        label=f"{site.mutant_line_name} · {'高' if site.confidence == 'H' else '低'}",
                    )
                    for site in sites
                ),
            )
        )
    return tracks


@router.get(
    "/{gene_id}/genome-view.svg",
    response_class=Response,
    responses={200: {"content": {"image/svg+xml": {}}}},
)
async def get_gene_genome_view(
    gene_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    assembly_id: int | None = Query(default=None),
    width: int = Query(default=GENOME_VIEW_DEFAULT_WIDTH_PX, ge=200, le=4000),
    start: int | None = Query(default=None, ge=0),
    end: int | None = Query(default=None, ge=1),
    include: str = Query(default="all", pattern="^(all|gene|sites)$"),
) -> Response:
    """Serve the gene's genome picture as a finished SVG.

    Rendering this on the server removes the track layout from first paint and
    turns the picture into an ordinary cacheable image: the browser (and any
    shared cache) can reuse it across visits, and the gene page still shows a
    picture before its JavaScript has run.

    Window defaults to the gene body plus a quarter-span flank, matching the
    portal component. ``start``/``end`` override it for a zoomed request.
    """
    gene = await service.get_gene(
        db,
        gene_id,
        release_context=release_context,
        assembly_id=assembly_id,
    )

    try:
        from ...services.local_test_preview_service import (
            list_preview_mutation_sites_for_gene,
        )

        sites = await list_preview_mutation_sites_for_gene(db, gene_id=gene_id)
    except Exception:
        # The unpublished preview dataset may legitimately be absent; the gene
        # body is still a useful picture, so degrade to no mutation lane rather
        # than failing the request.
        sites = []

    span = max(GENOME_VIEW_MIN_SPAN_BP, gene.end_pos - gene.start_pos)
    # Math.round semantics on purpose: `round()` would banker's-round a .5 and
    # frame the gene one base pair off the portal's window.
    flank = int(math.floor(span * GENOME_VIEW_FLANK_FRACTION + 0.5))
    window_start = max(0, gene.start_pos - flank)
    window_end = gene.end_pos + flank
    if start is not None:
        window_start = start
    if end is not None:
        window_end = end
    if window_end <= window_start:
        raise HTTPException(
            status_code=422, detail="`end` must be greater than `start`"
        )

    assembly_label = gene.assembly_name or ""
    tracks = _build_genome_view_tracks(
        gene_id=gene.gene_id or gene_id,
        chromosome=gene.chromosome,
        start_pos=gene.start_pos,
        end_pos=gene.end_pos,
        strand=str(gene.strand),
        transcripts=list(gene.transcripts or []),
        sites=list(sites),
        include=include,
    )

    viewport = Viewport(
        assembly_key=assembly_label or gene.chromosome,
        ref_name=gene.chromosome,
        start=window_start,
        end=window_end,
    )
    svg = render_genome_view_svg(
        viewport=viewport,
        width_px=width,
        tracks=tracks,
        theme=GENOME_VIEW_THEME,
    )

    etag = '"' + hashlib.sha256(
        genome_view_cache_key(viewport, width, [t.id for t in tracks]).encode()
    ).hexdigest()[:32] + '"'
    headers = {
        "ETag": etag,
        "Cache-Control": GENOME_VIEW_CACHE_CONTROL,
        # The picture is data, never a document: this stops a crafted gene id or
        # label from ever being interpreted as markup by a browser.
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        "X-Content-Type-Options": "nosniff",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)

    return Response(content=svg, media_type="image/svg+xml", headers=headers)
