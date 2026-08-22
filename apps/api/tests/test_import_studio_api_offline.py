"""Offline API-level smoke tests for the Import Studio chain."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.api.v1.import_studio import create_dataset_version, create_draft
from app.models.import_studio import ImportDraftStatus
from app.schemas.import_studio import DatasetVersionCreateRequest, ImportDraftCreateRequest


class _FakeDB:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = 0

    async def get(self, _model: object, value: object) -> object:
        if str(value) == "1":
            return SimpleNamespace(id=1)
        return SimpleNamespace(
            id=uuid.uuid4(),
            filename="genes.tsv",
            object_key="s3://bucket/genes.tsv",
            checksum_sha256="a" * 64,
            source="NCBI RefSeq",
            license="CC0",
            mime_type="text/tab-separated-values",
        )

    async def scalar(self, _statement: object) -> None:
        return None

    def add(self, row: object) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.committed += 1

    async def refresh(self, row: object) -> None:
        now = datetime.now(UTC)
        for field, value in {
            "id": uuid.uuid4(),
            "version": 1,
            "status": ImportDraftStatus.DRAFT.value,
            "row_count": 10,
            "column_count": 5,
            "source_objects": [],
            "field_mapping": [],
            "validation": {},
            "manifest": None,
            "created_at": now,
            "updated_at": now,
            "committed_at": None,
        }.items():
            if hasattr(row, field):
                setattr(row, field, value)


def _admin() -> object:
    return SimpleNamespace(
        id=uuid.uuid4(),
        is_superuser=True,
        is_active=True,
        is_deleted=False,
        role_rel=SimpleNamespace(name="administrator"),
    )


@pytest.mark.asyncio
async def test_create_dataset_version_and_draft_offline() -> None:
    db = _FakeDB()
    version = await create_dataset_version(
        DatasetVersionCreateRequest(
            dataset_id=1,
            filename="genes.tsv",
            object_key="s3://bucket/genes.tsv",
            checksum_sha256="a" * 64,
            source="NCBI RefSeq",
            license="CC0",
            mime_type="text/tab-separated-values",
            row_count=10,
            column_count=5,
            source_objects=[],
        ),
        db=db,  # type: ignore[arg-type]
        current_user=_admin(),  # type: ignore[arg-type]
    )
    assert version.dataset_id == 1
    assert version.version == 1

    draft = await create_draft(
        ImportDraftCreateRequest(
            dataset_version_id=version.id,
            module_key=None,
            row_count=10,
            column_count=5,
        ),
        db=db,  # type: ignore[arg-type]
        current_user=_admin(),  # type: ignore[arg-type]
    )
    assert draft.module_key is None
    assert draft.row_count == 10
    assert db.committed == 2
