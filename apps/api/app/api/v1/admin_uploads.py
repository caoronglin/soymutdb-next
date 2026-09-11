"""Admin upload endpoints (D4): presigned uploads for public resources.

Provides ``POST /admin/uploads/presign`` — the stateless presign flow used by
the admin file-upload component (``apps/admin/src/components/file-upload.tsx``):

1. Client POSTs the file name, size, MIME type, and SHA-256 (content editor).
2. API returns a constrained multipart POST action and every signed field.
3. Client POSTs those fields followed by the file to S3/MinIO.
4. Client calls ``/complete`` and receives the verified asset id plus ``public_url``;
   callers persist both when appropriate.

Objects land in the PUBLIC bucket under ``uploads/{purpose}/{uuid}-<file>``
(see ``app.services.presign``).  The separate ``/complete`` endpoint verifies
the stored bytes before creating a reusable media-asset row.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.config import get_settings
from ...core.security import RoleName
from ...models.auth import User
from ...schemas.media import MediaAssetCompleteRequest, MediaAssetResponse
from ...schemas.uploads import UploadPresignRequest, UploadPresignResponse
from ...services.media_service import complete_media_asset
from ...services.presign import (
    UPLOAD_EXPIRES_IN,
    build_uploads_key,
    generate_public_url,
    generate_upload_post,
)
from .deps import get_current_user, require_role

router = APIRouter(prefix="/admin/uploads", tags=["admin-uploads"])

#: Uploads are public resources managed by content editors. Administrators
#: inherit this capability through the central RBAC grant map.
_CONTENT_EDITORS = [Depends(require_role(RoleName.CONTENT_EDITOR))]

settings = get_settings()


@router.post(
    "/presign",
    response_model=UploadPresignResponse,
    dependencies=_CONTENT_EDITORS,
)
async def create_upload_presign(
    request: UploadPresignRequest,
) -> UploadPresignResponse:
    """Request a constrained pre-signed POST for a content-editor upload.

    Returns a POST action valid for 1 hour, all signed form fields, the object
    key, and the public URL the caller should persist. Nothing is stored
    server-side yet.

    Objects are stored in the PUBLIC bucket (``SOYMUTDB_S3_PUBLIC_BUCKET``)
    so ``public_url`` can be served directly by the static gateway.
    """
    object_key = build_uploads_key(request.purpose, request.filename)
    upload = generate_upload_post(
        object_key,
        size=request.size,
        content_type=request.content_type,
        checksum_sha256=request.checksum_sha256,
        bucket=settings.s3_public_bucket,
        expires_in=UPLOAD_EXPIRES_IN,
    )
    return UploadPresignResponse(
        upload_url=upload.url,
        upload_fields=upload.fields,
        object_key=object_key,
        public_url=generate_public_url(object_key),
        expires_in=UPLOAD_EXPIRES_IN,
    )


@router.post(
    "/complete",
    response_model=MediaAssetResponse,
    dependencies=_CONTENT_EDITORS,
)
async def complete_upload(
    request: MediaAssetCompleteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MediaAssetResponse:
    """Verify the object bytes and register a reusable media asset.

    The endpoint is intentionally separate from presign: an object is not
    selectable in the CMS until the server has checked its bytes, digest, MIME
    type and dimensions. Repeating the request is idempotent for the same key.
    """

    return MediaAssetResponse.model_validate(
        await complete_media_asset(db, request, current_user.id)
    )
