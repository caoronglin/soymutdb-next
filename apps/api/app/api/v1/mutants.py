"""Mutant line endpoints.

External/public contract: the canonical identity is ``public_id``. The
private persistence key is never accepted as a locator and never appears
in responses. Records that are non-public, deleted, or missing a
``public_id`` are treated uniformly as not found (no existence oracle).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import NotFoundError
from ...core.public_ids import normalize_public_id
from ...models.variant import MutantLine, Phenotype, VariantSummary
from ...schemas.variant import MutantLineDetail, MutantLineResponse, PhenotypeResponse
from ...services.release_context import ReleaseContext, get_release_context
from ...services.sql_like import LIKE_ESCAPE_CHARACTER, contains_pattern

router = APIRouter(prefix="/mutants", tags=["mutants"])

#: Maximum length of the free-text ``q`` filter, in characters.
_MAX_QUERY_LENGTH = 200


def _visible_public_conditions(release_id: int):
    """Filters shared by every public mutant entry point.

    A record is publicly visible only when it belongs to the currently
    resolved published release. Rows attached to a draft/other release or
    with ``release_id IS NULL`` are excluded, so an unpublished draft can
    never surface through a public route.
    """
    return (
        MutantLine.is_deleted.is_(False),
        MutantLine.is_public.is_(True),
        MutantLine.public_id.is_not(None),
        MutantLine.release_id == release_id,
    )


@router.get("", response_model=list[MutantLineResponse])
async def list_mutant_lines(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    mutagen: str | None = Query(default=None),
    q: Annotated[str | None, Query(max_length=_MAX_QUERY_LENGTH)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[MutantLineResponse]:
    """List public mutant lines from the active published release.

    ``mutagen`` keeps its historical *exact* match semantics. ``q`` is an
    additive free-text filter that matches a case-insensitive substring of
    the public identifier, the name, the cultivar or the mutagen; it narrows
    the very same release-scoped, public-only candidate set and never widens
    it.

    Both filters leave the response shape untouched: the endpoint still
    answers with a plain ``list[MutantLineResponse]`` (no envelope), so the
    existing clients keep working.
    """
    variant_count = func.count(VariantSummary.id).label("variant_count")
    stmt = (
        select(MutantLine, variant_count)
        .outerjoin(
            VariantSummary,
            (VariantSummary.mutant_line_id == MutantLine.id)
            & (VariantSummary.release_id == release_context.release_id),
        )
        .where(*_visible_public_conditions(release_context.release_id))
        .group_by(MutantLine.id)
        .order_by(func.lower(MutantLine.public_id), MutantLine.id)
        .offset(offset)
        .limit(limit)
    )
    if mutagen is not None:
        stmt = stmt.where(MutantLine.mutagen == mutagen)
    query_text = q.strip() if q else ""
    if query_text:
        # The user's text is turned into a *literal* pattern by the shared
        # helper: a search for "%" must not become "match every row".
        pattern = contains_pattern(query_text)
        stmt = stmt.where(
            or_(
                # The public identifier is the identity the page displays and
                # the one a user copies out of it, so it has to be searchable
                # with the same box that searches the names.
                MutantLine.public_id.ilike(pattern, escape=LIKE_ESCAPE_CHARACTER),
                MutantLine.name.ilike(pattern, escape=LIKE_ESCAPE_CHARACTER),
                MutantLine.cultivar.ilike(pattern, escape=LIKE_ESCAPE_CHARACTER),
                MutantLine.mutagen.ilike(pattern, escape=LIKE_ESCAPE_CHARACTER),
            )
        )
    result = await db.execute(stmt)
    return [_to_response(ml, count) for ml, count in result.all()]


@router.get("/{public_id}", response_model=MutantLineDetail)
async def get_mutant_line(
    public_id: str,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> MutantLineDetail:
    """Get a public mutant line by its public identifier.

    Any value that does not correspond to a visible public record yields
    the same not-found response — including existing internal identifiers.
    """
    variant_count = func.count(VariantSummary.id).label("variant_count")
    result = await db.execute(
        select(MutantLine, variant_count)
        .outerjoin(
            VariantSummary,
            (VariantSummary.mutant_line_id == MutantLine.id)
            & (VariantSummary.release_id == release_context.release_id),
        )
        .where(
            func.upper(MutantLine.public_id) == normalize_public_id(public_id),
            *_visible_public_conditions(release_context.release_id),
        )
        .group_by(MutantLine.id)
    )
    row = result.one_or_none()
    if row is None:
        raise NotFoundError(f"Mutant line {public_id} not found")
    ml, count = row
    return _to_detail(ml, count)


@router.get("/{public_id}/phenotypes", response_model=list[PhenotypeResponse])
async def get_phenotypes(
    public_id: str,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> list[PhenotypeResponse]:
    """List phenotypes for a public mutant line in the active release."""
    visible_parent = await db.execute(
        select(MutantLine).where(
            func.upper(MutantLine.public_id) == normalize_public_id(public_id),
            *_visible_public_conditions(release_context.release_id),
        )
    )
    ml = visible_parent.scalar_one_or_none()
    if ml is None:
        raise NotFoundError(f"Mutant line {public_id} not found")

    result = await db.execute(
        select(Phenotype).where(Phenotype.mutant_line_id == ml.id)
    )
    return [
        PhenotypeResponse(
            id=str(p.id),
            mutant_line_public_id=ml.public_id or "",
            trait_category=p.trait_category,
            trait_name=p.trait_name,
            trait_value=p.trait_value,
            unit=p.unit,
            description=p.description,
        )
        for p in result.scalars().all()
    ]


def _to_response(ml: MutantLine, variant_count: int = 0) -> MutantLineResponse:
    return MutantLineResponse(
        public_id=ml.public_id or "",
        name=ml.name,
        mutagen=ml.mutagen,
        cultivar=ml.cultivar,
        variant_count=variant_count,
    )


def _to_detail(ml: MutantLine, variant_count: int = 0) -> MutantLineDetail:
    return MutantLineDetail(
        public_id=ml.public_id or "",
        name=ml.name,
        mutagen=ml.mutagen,
        cultivar=ml.cultivar,
        variant_count=variant_count,
        species=ml.species,
        description=ml.description,
        generation=ml.generation,
        phenotype_summary=ml.phenotype_summary,
        is_public=ml.is_public,
        created_at=ml.created_at,
        updated_at=ml.updated_at,
    )
