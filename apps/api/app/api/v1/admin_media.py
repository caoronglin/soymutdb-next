"""Admin media library endpoints for verified, reusable CMS assets."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.security import RoleName
from ...models.media import MediaAssetStatus
from ...schemas.media import (
    MediaAssetListResponse,
    MediaAssetResponse,
    MediaAssetStatus as MediaAssetStatusSchema,
    MediaAssetUpdateRequest,
)
from ...services.media_service import (
    archive_media_asset,
    get_media_asset,
    get_media_asset_usage_count,
    list_media_assets,
    update_media_asset,
)
from .deps import require_role

router = APIRouter(prefix="/admin/media", tags=["admin-media"])
_CONTENT_EDITORS = [Depends(require_role(RoleName.CONTENT_EDITOR))]


def _serialize(asset, usage_count: int = 0) -> MediaAssetResponse:
    return MediaAssetResponse.model_validate(
        {
            "id": asset.id,
            "object_key": asset.object_key,
            "public_url": asset.public_url,
            "original_filename": asset.original_filename,
            "purpose": asset.purpose,
            "content_type": asset.content_type,
            "size_bytes": asset.size_bytes,
            "checksum_sha256": asset.checksum_sha256,
            "width": asset.width,
            "height": asset.height,
            "alt_text": asset.alt_text,
            "caption": asset.caption,
            "credit": asset.credit,
            "is_decorative": asset.is_decorative,
            "status": asset.status,
            "uploaded_by": asset.uploaded_by,
            "verified_at": asset.verified_at,
            "archived_at": asset.archived_at,
            "created_at": asset.created_at,
            "updated_at": asset.updated_at,
            "usage_count": usage_count,
        }
    )


@router.get("", response_model=MediaAssetListResponse, dependencies=_CONTENT_EDITORS)
async def list_media(
    search: str | None = Query(default=None, max_length=128),
    purpose: str | None = Query(default=None, max_length=32),
    asset_status: MediaAssetStatusSchema = Query(
        default=MediaAssetStatusSchema.READY,
        alias="status",
        description="ready or archived; pending is reserved for upload sessions",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> MediaAssetListResponse:
    rows, total = await list_media_assets(
        db,
        search=search,
        purpose=purpose,
        status=MediaAssetStatus(asset_status.value),
        page=page,
        page_size=page_size,
    )
    return MediaAssetListResponse(
        items=[_serialize(asset, usage_count) for asset, usage_count in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{asset_id}", response_model=MediaAssetResponse, dependencies=_CONTENT_EDITORS)
async def read_media(asset_id: UUID, db: AsyncSession = Depends(get_db)) -> MediaAssetResponse:
    asset = await get_media_asset(db, asset_id)
    usage_count = await get_media_asset_usage_count(db, asset_id)
    return _serialize(asset, usage_count)


@router.patch("/{asset_id}", response_model=MediaAssetResponse, dependencies=_CONTENT_EDITORS)
async def patch_media(
    asset_id: UUID,
    payload: MediaAssetUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> MediaAssetResponse:
    asset = await update_media_asset(db, asset_id, payload)
    usage_count = await get_media_asset_usage_count(db, asset_id)
    return _serialize(asset, usage_count)


@router.delete(
    "/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=_CONTENT_EDITORS,
)
async def delete_media(asset_id: UUID, db: AsyncSession = Depends(get_db)) -> Response:
    await archive_media_asset(db, asset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
