"""Mutant line endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import NotFoundError
from ...models.variant import MutantLine, Phenotype
from ...schemas.variant import MutantLineDetail, MutantLineResponse, PhenotypeResponse

router = APIRouter(prefix="/mutants", tags=["mutants"])


@router.get("", response_model=list[MutantLineResponse])
async def list_mutant_lines(
    db: AsyncSession = Depends(get_db),
    mutagen: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[MutantLineResponse]:
    """List mutant lines."""
    stmt = select(MutantLine).where(MutantLine.is_deleted.is_(False)).limit(limit)
    if mutagen is not None:
        stmt = stmt.where(MutantLine.mutagen == mutagen)
    result = await db.execute(stmt)
    return [_to_response(ml) for ml in result.scalars().all()]


@router.get("/{mutant_line_id}", response_model=MutantLineDetail)
async def get_mutant_line(
    mutant_line_id: int,
    db: AsyncSession = Depends(get_db),
) -> MutantLineDetail:
    """Get mutant line detail."""
    result = await db.execute(
        select(MutantLine).where(
            MutantLine.id == mutant_line_id, MutantLine.is_deleted.is_(False)
        )
    )
    ml = result.scalar_one_or_none()
    if ml is None:
        raise NotFoundError(f"Mutant line {mutant_line_id} not found")
    return _to_detail(ml)


@router.get("/{mutant_line_id}/phenotypes", response_model=list[PhenotypeResponse])
async def get_phenotypes(
    mutant_line_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[PhenotypeResponse]:
    """List phenotypes for a mutant line."""
    result = await db.execute(
        select(Phenotype).where(Phenotype.mutant_line_id == mutant_line_id)
    )
    return [
        PhenotypeResponse(
            id=str(p.id),
            mutant_line_id=str(p.mutant_line_id),
            trait_category=p.trait_category,
            trait_name=p.trait_name,
            trait_value=p.trait_value,
            unit=p.unit,
            description=p.description,
        )
        for p in result.scalars().all()
    ]


def _to_response(ml: MutantLine) -> MutantLineResponse:
    return MutantLineResponse(
        id=str(ml.id),
        name=ml.name,
        mutagen=ml.mutagen,
        cultivar=ml.cultivar,
        variant_count=0,
    )


def _to_detail(ml: MutantLine) -> MutantLineDetail:
    return MutantLineDetail(
        id=str(ml.id),
        name=ml.name,
        mutagen=ml.mutagen,
        cultivar=ml.cultivar,
        species=ml.species,
        description=ml.description,
        generation=ml.generation,
        phenotype_summary=ml.phenotype_summary,
        is_public=ml.is_public,
        created_at=ml.created_at,
        updated_at=ml.updated_at,
    )
