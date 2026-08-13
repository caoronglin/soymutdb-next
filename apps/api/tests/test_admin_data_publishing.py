import pytest


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
