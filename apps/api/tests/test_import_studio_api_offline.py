"""Offline API-level smoke tests for the Import Studio chain."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.api.v1.import_studio import (
    add_patches,
    commit_draft,
    create_dataset_version,
    create_draft,
    list_drafts,
)
from app.core.exceptions import ConflictError
from app.models.import_studio import ImportDraftStatus
from app.schemas.import_studio import (
    DataPatchCreateRequest,
    DatasetVersionCreateRequest,
    ImportCommitRequest,
    ImportDraftCreateRequest,
)


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


class _Result:
    def __init__(self, row: object) -> None:
        self._row = row

    def scalar_one_or_none(self) -> object:
        return self._row


class _CommittedDraftDB:
    def __init__(self) -> None:
        self.row = SimpleNamespace(
            id=uuid.uuid4(),
            dataset_version_id=uuid.uuid4(),
            module_key=None,
            checksum_sha256="a" * 64,
            row_count=1,
            column_count=1,
            field_mapping=[],
            status=ImportDraftStatus.COMMITTED.value,
            committed_at=datetime.now(UTC),
        )
        self.statements: list[str] = []
        self.committed = 0

    async def get(self, _model: object, _value: object) -> object:
        return self.row

    async def execute(self, statement: object) -> _Result:
        self.statements.append(str(statement))
        return _Result(self.row)

    def add(self, _row: object) -> None:
        raise AssertionError("a committed draft must not create more records")

    async def commit(self) -> None:
        self.committed += 1


@pytest.mark.asyncio
async def test_committed_drafts_reject_patch_mutation_before_persistence() -> None:
    db = _CommittedDraftDB()

    with pytest.raises(ConflictError, match="committed"):
        await add_patches(
            db.row.id,
            DataPatchCreateRequest(
                patches=[{"row_key": "r1", "column_name": "gene_id", "new_value": "GX"}]
            ),
            db=db,  # type: ignore[arg-type]
            current_user=_admin(),  # type: ignore[arg-type]
        )

    assert db.committed == 0


@pytest.mark.asyncio
async def test_commit_locks_the_draft_and_rejects_a_second_commit() -> None:
    db = _CommittedDraftDB()

    with pytest.raises(ConflictError, match="already committed"):
        await commit_draft(
            db.row.id,
            ImportCommitRequest(confirm=True),
            db=db,  # type: ignore[arg-type]
            current_user=_admin(),  # type: ignore[arg-type]
        )

    assert any("FOR UPDATE" in statement for statement in db.statements)
    assert db.committed == 0

class _ListResult:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def scalars(self) -> _ListResult:
        return self

    def all(self) -> list[object]:
        return self.rows


class _DraftListDB:
    def __init__(self) -> None:
        self.rows = [
            SimpleNamespace(
                id=uuid.uuid4(),
                dataset_version_id=uuid.uuid4(),
                module_key="genes",
                filename="genes.tsv",
                row_count=10,
                column_count=5,
                status=ImportDraftStatus.DRAFT.value,
                updated_at=datetime.now(UTC),
            )
        ]

    async def execute(self, _statement: object) -> _ListResult:
        return _ListResult(self.rows)


@pytest.mark.asyncio
async def test_list_drafts_returns_resume_metadata_without_source_details() -> None:
    result = await list_drafts(
        db=_DraftListDB(),  # type: ignore[arg-type]
        current_user=_admin(),  # type: ignore[arg-type]
    )

    assert len(result) == 1
    assert result[0].filename == "genes.tsv"
    assert result[0].status == "draft"
    assert not hasattr(result[0], "object_key")
    assert not hasattr(result[0], "checksum_sha256")
