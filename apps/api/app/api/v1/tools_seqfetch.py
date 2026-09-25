"""SeqFetch endpoints: extract FASTA sequences by gene ID or region.

Public tool – no authentication required (mirrors the public BLAST database
listing pattern; sequence retrieval from the reference FASTA exposes no
private data).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...schemas.seqfetch import SeqFetchRequest, SeqFetchResponse
from ...services.release_context import ReleaseContext, get_release_context
from ...services.seqfetch_service import SeqFetchService

router = APIRouter(prefix="/tools/seqfetch", tags=["tools"])
service = SeqFetchService()


@router.post("", response_model=SeqFetchResponse)
async def seqfetch(
    request: SeqFetchRequest,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> SeqFetchResponse:
    """Extract sequences for up to 200 gene IDs, or one chromosome interval.

    - ``{"genes": ["Glyma.01G000100", ...]}`` – batch mode; unknown IDs are
      skipped and reported in ``missing`` (never 404).
    - ``{"assembly": "GmWm82.a2.v1", "region": "chr1:1000-2000"}`` – single
      region mode.

    Results larger than 10 MiB are stored in S3 and returned with a
    pre-signed ``download_url`` (600 s) instead of inline FASTA.
    """
    return await service.extract(
        db, request, release_id=release_context.release_id
    )
