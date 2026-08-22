"""Admin upload endpoints (D4): presigned uploads for public resources.

Provides ``POST /admin/uploads/presign`` — the stateless presign flow used by
the admin file-upload component (``apps/admin/src/components/file-upload.tsx``):

1. Client POSTs the file name, size, MIME type, and SHA-256 (content editor).
2. API returns a constrained multipart POST action and every signed field.
3. Client POSTs those fields followed by the file to S3/MinIO.
4. Client persists ``public_url`` (e.g. as ``news_articles.cover_url``).

Objects land in the PUBLIC bucket under ``uploads/{purpose}/{uuid}-<file>``
(see ``app.services.presign``).  Nothing is persisted server-side; the flow
is stateless like the analyses upload endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...core.config import get_settings
from ...core.security import RoleName
from ...schemas.uploads import UploadPresignRequest, UploadPresignResponse
from ...services.presign import (
    UPLOAD_EXPIRES_IN,
    build_uploads_key,
    generate_public_url,
    generate_upload_post,
)
from .deps import require_role

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
