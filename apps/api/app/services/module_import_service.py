"""Transactional module TSV import service.

The service is release-scoped and idempotent by checksum.  A failed staging
import leaves no rows behind; a successful import stores validation evidence,
marks the dataset ``ready``. Publication remains an explicit, target-scoped
workflow handled by ``publication_service.request_publication``.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.data_publishing import DataSet, ImportStatus
from ..models.module_data import ModuleDataRow


class ModuleImportError(ValueError):
    """Raised when a module import cannot be completed safely."""


async def _find_dataset(
    db: AsyncSession, *, module_key: str, release_id: int
) -> DataSet | None:
    result = await db.execute(
        select(DataSet).where(
            DataSet.type == "module_tsv",
            DataSet.release_id == release_id,
        )
    )
    for dataset in result.scalars().all():
        evidence = dataset.validation_evidence or {}
        if evidence.get("module_key") == module_key:
            return dataset
    return None


async def count_rows(
    db: AsyncSession, module_key: str, release_id: int
) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(ModuleDataRow)
        .where(
            ModuleDataRow.module_key == module_key,
            ModuleDataRow.release_id == release_id,
        )
    )
    return int(result.scalar() or 0)


async def import_rows(
    db: AsyncSession,
    *,
    module_key: str,
    release_id: int,
    rows: list[dict[str, Any]],
    checksum: str,
    actor_id: str | None = None,
) -> DataSet:
    """Validate, stage, and commit module rows for a release.

    The caller owns the transaction. On success the dataset is ``ready``.
    Static publication is intentionally not requested here because a
    publication target must be selected explicitly.
    """
    if not checksum:
        raise ModuleImportError("checksum is required")
    if not rows:
        raise ModuleImportError("rows must not be empty")

    existing = await _find_dataset(db, module_key=module_key, release_id=release_id)

    if existing is not None and existing.status == ImportStatus.READY.value:
        evidence = existing.validation_evidence or {}
        if evidence.get("checksum") == checksum:
            return existing
        raise ModuleImportError("module data already imported for this release")

    # Remove any partial/failed staging rows before re-importing.
    await db.execute(
        delete(ModuleDataRow).where(
            ModuleDataRow.module_key == module_key,
            ModuleDataRow.release_id == release_id,
        )
    )

    if existing is None:
        dataset = DataSet(
            type="module_tsv",
            release_id=release_id,
            source_objects=[{"checksum": checksum}],
            status=ImportStatus.UPLOADING,
            validation_evidence={
                "module_key": module_key,
                "checksum": checksum,
                "row_count": len(rows),
            },
        )
        db.add(dataset)
        await db.flush()
    else:
        dataset = existing
        dataset.source_objects = [{"checksum": checksum}]
        dataset.validation_evidence = {
            "module_key": module_key,
            "checksum": checksum,
            "row_count": len(rows),
        }
        dataset.status = ImportStatus.UPLOADING.value

    for index, row in enumerate(rows, start=1):
        key_parts = [str(row.get(col, "")) for col in _unique_key_columns(module_key)]
        db.add(
            ModuleDataRow(
                id=uuid.uuid4(),
                module_key=module_key,
                release_id=release_id,
                row_key="\x1f".join(key_parts),
                data=row,
            )
        )

    dataset.status = ImportStatus.READY.value
    dataset.manifest = {
        "module_key": module_key,
        "release_id": release_id,
        "checksum": checksum,
        "row_count": len(rows),
    }

    await db.flush()
    return dataset


def _unique_key_columns(module_key: str) -> tuple[str, ...]:
    from .module_schema_registry import get_schema

    schema = get_schema(module_key)
    if schema is None:
        raise ModuleImportError(f"unknown module schema: {module_key}")
    return schema.unique_key


__all__ = ["ModuleImportError", "count_rows", "import_rows"]
