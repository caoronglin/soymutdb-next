import hashlib
import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError


def test_multipart_sha256_must_be_a_64_character_hex_digest():
    from app.schemas.data_publishing import MultipartCompleteRequest

    with pytest.raises(ValueError):
        MultipartCompleteRequest(
            object_key="data/1/x.vcf", parts=[{"part_number": 1, "etag": "e1"}], sha256="bad"
        )


def test_multipart_key_is_scoped_to_dataset():
    from app.services.presign import build_data_object_key, validate_data_key

    key = build_data_object_key(42, "genome.fa.gz")
    assert key.startswith("data/42/")
    assert validate_data_key(key) == key
    with pytest.raises(ValueError):
        validate_data_key(key, 43)


def test_multipart_completion_derives_checksum_with_bounded_s3_reads(monkeypatch):
    from app.services import presign

    content = b"gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\n"

    class Body:
        def __init__(self, data: bytes) -> None:
            self._data = data
            self._offset = 0
            self.read_sizes: list[int] = []
            self.closed = False

        def read(self, size: int = -1) -> bytes:
            assert size > 0, "checksum calculation must use bounded S3 reads"
            self.read_sizes.append(size)
            chunk = self._data[self._offset : self._offset + size]
            self._offset += len(chunk)
            return chunk

        def close(self) -> None:
            self.closed = True

    body = Body(content)

    class S3:
        def complete_multipart_upload(self, **_kwargs) -> None:
            return None

        def get_object(self, **_kwargs):
            return {"Body": body}

    monkeypatch.setattr(presign, "get_s3_client", lambda: S3())

    completed = presign.complete_multipart_upload(
        object_key="data/1/genes.tsv",
        upload_id="upload-1",
        parts=[presign.CompletedPart(1, "etag-1")],
    )

    assert completed.sha256 == hashlib.sha256(content).hexdigest()
    assert body.read_sizes
    assert body.closed is True


def test_multipart_completion_removes_object_when_legacy_digest_mismatches(monkeypatch):
    from app.services import presign

    class Body:
        def __init__(self) -> None:
            self._remaining = b"server-owned checksum"

        def read(self, size: int = -1) -> bytes:
            assert size > 0
            chunk = self._remaining[:size]
            self._remaining = self._remaining[len(chunk) :]
            return chunk

        def close(self) -> None:
            return None

    deleted: list[dict[str, str]] = []

    class S3:
        def complete_multipart_upload(self, **_kwargs) -> None:
            return None

        def get_object(self, **_kwargs):
            return {"Body": Body()}

        def delete_object(self, **kwargs) -> None:
            deleted.append(kwargs)

    monkeypatch.setattr(presign, "get_s3_client", lambda: S3())

    with pytest.raises(ValueError, match="server-derived checksum"):
        presign.complete_multipart_upload(
            object_key="data/1/genes.tsv",
            upload_id="upload-1",
            parts=[presign.CompletedPart(1, "etag-1")],
            sha256="0" * 64,
        )

    assert deleted == [{"Bucket": presign.settings.s3_analyses_bucket, "Key": "data/1/genes.tsv"}]


def test_release_actions_require_explicit_confirmation_and_reason():
    from app.schemas.data_publishing import ReleaseActionRequest

    with pytest.raises(ValueError):
        ReleaseActionRequest(confirm=False, reason="approved")
    with pytest.raises(ValueError):
        ReleaseActionRequest(confirm=True, reason="")


def test_release_create_request_contains_dataset_bindings():
    from app.schemas.data_publishing import ReleaseCreateRequest

    request = ReleaseCreateRequest(version="r1", name="Release 1", data_set_ids=[7, 8])
    assert request.data_set_ids == [7, 8]


def test_module_import_request_requires_an_explicit_release_id():
    """A module import cannot defer release binding to the worker."""
    from app.schemas.data_publishing import ImportCreateRequest

    with pytest.raises(PydanticValidationError, match="release_id is required"):
        ImportCreateRequest(
            filename="genes.tsv",
            type="module_tsv",
            object_key="data/1/genes.tsv",
            module_key="genes",
            checksum="a" * 64,
            idempotency_key="module-import-without-release",
        )


def test_module_import_request_preserves_a_frozen_import_draft_id():
    """The API must carry the edit snapshot through to the worker command."""
    from app.schemas.data_publishing import ImportCreateRequest

    draft_id = uuid.uuid4()
    request = ImportCreateRequest(
        filename="genes.tsv",
        type="module_tsv",
        object_key="data/1/genes.tsv",
        data_set_id=1,
        release_id=7,
        module_key="genes",
        checksum="a" * 64,
        import_draft_id=draft_id,
        idempotency_key="module-import-with-draft",
    )

    assert request.import_draft_id == draft_id


@pytest.mark.asyncio
async def test_same_import_idempotency_key_returns_one_task_and_one_outbox(db_session):
    from app.services.outbox_service import create_import_command

    first = await create_import_command(
        db_session,
        actor_id=None,
        idempotency_key="import:42",
        data_set_id=42,
        import_type="vcf",
        filename="x.vcf",
        object_key="data/42/x.vcf",
    )
    second = await create_import_command(
        db_session,
        actor_id=None,
        idempotency_key="import:42",
        data_set_id=42,
        import_type="vcf",
        filename="x.vcf",
        object_key="data/42/x.vcf",
    )
    assert first.id == second.id


@pytest.mark.asyncio
async def test_module_import_command_binds_a_new_dataset_and_outbox_to_an_existing_release(
    db_session,
):
    """The API owns the release binding before a worker message is queued."""
    from sqlalchemy import select

    from app.models.content import Release
    from app.models.data_publishing import DataSet
    from app.models.outbox import OutboxEvent
    from app.services.outbox_service import create_import_command

    release = Release(version="module-r1", name="Module release")
    db_session.add(release)
    await db_session.flush()

    task = await create_import_command(
        db_session,
        actor_id=None,
        idempotency_key="module-import:41",
        data_set_id=41,
        import_type="module_tsv",
        filename="genes.tsv",
        object_key="data/41/genes.tsv",
        release_id=release.id,
        module_key="genes",
        checksum="a" * 64,
    )

    dataset = await db_session.get(DataSet, 41)
    event = await db_session.scalar(
        select(OutboxEvent).where(OutboxEvent.aggregate_id == str(task.id))
    )

    assert dataset is not None
    assert dataset.release_id == release.id
    assert task.release_id == release.id
    assert event is not None
    assert event.payload["kwargs"]["release_id"] == str(release.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_release_id", [None, 1])
async def test_module_import_command_rejects_dataset_bound_to_another_or_no_release(
    db_session,
    existing_release_id,
):
    """A user-supplied data-set id must never be silently rebound."""
    from app.core.exceptions import ValidationError
    from app.models.content import Release
    from app.models.data_publishing import DataSet
    from app.services.outbox_service import create_import_command

    first_release = Release(version="module-existing-r1", name="Existing release")
    second_release = Release(version="module-requested-r2", name="Requested release")
    db_session.add_all([first_release, second_release])
    await db_session.flush()
    db_session.add(
        DataSet(
            id=42,
            type="module_tsv",
            release_id=first_release.id if existing_release_id is not None else None,
        )
    )
    await db_session.flush()

    with pytest.raises(ValidationError, match="already bound to release"):
        await create_import_command(
            db_session,
            actor_id=None,
            idempotency_key=f"module-import-mismatch:{existing_release_id}",
            data_set_id=42,
            import_type="module_tsv",
            filename="genes.tsv",
            object_key="data/42/genes.tsv",
            release_id=second_release.id,
            module_key="genes",
            checksum="a" * 64,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("release_id", [None, 999_999])
async def test_module_import_command_rejects_missing_or_unknown_release(db_session, release_id):
    """Legacy callers get a 422-compatible domain error, not worker ``int`` errors."""
    from app.core.exceptions import ValidationError
    from app.services.outbox_service import create_import_command

    with pytest.raises(ValidationError, match="release_id|required release"):
        await create_import_command(
            db_session,
            actor_id=None,
            idempotency_key=f"module-import-invalid-release:{release_id}",
            data_set_id=43,
            import_type="module_tsv",
            filename="genes.tsv",
            object_key="data/43/genes.tsv",
            release_id=release_id,
            module_key="genes",
            checksum="a" * 64,
        )
