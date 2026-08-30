"""Admin Import Studio endpoints for the immutable version/edit chain."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from ...core.security import RoleName, has_role
from ...models.auth import User
from ...models.data_publishing import DataSet
from ...models.import_studio import (
    DataPatch,
    DatasetVersion,
    FieldMapping,
    ImportDraft,
    ImportDraftStatus,
    PageDataSource,
    PublicationManifest,
)
from ...models.page_builder import PageDefinition
from ...schemas.import_studio import (
    DataPatchCreateRequest,
    DatasetVersionCreateRequest,
    DatasetVersionResponse,
    FieldMappingUpdateRequest,
    ImportCommitRequest,
    ImportDraftCreateRequest,
    ImportDraftResponse,
    ImportDraftListItemResponse,
    ImportValidationRequest,
    PublicationManifestResponse,
)
from ...services.import_studio_service import (
    MAX_DATA_PATCHES,
    build_publication_manifest,
    validate_data_patches,
    validate_field_mapping,
    validate_import_shape,
)
from ...services.module_schema_registry import get_schema
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/imports/studio", tags=["admin-import-studio"])


def _require_admin(current_user: User) -> None:
    if not has_role(get_user_roles(current_user), RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator access required")


def _status_value(value: object) -> str:
    return str(getattr(value, "value", value))


async def _load_draft_for_update(
    db: AsyncSession, draft_id: uuid.UUID
) -> ImportDraft:
    """Lock one draft across an edit or commit state transition."""
    row = (
        await db.execute(
            select(ImportDraft)
            .where(ImportDraft.id == draft_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"Import draft {draft_id} not found")
    return row


def _require_mutable_draft(row: ImportDraft) -> None:
    """Permit edits only before a draft has been validated or published."""
    current_status = _status_value(row.status)
    if current_status == ImportDraftStatus.COMMITTED.value:
        raise ConflictError(
            f"Import draft {row.id} is already committed and immutable"
        )
    if current_status != ImportDraftStatus.DRAFT.value:
        raise ConflictError(
            f"Import draft {row.id} is {current_status} and cannot be edited; "
            "create a new draft instead"
        )


def _version_response(row: DatasetVersion) -> DatasetVersionResponse:
    return DatasetVersionResponse(
        id=row.id,
        dataset_id=row.dataset_id,
        version=row.version,
        filename=row.filename,
        object_key=row.object_key,
        checksum_sha256=row.checksum_sha256,
        source=row.source,
        license=row.license,
        mime_type=row.mime_type,
        row_count=row.row_count,
        column_count=row.column_count,
        source_objects=row.source_objects,
        manifest=row.manifest,
        status=_status_value(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _draft_response(row: ImportDraft) -> ImportDraftResponse:
    return ImportDraftResponse(
        id=row.id,
        dataset_version_id=row.dataset_version_id,
        module_key=row.module_key,
        filename=row.filename,
        object_key=row.object_key,
        checksum_sha256=row.checksum_sha256,
        source=row.source,
        license=row.license,
        mime_type=row.mime_type,
        row_count=row.row_count,
        column_count=row.column_count,
        field_mapping=row.field_mapping,
        validation=row.validation,
        status=_status_value(row.status),
        committed_at=row.committed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _manifest_response(row: PublicationManifest) -> PublicationManifestResponse:
    return PublicationManifestResponse(
        id=row.id,
        import_draft_id=row.import_draft_id,
        checksum_sha256=row.checksum_sha256,
        manifest=row.manifest,
        published_at=row.published_at,
    )


@router.post(
    "/dataset-versions",
    response_model=DatasetVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_dataset_version(
    payload: DatasetVersionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DatasetVersionResponse:
    """Record immutable raw-object metadata before any editing begins."""
    _require_admin(current_user)
    validate_import_shape(
        row_count=payload.row_count,
        column_count=payload.column_count,
        module_key=None,
    )
    dataset = await db.get(DataSet, payload.dataset_id)
    if dataset is None:
        raise NotFoundError(f"Dataset {payload.dataset_id} not found")

    latest = await db.scalar(
        select(func.max(DatasetVersion.version)).where(
            DatasetVersion.dataset_id == payload.dataset_id
        )
    )
    row = DatasetVersion(
        dataset_id=payload.dataset_id,
        version=int(latest or 0) + 1,
        filename=payload.filename,
        object_key=payload.object_key,
        checksum_sha256=payload.checksum_sha256,
        source=payload.source,
        license=payload.license,
        mime_type=payload.mime_type,
        row_count=payload.row_count,
        column_count=payload.column_count,
        source_objects=payload.source_objects,
        status=ImportDraftStatus.DRAFT.value,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _version_response(row)


@router.post(
    "/drafts",
    response_model=ImportDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_draft(
    payload: ImportDraftCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportDraftResponse:
    """Create an editing draft from an immutable dataset version."""
    _require_admin(current_user)
    version = await db.get(DatasetVersion, payload.dataset_version_id)
    if version is None:
        raise NotFoundError(f"Dataset version {payload.dataset_version_id} not found")
    if payload.module_key is not None and get_schema(payload.module_key) is None:
        raise NotFoundError(f"Unknown module schema '{payload.module_key}'")
    validate_import_shape(
        row_count=payload.row_count,
        column_count=payload.column_count,
        module_key=payload.module_key,
    )
    row = ImportDraft(
        dataset_version_id=version.id,
        module_key=payload.module_key,
        filename=version.filename,
        object_key=version.object_key,
        checksum_sha256=version.checksum_sha256,
        source=version.source,
        license=version.license,
        mime_type=version.mime_type,
        row_count=payload.row_count,
        column_count=payload.column_count,
        field_mapping=[],
        validation={},
        status=ImportDraftStatus.DRAFT.value,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _draft_response(row)


@router.get("/drafts", response_model=list[ImportDraftListItemResponse])
async def list_drafts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ImportDraftListItemResponse]:
    """List persisted Import Studio drafts for dashboard resume only.

    This endpoint never creates or validates a draft and exposes no mutable
    source metadata, so dashboard discovery cannot fabricate an import source.
    """
    _require_admin(current_user)
    rows = (
        await db.execute(select(ImportDraft).order_by(ImportDraft.updated_at.desc()))
    ).scalars().all()
    return [
        ImportDraftListItemResponse(
            id=row.id,
            dataset_version_id=row.dataset_version_id,
            module_key=row.module_key,
            filename=row.filename,
            row_count=row.row_count,
            column_count=row.column_count,
            status=_status_value(row.status),
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.get("/drafts/{draft_id}", response_model=ImportDraftResponse)
async def get_draft(
    draft_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportDraftResponse:
    _require_admin(current_user)
    row = await db.get(ImportDraft, draft_id)
    if row is None:
        raise NotFoundError(f"Import draft {draft_id} not found")
    return _draft_response(row)


@router.put("/drafts/{draft_id}/mapping", response_model=ImportDraftResponse)
async def update_mapping(
    draft_id: uuid.UUID,
    payload: FieldMappingUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportDraftResponse:
    _require_admin(current_user)
    row = await _load_draft_for_update(db, draft_id)
    _require_mutable_draft(row)
    mappings = [item.model_dump(mode="python") for item in payload.mappings]
    validate_field_mapping(mappings)

    existing = (
        await db.execute(
            select(FieldMapping).where(FieldMapping.import_draft_id == row.id)
        )
    ).scalars().all()
    for mapping in existing:
        await db.delete(mapping)
    row.field_mapping = mappings
    for index, item in enumerate(payload.mappings):
        db.add(
            FieldMapping(
                import_draft_id=row.id,
                source_field=item.source_field,
                target_field=item.target_field,
                position=item.position,
                transform=item.transform,
                created_by=current_user.id,
                updated_by=current_user.id,
            )
        )
    row.updated_by = current_user.id
    await db.commit()
    await db.refresh(row)
    return _draft_response(row)


@router.post("/drafts/{draft_id}/patches", response_model=ImportDraftResponse)
async def add_patches(
    draft_id: uuid.UUID,
    payload: DataPatchCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportDraftResponse:
    _require_admin(current_user)
    row = await _load_draft_for_update(db, draft_id)
    _require_mutable_draft(row)
    patches = [item.model_dump(mode="python") for item in payload.patches]
    validate_data_patches(patches)
    existing = (
        await db.execute(
            select(DataPatch).where(DataPatch.import_draft_id == row.id)
        )
    ).scalars().all()
    existing_by_cell = {
        (patch.row_key, patch.column_name): patch for patch in existing
    }
    new_cells = {
        (patch["row_key"], patch["column_name"])
        for patch in patches
        if (patch["row_key"], patch["column_name"]) not in existing_by_cell
    }
    if len(existing) + len(new_cells) > MAX_DATA_PATCHES:
        raise ValidationError("A draft cannot contain more than 10,000 patches")
    for item in payload.patches:
        existing_patch = existing_by_cell.get((item.row_key, item.column_name))
        if existing_patch is not None:
            existing_patch.old_value = item.old_value
            existing_patch.new_value = item.new_value
            existing_patch.patch_type = item.patch_type
            existing_patch.updated_by = current_user.id
            continue
        db.add(
            DataPatch(
                import_draft_id=row.id,
                row_key=item.row_key,
                column_name=item.column_name,
                old_value=item.old_value,
                new_value=item.new_value,
                patch_type=item.patch_type,
                created_by=current_user.id,
                updated_by=current_user.id,
            )
        )
    row.updated_by = current_user.id
    await db.commit()
    await db.refresh(row)
    return _draft_response(row)


@router.post("/drafts/{draft_id}/validate", response_model=ImportDraftResponse)
async def validate_draft(
    draft_id: uuid.UUID,
    payload: ImportValidationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportDraftResponse:
    _require_admin(current_user)
    row = await _load_draft_for_update(db, draft_id)
    _require_mutable_draft(row)
    mappings = [item.model_dump(mode="python") for item in payload.field_mapping]
    validate_import_shape(
        row_count=payload.row_count,
        column_count=payload.column_count,
        module_key=row.module_key,
    )
    validate_field_mapping(mappings)
    row.row_count = payload.row_count
    row.column_count = payload.column_count
    row.field_mapping = mappings
    row.validation = {"ok": True, "errors": []}
    row.status = ImportDraftStatus.VALIDATED.value
    row.updated_by = current_user.id
    await db.commit()
    await db.refresh(row)
    return _draft_response(row)


@router.post("/drafts/{draft_id}/commit", response_model=ImportDraftResponse)
async def commit_draft(
    draft_id: uuid.UUID,
    payload: ImportCommitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportDraftResponse:
    """Atomically commit a validated draft and create publication evidence."""
    _require_admin(current_user)
    row = await _load_draft_for_update(db, draft_id)
    current_status = _status_value(row.status)
    if current_status == ImportDraftStatus.COMMITTED.value:
        raise ConflictError(f"Import draft {draft_id} is already committed")
    validate_import_shape(
        row_count=row.row_count,
        column_count=row.column_count,
        module_key=row.module_key,
    )
    validate_field_mapping(row.field_mapping)
    if current_status not in {
        ImportDraftStatus.VALIDATED.value,
        ImportDraftStatus.READY.value,
    }:
        raise ValidationError(
            f"Import draft {draft_id} must be validated before commit"
        )
    existing_manifest = await db.scalar(
        select(PublicationManifest.id)
        .where(PublicationManifest.import_draft_id == row.id)
        .limit(1)
    )
    if existing_manifest is not None:
        raise ConflictError(
            f"Import draft {draft_id} already has publication evidence and "
            "cannot be committed again"
        )
    patch_rows = (
        await db.execute(
            select(DataPatch)
            .where(DataPatch.import_draft_id == row.id)
            .order_by(DataPatch.row_key, DataPatch.column_name)
        )
    ).scalars().all()
    patches = [
        {
            "row_key": patch.row_key,
            "column_name": patch.column_name,
            "old_value": patch.old_value,
            "new_value": patch.new_value,
            "patch_type": patch.patch_type,
        }
        for patch in patch_rows
    ]
    validate_data_patches(patches)

    manifest = build_publication_manifest(
        draft_id=str(row.id),
        dataset_version_id=str(row.dataset_version_id),
        checksum_sha256=row.checksum_sha256,
        row_count=row.row_count,
        column_count=row.column_count,
        module_key=row.module_key,
        field_mapping=row.field_mapping,
        patches=patches,
    )
    if payload.page_id is not None:
        page = await db.get(PageDefinition, payload.page_id)
        if page is None:
            raise NotFoundError(f"Page definition {payload.page_id} not found")
        db.add(
            PageDataSource(
                page_id=payload.page_id,
                dataset_version_id=row.dataset_version_id,
                source_id=payload.source_id,
                kind=payload.kind,
                config={
                    **payload.config,
                    "import_draft_id": str(row.id),
                    "publication_manifest_sha256": manifest["manifest_sha256"],
                },
                created_by=current_user.id,
                updated_by=current_user.id,
            )
        )

    db.add(
        PublicationManifest(
            import_draft_id=row.id,
            checksum_sha256=row.checksum_sha256,
            manifest=manifest,
            published_at=datetime.now(UTC),
            created_by=current_user.id,
            updated_by=current_user.id,
        )
    )
    row.status = ImportDraftStatus.COMMITTED.value
    row.committed_at = datetime.now(UTC)
    row.updated_by = current_user.id
    await db.commit()
    await db.refresh(row)
    return _draft_response(row)


@router.get("/drafts/{draft_id}/manifest", response_model=PublicationManifestResponse)
async def get_manifest(
    draft_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PublicationManifestResponse:
    _require_admin(current_user)
    row = (
        await db.execute(
            select(PublicationManifest)
            .where(PublicationManifest.import_draft_id == draft_id)
            .order_by(PublicationManifest.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"Publication manifest for draft {draft_id} not found")
    return _manifest_response(row)


@router.get("/dataset-versions", response_model=list[DatasetVersionResponse])
async def list_dataset_versions(
    dataset_id: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DatasetVersionResponse]:
    _require_admin(current_user)
    rows = (
        (
            await db.execute(
                select(DatasetVersion)
                .where(DatasetVersion.dataset_id == dataset_id)
                .order_by(DatasetVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_version_response(row) for row in rows]


__all__ = ["router"]
