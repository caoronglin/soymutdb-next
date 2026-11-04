"""Gene service – search, detail, transcripts (PostgreSQL)."""

from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, lazyload

from ..core.exceptions import NotFoundError, ValidationError
from ..models.genomic import Assembly, Chromosome, Gene, Transcript
from ..models.variant import VariantSummary
from ..schemas.gene_evidence import EVIDENCE_KINDS, EvidenceTag
from ..schemas.genomic import (
    AssemblyResponse,
    ChromosomeResponse,
    ExonResponse,
    GeneDetail,
    GeneListParams,
    GeneListResponse,
    GeneResponse,
    RegionGeneResponse,
    RegionStructureResponse,
    RegionTranscriptResponse,
    TranscriptPartResponse,
    TranscriptResponse,
)
from .gene_detail_sections import load_gene_sections
from .release_context import (
    ReleaseContext,
    decode_bound_cursor,
    encode_bound_cursor,
)
from .sequence_availability import gene_sequence_availability
from .sql_like import LIKE_ESCAPE_CHARACTER, contains_pattern


def _public_transcript_id(tx: Transcript) -> str:
    """Stable, non-persistence identifier for a public transcript.

    The previous implementation returned ``str(tx.id)`` (a BIGSERIAL primary
    key) to anonymous callers, which leaked an internal row identity and made
    the value enumerate-able. The accession/name the annotation already
    publishes is the public identity; the surrogate key stays internal and is
    only used as a last-resort discriminator when an annotation has no name.
    """
    if tx.name:
        return str(tx.name)
    return f"transcript-{tx.gene.accession}-{tx.start}-{tx.end}-{tx.strand}"


def _cursor_filters(params: GeneListParams) -> dict[str, str]:
    return params.model_dump(
        mode="json",
        exclude={"cursor", "limit", "page", "page_size"},
        exclude_none=True,
    )


def _variant_count_subquery(release_id: int):
    """Correlated per-gene variant count for the resolved release + assembly.

    Correlated on ``Gene`` deliberately. The ``outerjoin + GROUP BY
    genes.gene_pk`` form cannot work here: ``Gene`` eager-loads its
    relationships (``lazy="joined"``), so the target list also carries
    ``releases_1`` / ``chromosomes_1`` / ``gene_data_cache_1`` columns that are
    not functionally dependent on the grouping key, and PostgreSQL rejects the
    statement with

        column "releases_1.id" must appear in the GROUP BY clause

    That is a 500 on every ``GET /genes`` -- and a statement-shape test that
    never executes the SQL cannot see it.
    """
    return (
        select(func.count(VariantSummary.id))
        .where(
            VariantSummary.gene_id == Gene.gene_pk,
            VariantSummary.release_id == release_id,
            VariantSummary.assembly_id == Gene.assembly_id,
        )
        .correlate(Gene)
        .scalar_subquery()
    )


#: Source strings that mean "a model called this gene, nobody checked it".
#: Kept as a branch of literal matches rather than a fuzzy match: a wrong guess
#: here would relabel a curated annotation as predicted.
_PREDICTED_SOURCE_MARKERS = (
    "augustus",
    "genesnap",
    "fgenesh",
    "maker",
    "predicted",
    "ab initio",
    "abinitio",
)

#: Source strings that mean a human reviewed this record.
_CURATED_SOURCE_MARKERS = ("curated", "reviewed", "swiss-prot", "uniprot")


def gene_model_evidence(gene: Gene) -> EvidenceTag | None:
    """Report how the gene model came to exist, or ``None`` when unknown.

    Reads only what the imported annotation actually carries (the GFF3
    ``attributes["source"]`` / ``attributes["evidence"]``), never the accession
    pattern. Returning ``None`` for a silent source is the point: guessing
    "predicted" from a gene id would put a claim on the page the data never
    made.
    """
    attributes = gene.attributes if isinstance(gene.attributes, dict) else {}
    declared = attributes.get("evidence")
    if isinstance(declared, str) and declared.strip():
        known = set(EVIDENCE_KINDS)
        candidate = declared.strip().lower()
        if candidate in known:
            return EvidenceTag(
                kind=candidate,
                source=str(attributes.get("source") or "annotation"),
            )
    source = attributes.get("source")
    if isinstance(source, str) and source.strip():
        lowered = source.strip().lower()
        if any(marker in lowered for marker in _CURATED_SOURCE_MARKERS):
            return EvidenceTag(kind="curated", source=source.strip())
        if any(marker in lowered for marker in _PREDICTED_SOURCE_MARKERS):
            return EvidenceTag(kind="predicted", source=source.strip())
        return EvidenceTag(kind="imported", source=source.strip())
    return None


def _order_by(params: GeneListParams, release_id: int):
    """Validated ORDER BY list for the gene list.

    Only columns from the closed allowlist reach SQL; the keyset cursor is
    defined for the default ``(accession, gene_pk)`` order, so any other sort
    uses the page-based contract (enforced in ``list_genes``).

    ``variant_count`` orders by the same correlated subquery the projection
    selects: a bare aggregate here would re-introduce the missing GROUP BY.
    """
    descending = params.sort_dir == "desc"
    column = {
        "gene_id": Gene.accession,
        "symbol": Gene.name,
        "variant_count": _variant_count_subquery(release_id),
    }[params.sort_by]
    primary = column.desc() if descending else column.asc()
    # gene_pk is the stable tiebreaker; keep it aligned with the primary
    # direction so equal keys do not interleave across pages.
    tie = Gene.gene_pk.desc() if descending else Gene.gene_pk.asc()
    return [primary, tie]


def encode_cursor(
    accession: str,
    gene_pk: int,
    *,
    release_context: ReleaseContext,
    params: GeneListParams,
) -> str:
    """Encode a release/filter-bound gene keyset cursor.

    The sort key is ``(accession, gene_pk)``: accessions repeat across
    assemblies, so the surrogate key is the stable tiebreaker.
    """
    return encode_bound_cursor(
        kind="gene",
        sort_key={"a": accession, "p": str(gene_pk)},
        release_context=release_context,
        filters=_cursor_filters(params),
    )


def decode_cursor(
    cursor: str,
    *,
    release_context: ReleaseContext,
    params: GeneListParams,
) -> tuple[str, int]:
    """Verify and decode a release/filter-bound gene keyset cursor."""
    try:
        payload = decode_bound_cursor(
            cursor,
            kind="gene",
            release_context=release_context,
            filters=_cursor_filters(params),
        )
        accession = payload["a"]
        gene_pk = payload["p"]
        if not isinstance(accession, str) or not accession:
            raise ValueError("gene accession must be a non-empty string")
        if not isinstance(gene_pk, str) or not gene_pk.isdigit():
            raise ValueError("gene pk must be a numeric string")
        return accession, int(gene_pk)
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"Invalid cursor: {exc}") from exc


PART_KIND_BY_TYPE: dict[str, str] = {
    "cds": "cds",
    "five_prime_utr": "utr5",
    "three_prime_utr": "utr3",
}


def _region_transcript(tx: Transcript, *, include_parts: bool) -> RegionTranscriptResponse:
    """Map one ORM transcript, translating ``part_type`` into the renderers' kind.

    The translation lives here rather than in the renderers so that the
    four-value vocabulary (``exon`` / ``cds`` / ``utr5`` / ``utr3``) is decided
    once, at the API boundary. Segments whose type falls outside the table are
    dropped instead of being guessed at as coding sequence — mislabelling a UTR
    as CDS would change how the picture reads.
    """
    parts: list[TranscriptPartResponse] = []
    if include_parts:
        for part in tx.parts:
            kind = PART_KIND_BY_TYPE.get(part.part_type)
            if kind is None:
                continue
            parts.append(TranscriptPartResponse(kind=kind, start=part.start, end=part.end))
    return RegionTranscriptResponse(
        id=tx.id,
        name=tx.name,
        biotype=tx.biotype,
        start=tx.start,
        end=tx.end,
        strand=tx.strand,
        is_canonical=tx.is_canonical,
        parts=parts,
    )


class GeneService:
    """Gene query service backed by PostgreSQL."""

    async def list_genes(
        self,
        db: AsyncSession,
        params: GeneListParams,
        *,
        release_context: ReleaseContext,
    ) -> GeneListResponse:
        """Return a cursor-paginated list of genes.

        Each row carries the number of variant summaries linked to the gene
        *within the resolved release and assembly*. The count previously came
        back as ``0`` for every row (the React table rendered an always-empty
        column) and an unscoped count would have spanned draft releases.
        """
        variant_count = _variant_count_subquery(release_context.release_id).label("variant_count")
        stmt = (
            select(Gene, variant_count)
            .join(Assembly, Gene.assembly_id == Assembly.id)
            .where(Assembly.release_id == release_context.release_id)
            .options(
                # The list response carries no transcript or alias data (the
                # projection below is GeneResponse, which has no such fields),
                # but ``Gene.transcripts`` and ``Gene.aliases`` are
                # ``selectin`` relationships: a 200-row page materialised
                # every transcript, exon, transcript part and alias of those
                # genes and then threw them away -- extra round trips plus the
                # joined back-references they drag along.
                #
                # The same holds for the assembly's own chromosome list, which
                # the list response never renders either (it names the gene's
                # own chromosome, not the assembly's set). ``joinedload`` keeps
                # the assembly in the very same statement -- it is already
                # joined -- and the chained ``lazyload`` is what stops the
                # assembly's ``selectin`` chromosomes from being fetched.
                #
                # ``lazyload`` keeps the mapper's default for every other
                # path -- the detail endpoint still eager-loads transcripts,
                # exons, parts and aliases exactly as before -- and only
                # suppresses the eager load for this one statement. It is the
                # 2.1 replacement for the deprecated ``noload`` strategy.
                lazyload(Gene.transcripts),
                lazyload(Gene.aliases),
                joinedload(Gene.assembly).lazyload(Assembly.chromosomes),
            )
        )

        if params.assembly_id is not None:
            stmt = stmt.where(Gene.assembly_id == int(params.assembly_id))
        if params.chromosome is not None:
            # genes stores a chromosome_id FK; filter via the joined name.
            stmt = stmt.join(Chromosome, Gene.chromosome_id == Chromosome.id).where(
                Chromosome.name == params.chromosome
            )
            if params.assembly_id is not None:
                # same chromosome names exist across assemblies.
                stmt = stmt.where(Chromosome.assembly_id == int(params.assembly_id))
        if params.biotype is not None:
            stmt = stmt.where(Gene.biotype == params.biotype)
        if params.search:
            # The user's text is matched *literally*. Interpolating it raw made
            # the search a LIKE program: "%" matched every gene and "_" matched
            # any single character (docs/dev/database-core-contract.md §6 item
            # 6 asks for a literal "%" / "_" fixture for exactly this reason).
            # A pattern made only of wildcards also carries no trigram, so the
            # planner could not use the trigram indexes either.
            pattern = contains_pattern(params.search)
            stmt = stmt.where(
                or_(
                    Gene.accession.ilike(pattern, escape=LIKE_ESCAPE_CHARACTER),
                    Gene.name.ilike(pattern, escape=LIKE_ESCAPE_CHARACTER),
                    Gene.description.ilike(pattern, escape=LIKE_ESCAPE_CHARACTER),
                )
            )

        page_size = params.page_size or params.limit
        total = 0
        if params.page is not None:
            # Count the filtered gene set, not the grouped variant projection:
            # a gene with no linked variants still belongs in the total.
            count_stmt = select(func.count()).select_from(
                stmt.order_by(None).with_only_columns(Gene.gene_pk).subquery()
            )
            total = int(await db.scalar(count_stmt) or 0)

        # Keyset pagination on (accession, gene_pk) — accessions repeat
        # across assemblies, the surrogate key is the stable tiebreaker. The
        # cursor encodes that one order, so it is only honoured for the default
        # sort; silently replaying it under a different ORDER BY would skip or
        # repeat rows.
        if params.cursor and (params.sort_by != "gene_id" or params.sort_dir != "asc"):
            raise ValidationError(
                "Cursor pagination is only available for the default gene order "
                "(sort_by=gene_id, sort_dir=asc); use page/page_size instead.",
                details={
                    "code": "cursor_requires_default_order",
                    "sort_by": params.sort_by,
                    "sort_dir": params.sort_dir,
                },
            )
        if params.cursor:
            last_accession, last_pk = decode_cursor(
                params.cursor,
                release_context=release_context,
                params=params,
            )
            stmt = stmt.where(
                or_(
                    Gene.accession > last_accession,
                    and_(
                        Gene.accession == last_accession,
                        Gene.gene_pk > last_pk,
                    ),
                )
            )

        stmt = stmt.order_by(*_order_by(params, release_context.release_id))
        if params.page is not None:
            stmt = stmt.offset((params.page - 1) * page_size).limit(page_size)
        else:
            stmt = stmt.limit(params.limit + 1)
        result = await db.execute(stmt)
        rows = list(result.all())
        genes = [gene for gene, _count in rows]

        has_more = (
            len(genes) > params.limit if params.page is None else params.page * page_size < total
        )
        if has_more and params.page is None:
            genes = genes[: params.limit]

        items = [self._gene_to_response(gene, count) for gene, count in rows[: len(genes)]]
        next_cursor = (
            encode_cursor(
                genes[-1].accession,
                genes[-1].gene_pk,
                release_context=release_context,
                params=params,
            )
            if has_more and genes
            else None
        )

        page = params.page or 1
        return GeneListResponse(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            page=page,
            page_size=page_size,
            total=total if params.page is not None else len(items),
            total_pages=(total + page_size - 1) // page_size if total else 0,
        )

    async def get_gene(
        self,
        db: AsyncSession,
        gene_id: str,
        *,
        release_context: ReleaseContext,
        assembly_id: int | None = None,
    ) -> GeneDetail:
        """Fetch one gene without crossing the selected data release.

        ``gene_id`` is the assembly-scoped accession. When the same
        accession exists in multiple searchable assemblies and no
        ``assembly_id`` was supplied, the request fails with an explicit
        disambiguation error instead of silently choosing a version.
        """
        conditions = [
            Gene.accession == gene_id,
            Assembly.release_id == release_context.release_id,
        ]
        if assembly_id is not None:
            conditions.append(Gene.assembly_id == int(assembly_id))
        stmt = (
            select(Gene)
            .join(Assembly, Gene.assembly_id == Assembly.id)
            .where(and_(*conditions))
            .order_by(Gene.gene_pk)
        )
        result = await db.execute(stmt)
        genes = list(result.scalars().all())
        if not genes:
            raise NotFoundError(f"Gene {gene_id} not found")
        if len(genes) > 1:
            raise ValidationError(
                f"Gene {gene_id} exists in multiple assemblies; supply an explicit assembly_id",
                details={
                    "code": "ambiguous_assembly",
                    "assemblies": [
                        {
                            "assembly_id": g.assembly_id,
                            "accession": g.accession,
                        }
                        for g in genes
                    ],
                },
            )
        gene = genes[0]

        # Transcripts + exons are eager-loaded via relationship.
        transcripts = [self._transcript_to_response(t) for t in gene.transcripts]
        aliases = [a.alias for a in gene.aliases]

        # The detail header renders this as the gene's variant total. It must be
        # scoped to the resolved release *and* the resolved assembly: an
        # unscoped count would include draft/other-release rows, and a
        # hardcoded 0 (the previous behaviour) made the UI stat meaningless.
        variant_count = int(
            await db.scalar(
                select(func.count())
                .select_from(VariantSummary)
                .where(
                    VariantSummary.gene_id == gene.gene_pk,
                    VariantSummary.release_id == release_context.release_id,
                    VariantSummary.assembly_id == gene.assembly_id,
                )
            )
            or 0
        )

        # Optional sections are assembled after the header so each one can
        # report its own presence (`empty` vs `not_imported`) instead of being
        # flattened into an empty list.
        sections = await load_gene_sections(db, gene, release_context=release_context)

        return GeneDetail(
            id=str(gene.accession),
            gene_id=str(gene.accession),
            assembly_id=str(gene.assembly_id),
            chromosome=gene.chromosome.name,
            name=gene.name,
            symbol=gene.name,
            biotype=gene.biotype,
            start=gene.start,
            end=gene.end,
            start_pos=gene.start,
            end_pos=gene.end,
            strand=gene.strand,
            description=gene.description,
            transcripts=transcripts,
            aliases=aliases,
            variant_count=variant_count,
            sequences=gene_sequence_availability(),
            model_evidence=gene_model_evidence(gene),
            **sections,
            created_at=gene.created_at,
            updated_at=gene.updated_at,
        )

    async def find_by_accessions(
        self,
        db: AsyncSession,
        accessions: list[str] | set[str],
        *,
        release_context: ReleaseContext | None = None,
        assembly_id: int | None = None,
    ) -> dict[str, list[Gene]]:
        """Resolve accessions to assembly-scoped gene rows.

        Returns a mapping accession → matching genes (possibly in several
        assemblies). Callers must disambiguate when a list holds more than
        one entry; they must not silently pick a version.
        """
        if not accessions:
            return {}
        stmt = select(Gene).where(Gene.accession.in_(list(accessions)))
        if release_context is not None:
            stmt = stmt.join(Assembly, Gene.assembly_id == Assembly.id).where(
                Assembly.release_id == release_context.release_id
            )
        if assembly_id is not None:
            stmt = stmt.where(Gene.assembly_id == int(assembly_id))
        result = await db.execute(stmt)
        mapping: dict[str, list[Gene]] = {}
        for gene in result.scalars().all():
            mapping.setdefault(gene.accession, []).append(gene)
        return mapping

    async def resolve_released_gene(
        self,
        db: AsyncSession,
        accession: str,
        *,
        release_context: ReleaseContext,
        assembly_id: int | None = None,
    ) -> Gene:
        """Resolve one accession inside the published release, or fail closed.

        Accessions repeat across assemblies, so an accession matching more than
        one *released* assembly is an explicit disambiguation error rather than
        a silent pick. Shared by the expression/homolog routes so the boundary
        rule has exactly one implementation.
        """
        resolved = await self.find_by_accessions(
            db,
            [accession],
            release_context=release_context,
            assembly_id=assembly_id,
        )
        matches = resolved.get(accession, [])
        if not matches:
            raise NotFoundError(f"Gene {accession} not found")
        if len(matches) > 1:
            raise ValidationError(
                f"Gene {accession} exists in multiple assemblies; supply an explicit assembly_id",
                details={"code": "ambiguous_assembly"},
            )
        return matches[0]

    async def get_region_structure(
        self,
        db: AsyncSession,
        *,
        assembly_id: int,
        chromosome: str,
        start: int,
        end: int,
        include_parts: bool = True,
        release_context: ReleaseContext,
    ) -> RegionStructureResponse:
        """Every gene overlapping a window, with its modelled structure.

        Overlap, not containment: a gene that merely crosses the window edge is
        part of the picture, and dropping it would leave a visible hole in the
        track.

        The window is scoped to one assembly on purpose. v4 and v5 are distinct
        coordinate namespaces, so the same ``Gm01:1,563,650`` names two
        different places in the genome and a query without an assembly would
        silently merge them.
        """
        assembly = (
            await db.execute(
                select(Assembly)
                .where(Assembly.id == assembly_id)
                .where(Assembly.release_id == release_context.release_id)
            )
        ).scalar_one_or_none()
        if assembly is None:
            raise NotFoundError(f"Assembly {assembly_id} not found in this release")

        chromosome_row = (
            await db.execute(
                select(Chromosome)
                .where(Chromosome.assembly_id == assembly_id)
                .where(Chromosome.name == chromosome)
            )
        ).scalar_one_or_none()
        if chromosome_row is None:
            raise NotFoundError(f"Chromosome {chromosome} not found in assembly {assembly_id}")

        genes = list(
            (
                await db.execute(
                    select(Gene)
                    .where(Gene.assembly_id == assembly_id)
                    .where(Gene.chromosome_id == chromosome_row.id)
                    .where(Gene.start <= end)
                    .where(Gene.end >= start)
                    .order_by(Gene.start, Gene.gene_pk)
                )
            )
            .scalars()
            .all()
        )

        return RegionStructureResponse(
            assembly_id=assembly.id,
            assembly_name=assembly.name,
            assembly_version=assembly.version,
            chromosome=chromosome_row.name,
            chromosome_length=chromosome_row.length,
            start=start,
            end=end,
            genes=[
                RegionGeneResponse(
                    gene_id=gene.accession,
                    name=gene.name,
                    chromosome=chromosome_row.name,
                    start=gene.start,
                    end=gene.end,
                    start_pos=gene.start,
                    end_pos=gene.end,
                    strand=gene.strand,
                    biotype=gene.biotype,
                    transcripts=[
                        _region_transcript(tx, include_parts=include_parts)
                        for tx in gene.transcripts
                    ],
                )
                for gene in genes
            ],
        )

    async def list_assemblies(self, db: AsyncSession, *, release_id: int) -> list[AssemblyResponse]:
        result = await db.execute(
            select(Assembly).where(Assembly.release_id == release_id).order_by(Assembly.name)
        )
        return [
            AssemblyResponse(
                id=str(a.id),
                name=a.name,
                species=a.species,
                version=a.version,
                description=a.description,
                is_default=a.is_default,
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
            for a in result.scalars().all()
        ]

    async def list_chromosomes(
        self, db: AsyncSession, assembly_id: int, *, release_id: int
    ) -> list[ChromosomeResponse]:
        """Chromosomes of one assembly, only when it belongs to this release.

        The existence check is separate from the row query on purpose. Filtering
        a join by ``Assembly.release_id`` and returning whatever came back makes
        an assembly outside the release answer ``200 + []``, which tells the
        caller "that assembly exists and has no chromosomes" -- a claim the data
        never made, and one that discloses the existence of unpublished rows.
        Unpublished and non-existent therefore share one 404, with no row data in
        the error, and no fallback to the default assembly (that would silently
        answer for a different coordinate namespace).
        """
        in_release = (
            await db.execute(
                select(Assembly.id)
                .where(Assembly.id == assembly_id)
                .where(Assembly.release_id == release_id)
            )
        ).scalar_one_or_none()
        if in_release is None:
            raise NotFoundError(f"Assembly {assembly_id} is not available")
        result = await db.execute(
            select(Chromosome)
            .where(Chromosome.assembly_id == assembly_id)
            .order_by(Chromosome.order)
        )
        return [
            ChromosomeResponse(
                id=str(c.id),
                assembly_id=str(c.assembly_id),
                name=c.name,
                length=c.length,
                order=c.order,
            )
            for c in result.scalars().all()
        ]

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _gene_to_response(gene: Gene, variant_count: int = 0) -> GeneResponse:
        return GeneResponse(
            id=str(gene.accession),
            gene_id=str(gene.accession),
            assembly_id=str(gene.assembly_id),
            assembly_name=gene.assembly.name if gene.assembly else None,
            chromosome=gene.chromosome.name,
            name=gene.name,
            symbol=gene.name,
            biotype=gene.biotype,
            start=gene.start,
            end=gene.end,
            start_pos=gene.start,
            end_pos=gene.end,
            strand=gene.strand,
            description=gene.description,
            variant_count=variant_count,
        )

    @staticmethod
    def _transcript_to_response(tx: Transcript) -> TranscriptResponse:
        return TranscriptResponse(
            id=_public_transcript_id(tx),
            gene_id=str(tx.gene.accession),
            name=tx.name,
            biotype=tx.biotype,
            start=tx.start,
            end=tx.end,
            strand=tx.strand,
            is_canonical=tx.is_canonical,
            exons=[
                ExonResponse(
                    id=f"{_public_transcript_id(tx)}.exon{e.order}",
                    start=e.start,
                    end=e.end,
                    order=e.order,
                )
                for e in tx.exons
            ],
        )
