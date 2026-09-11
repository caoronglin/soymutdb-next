"""Mutant line endpoints.

External/public contract: the canonical identity is ``public_id``. The
private persistence key is never accepted as a locator and never appears
in responses. Records that are non-public, deleted, or missing a
``public_id`` are treated uniformly as not found (no existence oracle).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import NotFoundError
from ...core.public_ids import normalize_public_id
from ...models.variant import MutantLine, Phenotype, VariantSummary
from ...schemas.variant import MutantLineDetail, MutantLineResponse, PhenotypeResponse

router = APIRouter(prefix="/mutants", tags=["mutants"])


def _visible_public_conditions():
    """Filters shared by every public mutant entry point."""
    return (
        MutantLine.is_deleted.is_(False),
        MutantLine.is_public.is_(True),
        MutantLine.public_id.is_not(None),
    )


@router.get("", response_model=list[MutantLineResponse])
async def list_mutant_lines(
    db: AsyncSession = Depends(get_db),
    mutagen: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[MutantLineResponse]:
    """List public mutant lines."""
    variant_count = func.count(VariantSummary.id).label("variant_count")
    stmt = (
        select(MutantLine, variant_count)
        .outerjoin(VariantSummary, VariantSummary.mutant_line_id == MutantLine.id)
        .where(*_visible_public_conditions())
        .group_by(MutantLine.id)
        .order_by(func.lower(MutantLine.public_id), MutantLine.id)
        .limit(limit)
    )
    if mutagen is not None:
        stmt = stmt.where(MutantLine.mutagen == mutagen)
    result = await db.execute(stmt)
    return [_to_response(ml, count) for ml, count in result.all()]


@router.get("/{public_id}", response_model=MutantLineDetail)
async def get_mutant_line(
    public_id: str,
    db: AsyncSession = Depends(get_db),
) -> MutantLineDetail:
    """Get a public mutant line by its public identifier.

    Any value that does not correspond to a visible public record yields
    the same not-found response — including existing internal identifiers.
    """
    variant_count = func.count(VariantSummary.id).label("variant_count")
    result = await db.execute(
        select(MutantLine, variant_count)
        .outerjoin(VariantSummary, VariantSummary.mutant_line_id == MutantLine.id)
        .where(
            func.upper(MutantLine.public_id) == normalize_public_id(public_id),
            *_visible_public_conditions(),
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
) -> list[PhenotypeResponse]:
    """List phenotypes for a public mutant line."""
    visible_parent = await db.execute(
        select(MutantLine).where(
            func.upper(MutantLine.public_id) == normalize_public_id(public_id),
            *_visible_public_conditions(),
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
