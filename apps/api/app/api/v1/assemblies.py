"""Assembly endpoints: the assemblies of the resolved release, with real counts.

Deliberately a top-level ``/assemblies`` resource rather than
``/genes/assemblies``. An assembly is not a gene, and ``Assembly.species`` is a
free-text column, so there is no species resource to nest this under either.

Nothing here reads ``Release.gene_count`` or any other denormalised counter: see
``AssemblyService`` for why that would report the whole release's genes once per
assembly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...schemas.genomic import AssemblyDetailResponse, AssemblySummaryResponse
from ...services.assembly_service import AssemblyService
from ...services.release_context import ReleaseContext, get_release_context

router = APIRouter(prefix="/assemblies", tags=["assemblies"])
service = AssemblyService()


@router.get("", response_model=list[AssemblySummaryResponse])
async def list_assemblies(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> list[AssemblySummaryResponse]:
    """List the resolved release's assemblies with their own aggregate counts.

    Not cached: an assembly with a wrong gene count is worse than an assembly
    fetched twice, and the numbers change when data is imported rather than on
    their own.
    """
    return await service.list_assemblies(db, release_id=release_context.release_id)


@router.get("/{assembly_id}", response_model=AssemblyDetailResponse)
async def get_assembly(
    assembly_id: int,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> AssemblyDetailResponse:
    """Return one assembly of the resolved release, with its chromosomes.

    A 404 is returned both for an unknown assembly and for one that belongs to
    another release: the endpoint reveals nothing about assemblies outside the
    resolved release.
    """
    return await service.get_assembly(
        db, assembly_id, release_id=release_context.release_id
    )
