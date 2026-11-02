"""Owner-scoped variant export records: submit → status → download.

The export POST used to leave no durable trace of the artifact: the outbox
event carried the command, the Celery result backend is disposable, and the
API could not answer "is my export ready?" or "where is my file?".  This
module owns that state in PostgreSQL.

Two boundaries are enforced here and nowhere else:

* **Authorization** — only the submitter and an administrator may read an
  export.  The export id is unguessable, but it is *not* the authorization:
  a stranger's export is reported as "not found" so its existence is not
  disclosed.
* **Artifact identity** — the row stores an object *key*.  A download URL is
  signed on demand, for a short window, for the requester only.  No
  long-lived URL is ever persisted or returned by the status endpoint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from soymutdb_jobs.export_artifact import build_export_filename
from soymutdb_jobs.export_errors import public_export_error
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.exceptions import ConflictError, NotFoundError
from ..core.security import RoleName, has_role
from ..models.variant_export import VariantExport, VariantExportStatus
from ..schemas.variant import ExportDownloadResponse, ExportStatusResponse
from ..utils.s3 import generate_presigned_url

__all__ = [
    "EXPORT_ARTIFACT_RETENTION_DAYS",
    "EXPORT_DOWNLOAD_URL_TTL_SECONDS",
    "VariantExportService",
]

#: The settings object is bound once at import time: ``get_settings()`` is
#: cached, so this keeps the module-level reference stable for the download
#: path without re-reading the environment per request.
settings = get_settings()

#: How long a produced artifact stays downloadable (matches the worker's
#: object-cleanup retention of exported files).
EXPORT_ARTIFACT_RETENTION_DAYS = 7

#: Lifetime of a signed download URL.  Short on purpose: the link is a
#: per-request grant, not a durable shareable URL.
EXPORT_DOWNLOAD_URL_TTL_SECONDS = 900

class VariantExportService:
    """Read/authorisation service for variant export records."""

    def __init__(self, download_url_ttl: int = EXPORT_DOWNLOAD_URL_TTL_SECONDS) -> None:
        self._download_url_ttl = download_url_ttl

    # -- creation ----------------------------------------------------------

    @staticmethod
    async def create_record(
        db: AsyncSession,
        *,
        export_id: uuid.UUID,
        user_id: uuid.UUID | None,
        release_key: str,
        assembly_key: str | None,
        export_format: str,
        compress: bool,
        filters: dict,
    ) -> VariantExport:
        """Insert the export record for a freshly accepted request."""
        record = VariantExport(
            id=export_id,
            user_id=user_id,
            status=VariantExportStatus.PENDING,
            release_key=release_key,
            assembly_key=assembly_key,
            format=export_format,
            compress=compress,
            filters=filters,
        )
        db.add(record)
        await db.flush()
        return record

    # -- reads -------------------------------------------------------------

    async def get_status(
        self,
        db: AsyncSession,
        export_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None,
        user_roles: list[str],
    ) -> ExportStatusResponse:
        """Return the owner-visible state of one export."""
        record = await self._load_visible(db, export_id, user_id=user_id, user_roles=user_roles)
        return ExportStatusResponse(
            export_id=str(record.id),
            status=str(record.status),
            format=record.format,
            release_key=record.release_key,
            assembly_key=record.assembly_key,
            record_count=record.record_count,
            file_size=record.file_size,
            error_message=public_export_error(record.error_message),
            created_at=record.created_at,
            started_at=record.started_at,
            completed_at=record.completed_at,
            expires_at=record.expires_at,
        )

    async def get_download(
        self,
        db: AsyncSession,
        export_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None,
        user_roles: list[str],
    ) -> ExportDownloadResponse:
        """Sign a short-lived download URL for a finished export artifact."""
        record = await self._load_visible(db, export_id, user_id=user_id, user_roles=user_roles)
        if record.status != VariantExportStatus.SUCCEEDED:
            raise ConflictError(
                f"Export {export_id} is {record.status}; a download is only available "
                "for a completed export"
            )
        if not record.artifact_path:
            raise NotFoundError(f"Export {export_id} has no artifact")
        if record.expires_at is not None and record.expires_at <= datetime.now(UTC):
            raise NotFoundError(f"Export {export_id} has expired")

        filename = build_export_filename(str(record.id), record.format, record.compress)
        expires_at = datetime.now(UTC) + timedelta(seconds=self._download_url_ttl)
        url = generate_presigned_url(
            f"{settings.s3_export_bucket}/{record.artifact_path}",
            expires_in=self._download_url_ttl,
        )
        return ExportDownloadResponse(
            export_id=str(record.id),
            download_url=url,
            filename=filename,
            expires_at=expires_at,
            expires_in_seconds=self._download_url_ttl,
        )

    # -- internals ---------------------------------------------------------

    async def _load_visible(
        self,
        db: AsyncSession,
        export_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None,
        user_roles: list[str],
    ) -> VariantExport:
        """Load an export the caller is allowed to see.

        A record owned by somebody else is reported as missing, so the
        unguessable id never becomes a capability for discovering that an
        export exists.  This deliberately differs from the GWAS job API,
        which answers a foreign job with 403: a 403 would confirm that the
        id exists, and the export id is exactly what a stranger might have
        obtained.  The GWAS divergence is tracked as a follow-up; it is not
        a pattern to copy.
        """
        result = await db.execute(select(VariantExport).where(VariantExport.id == export_id))
        record = result.scalar_one_or_none()
        if record is None:
            raise NotFoundError(f"Export {export_id} not found")
        if not self._may_read(record, user_id=user_id, user_roles=user_roles):
            raise NotFoundError(f"Export {export_id} not found")
        return record

    @staticmethod
    def _may_read(
        record: VariantExport,
        *,
        user_id: uuid.UUID | None,
        user_roles: list[str],
    ) -> bool:
        if record.user_id is not None and user_id is not None and record.user_id == user_id:
            return True
        return has_role(user_roles, RoleName.ADMINISTRATOR)
