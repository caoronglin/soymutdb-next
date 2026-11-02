"""Pydantic safety contracts for Import Studio request/response models."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.import_studio import (
    DataPatchCreateRequest,
    DatasetVersionCreateRequest,
    FieldMappingUpdateRequest,
    ImportDraftCreateRequest,
    ImportValidationRequest,
)


def _valid_dataset_version() -> dict[str, object]:
    return {
        "dataset_id": 1,
        "filename": "genes.tsv",
        "object_key": "s3://bucket/genes.tsv",
        "checksum_sha256": "a" * 64,
        "source": "NCBI RefSeq",
        "license": "CC0",
        "mime_type": "text/tab-separated-values",
        "row_count": 10,
        "column_count": 5,
    }


def test_dataset_version_rejects_legacy_xls_code_files_and_bad_checksum() -> None:
    with pytest.raises(PydanticValidationError, match="legacy .xls"):
        DatasetVersionCreateRequest(
            **{**_valid_dataset_version(), "filename": "old.xls"}
        )
    with pytest.raises(PydanticValidationError, match="code files"):
        DatasetVersionCreateRequest(
            **{**_valid_dataset_version(), "filename": "plugin.py"}
        )
    with pytest.raises(PydanticValidationError, match="checksum_sha256"):
        DatasetVersionCreateRequest(
            **{**_valid_dataset_version(), "checksum_sha256": "bad"}
        )


def test_module_aware_limits_reach_the_scientific_branch() -> None:
    """A registered module may carry the wider scientific shape.

    The generic page limits must not be baked into the request schemas:
    ``MAX_SCIENCE_ROWS`` / ``MAX_SCIENCE_COLUMNS`` are unreachable otherwise.
    """
    version = DatasetVersionCreateRequest(
        **{
            **_valid_dataset_version(),
            "row_count": 2_000_000,
            "column_count": 200,
            "module_key": "genes",
        }
    )
    assert version.module_key == "genes"

    with pytest.raises(PydanticValidationError, match="Generic pages are limited to 50 columns"):
        DatasetVersionCreateRequest(**{**_valid_dataset_version(), "column_count": 200})

    validation = ImportValidationRequest(
        row_count=2_000_000,
        column_count=200,
        field_mapping=[],
        module_key="genes",
    )
    assert validation.module_key == "genes"

    with pytest.raises(PydanticValidationError, match="Generic pages"):
        ImportValidationRequest(
            row_count=2_000_000,
            column_count=200,
            field_mapping=[],
        )

    with pytest.raises(PydanticValidationError, match="less than or equal to 256"):
        ImportValidationRequest(
            row_count=10,
            column_count=257,
            field_mapping=[],
            module_key="genes",
        )


def test_draft_and_mapping_contracts_are_bounded() -> None:
    draft = ImportDraftCreateRequest(
        dataset_version_id=uuid.uuid4(),
        module_key="genes",
        row_count=2_000_000,
        column_count=200,
    )
    assert draft.module_key == "genes"

    with pytest.raises(PydanticValidationError, match="Generic pages"):
        ImportValidationRequest(
            row_count=100_001,
            column_count=10,
            field_mapping=[],
        )
    with pytest.raises(PydanticValidationError, match="at most 50"):
        FieldMappingUpdateRequest(
            mappings=[{"source_field": f"c{i}", "target_field": f"t{i}"} for i in range(51)]
        )
    with pytest.raises(PydanticValidationError, match="at most 10000"):
        DataPatchCreateRequest(
            patches=[
                {
                    "row_key": "r1",
                    "column_name": "value",
                    "new_value": "x",
                }
                for _ in range(10_001)
            ]
        )
