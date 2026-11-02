"""Offline API-level smoke tests for the Import Studio chain."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.api.v1.import_studio import (
    add_patches,
    commit_draft,
    create_dataset_version,
    create_draft,
    list_drafts,
    validate_draft,
)
from app.core.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.models.import_studio import ImportDraftStatus
from app.schemas.import_studio import (
    DataPatchCreateRequest,
    DatasetVersionCreateRequest,
    ImportCommitRequest,
    ImportDraftCreateRequest,
    ImportValidationRequest,
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


def _version_row() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        filename="genes.tsv",
        object_key="s3://bucket/genes.tsv",
        checksum_sha256="a" * 64,
        source="NCBI RefSeq",
        license="CC0",
        mime_type="text/tab-separated-values",
        row_count=10,
        column_count=5,
    )


def _draft_row(version_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        dataset_version_id=version_id,
        module_key=None,
        filename="genes.tsv",
        object_key="s3://bucket/genes.tsv",
        checksum_sha256="a" * 64,
        source="NCBI RefSeq",
        license="CC0",
        mime_type="text/tab-separated-values",
        row_count=10,
        column_count=5,
        field_mapping=[],
        validation={},
        status=ImportDraftStatus.DRAFT.value,
        committed_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


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


@pytest.mark.asyncio
async def test_create_dataset_version_rejects_an_unknown_module_schema() -> None:
    db = _FakeDB()

    with pytest.raises(NotFoundError, match="Unknown module schema"):
        await create_dataset_version(
            DatasetVersionCreateRequest(
                dataset_id=1,
                filename="wide.tsv",
                object_key="s3://bucket/wide.tsv",
                checksum_sha256="a" * 64,
                source="NCBI RefSeq",
                license=None,
                mime_type="text/tab-separated-values",
                row_count=10,
                column_count=5,
                source_objects=[],
                module_key="not-a-registered-module",
            ),
            db=db,  # type: ignore[arg-type]
            current_user=_admin(),  # type: ignore[arg-type]
        )

    assert db.added == []
    assert db.committed == 0


@pytest.mark.asyncio
async def test_create_dataset_version_accepts_a_registered_scientific_shape() -> None:
    """The scientific limits must be reachable for a registered module."""
    captured: list[tuple[int, int]] = []

    class _CapturingDB(_FakeDB):
        def add(self, row: object) -> None:
            # Capture before the fake refresh overwrites the shape.
            captured.append((row.row_count, row.column_count))  # type: ignore[attr-defined]
            super().add(row)

    db = _CapturingDB()

    await create_dataset_version(
        DatasetVersionCreateRequest(
            dataset_id=1,
            filename="wide.tsv",
            object_key="s3://bucket/wide.tsv",
            checksum_sha256="a" * 64,
            source="NCBI RefSeq",
            license=None,
            mime_type="text/tab-separated-values",
            row_count=2_000_000,
            column_count=200,
            source_objects=[],
            module_key="genes",
        ),
        db=db,  # type: ignore[arg-type]
        current_user=_admin(),  # type: ignore[arg-type]
    )

    assert captured == [(2_000_000, 200)]
    assert db.committed == 1


class _MutableDraftDB:
    """Minimal draft store for the validation endpoint."""

    def __init__(self, module_key: str | None) -> None:
        self.row = SimpleNamespace(
            id=uuid.uuid4(),
            dataset_version_id=uuid.uuid4(),
            module_key=module_key,
            filename="genes.tsv",
            object_key="s3://bucket/genes.tsv",
            checksum_sha256="a" * 64,
            source="NCBI RefSeq",
            license="CC0",
            mime_type="text/tab-separated-values",
            row_count=10,
            column_count=5,
            field_mapping=[],
            validation={},
            status=ImportDraftStatus.DRAFT.value,
            committed_at=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.committed = 0

    async def execute(self, _statement: object) -> _Result:
        return _Result(self.row)

    def add(self, _row: object) -> None:
        raise AssertionError("validation must not create records")

    async def commit(self) -> None:
        self.committed += 1

    async def refresh(self, _row: object) -> None:
        return None


@pytest.mark.asyncio
async def test_validate_draft_rejects_a_module_key_mismatch() -> None:
    db = _MutableDraftDB("genes")

    with pytest.raises(ValidationError, match="module key does not match"):
        await validate_draft(
            db.row.id,
            ImportValidationRequest(
                row_count=10,
                column_count=5,
                field_mapping=[],
                module_key="other-module",
            ),
            db=db,  # type: ignore[arg-type]
            current_user=_admin(),  # type: ignore[arg-type]
        )

    assert db.committed == 0


@pytest.mark.asyncio
async def test_validate_draft_uses_the_draft_module_key_for_the_shape_limit() -> None:
    """A registered scientific draft may exceed the generic page limits."""
    db = _MutableDraftDB("genes")

    await validate_draft(
        db.row.id,
        ImportValidationRequest(
            row_count=2_000_000,
            column_count=200,
            field_mapping=[],
            module_key="genes",
        ),
        db=db,  # type: ignore[arg-type]
        current_user=_admin(),  # type: ignore[arg-type]
    )

    assert db.committed == 1
    assert db.row.row_count == 2_000_000
    assert db.row.column_count == 200


class _ExistingDraftDB:
    def __init__(
        self,
        *,
        fail_insert: bool = False,
        integrity_constraint: str = "uq_import_drafts_dataset_version",
    ) -> None:
        self.version = _version_row()
        self.existing = _draft_row(self.version.id)
        self.fail_insert = fail_insert
        self.integrity_constraint = integrity_constraint
        self.lookup_count = 0
        self.added: list[object] = []
        self.committed = 0
        self.rolled_back = 0

    async def get(self, model: object, _value: object) -> object:
        # create_draft loads the immutable DatasetVersion first.
        return self.version if model.__name__ == "DatasetVersion" else self.existing

    async def scalar(self, _statement: object) -> object:
        self.lookup_count += 1
        # The first lookup is deliberately empty to model a concurrent insert;
        # the second sees the winner after the failed transaction is rolled back.
        return None if self.fail_insert and self.lookup_count == 1 else self.existing

    def add(self, row: object) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.committed += 1
        if self.fail_insert:
            raise IntegrityError(
                "insert",
                {},
                SimpleNamespace(constraint_name=self.integrity_constraint),
            )

    async def rollback(self) -> None:
        self.rolled_back += 1


def _draft_request(version_id: uuid.UUID) -> ImportDraftCreateRequest:
    return ImportDraftCreateRequest(
        dataset_version_id=version_id,
        module_key=None,
        row_count=10,
        column_count=5,
    )


@pytest.mark.asyncio
async def test_duplicate_create_draft_resumes_existing_row_without_insert() -> None:
    db = _ExistingDraftDB()

    result = await create_draft(
        _draft_request(db.version.id),
        db=db,  # type: ignore[arg-type]
        current_user=_admin(),  # type: ignore[arg-type]
    )

    assert result.id == db.existing.id
    assert db.added == []
    assert db.committed == 0


@pytest.mark.asyncio
async def test_concurrent_create_draft_recovers_unique_constraint_winner() -> None:
    db = _ExistingDraftDB(fail_insert=True)

    result = await create_draft(
        _draft_request(db.version.id),
        db=db,  # type: ignore[arg-type]
        current_user=_admin(),  # type: ignore[arg-type]
    )

    assert result.id == db.existing.id
    assert db.committed == 1
    assert db.rolled_back == 1
    assert db.lookup_count == 2


@pytest.mark.asyncio
async def test_unrelated_integrity_error_is_not_treated_as_concurrent_draft() -> None:
    db = _ExistingDraftDB(
        fail_insert=True,
        integrity_constraint="fk_import_drafts_dataset_version_id",
    )

    with pytest.raises(IntegrityError):
        await create_draft(
            _draft_request(db.version.id),
            db=db,  # type: ignore[arg-type]
            current_user=_admin(),  # type: ignore[arg-type]
        )

    assert db.rolled_back == 0
    assert db.lookup_count == 1


@pytest.mark.asyncio
async def test_duplicate_create_draft_rejects_different_inspected_shape() -> None:
    db = _ExistingDraftDB()

    with pytest.raises(ConflictError, match="match inspected DatasetVersion"):
        await create_draft(
            ImportDraftCreateRequest(
                dataset_version_id=db.version.id,
                module_key=None,
                row_count=9,
                column_count=5,
            ),
            db=db,  # type: ignore[arg-type]
            current_user=_admin(),  # type: ignore[arg-type]
        )

    assert db.added == []
    assert db.committed == 0


@pytest.mark.asyncio
async def test_committed_dataset_version_draft_is_not_reopened() -> None:
    db = _ExistingDraftDB()
    db.existing.status = ImportDraftStatus.COMMITTED.value

    with pytest.raises(ConflictError, match="already committed"):
        await create_draft(
            _draft_request(db.version.id),
            db=db,  # type: ignore[arg-type]
            current_user=_admin(),  # type: ignore[arg-type]
        )

    assert db.added == []
    assert db.committed == 0


@pytest.mark.asyncio
async def test_import_studio_create_requires_administrator_role() -> None:
    db = _FakeDB()
    viewer = SimpleNamespace(
        id=uuid.uuid4(),
        is_superuser=False,
        is_active=True,
        is_deleted=False,
        role_rel=SimpleNamespace(name="viewer"),
    )

    with pytest.raises(AuthorizationError, match="Administrator"):
        await create_draft(
            _draft_request(uuid.uuid4()),
            db=db,  # type: ignore[arg-type]
            current_user=viewer,  # type: ignore[arg-type]
        )

    assert db.added == []
    assert db.committed == 0


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
