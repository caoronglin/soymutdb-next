"""DB-free contracts for the Import Studio validation/patch/manifest service."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.exceptions import ValidationError
from app.services.import_studio_service import (
    apply_data_patches,
    build_publication_manifest,
    validate_import_draft_snapshot,
    validate_data_patches,
    validate_field_mapping,
    validate_import_shape,
)


def test_generic_page_shape_enforces_100k_rows_and_50_columns() -> None:
    validate_import_shape(row_count=100_000, column_count=50, module_key=None)
    with pytest.raises(ValidationError, match="100,000"):
        validate_import_shape(row_count=100_001, column_count=10, module_key=None)
    with pytest.raises(ValidationError, match="50 columns"):
        validate_import_shape(row_count=10, column_count=51, module_key=None)


def test_registered_schema_allows_larger_streaming_bounds() -> None:
    validate_import_shape(row_count=2_000_000, column_count=200, module_key="genes")
    with pytest.raises(ValidationError, match="streaming limit"):
        validate_import_shape(row_count=2_000_001, column_count=10, module_key="genes")


def test_field_mapping_rejects_duplicates_unknown_and_reserved_targets() -> None:
    columns = ["gene_id", "chromosome", "position"]
    validate_field_mapping(
        [
            {"source_field": "gene_id", "target_field": "id"},
            {"source_field": "chromosome", "target_field": "chr"},
        ],
        columns=columns,
    )
    with pytest.raises(ValidationError, match="must be unique"):
        validate_field_mapping(
            [
                {"source_field": "gene_id", "target_field": "id"},
                {"source_field": "gene_id", "target_field": "id2"},
            ],
            columns=columns,
        )
    with pytest.raises(ValidationError, match="not present"):
        validate_field_mapping(
            [{"source_field": "missing", "target_field": "id"}],
            columns=columns,
        )
    with pytest.raises(ValidationError, match="reserved"):
        validate_field_mapping(
            [{"source_field": "gene_id", "target_field": "script"}],
            columns=columns,
        )
    with pytest.raises(ValidationError, match="URLs"):
        validate_field_mapping(
            [
                {
                    "source_field": "gene_id",
                    "target_field": "id",
                    "transform": {"target": "https://evil.example"},
                }
            ],
            columns=columns,
        )


def test_patches_are_bounded_and_formula_values_are_neutralized() -> None:
    rows = [{"_row_key": "r1", "gene_id": "G1", "value": "normal"}]
    patched = apply_data_patches(
        rows,
        [
            {
                "row_key": "r1",
                "column_name": "value",
                "new_value": "=HYPERLINK(\"https://evil.example\")",
            }
        ],
    )
    assert patched[0]["value"].startswith("'=")
    with pytest.raises(ValidationError, match="not found"):
        apply_data_patches(rows, [{"row_key": "r2", "column_name": "value", "new_value": "x"}])
    with pytest.raises(ValidationError, match="10,000"):
        apply_data_patches(rows, [{"row_key": "r1", "column_name": "x", "new_value": "x"}] * 10_001)


def test_persisted_patches_reject_formulas_urls_and_scripts() -> None:
    validate_data_patches(
        [{"row_key": "r1", "column_name": "value", "new_value": "safe"}]
    )
    with pytest.raises(ValidationError, match="formulas"):
        validate_data_patches(
            [{"row_key": "r1", "column_name": "value", "new_value": "=HYPERLINK(1)"}]
        )
    with pytest.raises(ValidationError, match="URLs"):
        validate_data_patches(
            [{"row_key": "r1", "column_name": "value", "new_value": "https://evil.example"}]
        )
    with pytest.raises(ValidationError, match="script/HTML"):
        validate_data_patches(
            [{"row_key": "r1", "column_name": "value", "new_value": "<script>alert(1)</script>"}]
        )


def test_persisted_patches_reject_multiple_values_for_the_same_cell() -> None:
    with pytest.raises(ValidationError, match="one value per cell"):
        validate_data_patches(
            [
                {"row_key": "r1", "column_name": "value", "new_value": "first"},
                {"row_key": "r1", "column_name": "value", "new_value": "second"},
            ]
        )


def test_publication_manifest_is_deterministic_and_source_bound() -> None:
    manifest = build_publication_manifest(
        draft_id="draft-1",
        dataset_version_id="version-1",
        checksum_sha256="a" * 64,
        row_count=10,
        column_count=5,
        module_key=None,
    )
    assert manifest["schema_version"] == 2
    assert manifest["draft_id"] == "draft-1"
    assert manifest["manifest_sha256"]
    assert len(manifest["manifest_sha256"]) == 64


def test_publication_manifest_binds_canonical_mapping_and_patches() -> None:
    common = {
        "draft_id": "draft-1",
        "dataset_version_id": "version-1",
        "checksum_sha256": "a" * 64,
        "row_count": 10,
        "column_count": 5,
        "module_key": None,
    }
    first = build_publication_manifest(
        **common,
        field_mapping=[
            {"source_field": "gene_id", "target_field": "id", "position": 0, "transform": {}}
        ],
        patches=[
            {
                "row_key": "r1",
                "column_name": "gene_id",
                "old_value": "G1",
                "new_value": "GX",
                "patch_type": "set",
            }
        ],
        generated_at=datetime(2026, 8, 22, tzinfo=UTC),
    )
    reordered = build_publication_manifest(
        **common,
        field_mapping=[
            {"position": 0, "transform": {}, "target_field": "id", "source_field": "gene_id"}
        ],
        patches=[
            {
                "patch_type": "set",
                "new_value": "GX",
                "old_value": "G1",
                "column_name": "gene_id",
                "row_key": "r1",
            }
        ],
        generated_at=datetime(2026, 8, 23, tzinfo=UTC),
    )

    assert first["transformations"]["patches"][0]["new_value"] == "GX"
    assert first["manifest_sha256"] == reordered["manifest_sha256"]


def test_committed_module_draft_snapshot_requires_the_exact_import_source() -> None:
    """A frozen editing draft cannot be dispatched against a different object."""
    draft = SimpleNamespace(
        status="committed",
        module_key="genes",
        release_id=7,
        object_key="data/42/genes.tsv",
        checksum_sha256="a" * 64,
    )
    version = SimpleNamespace(dataset_id=42)

    validate_import_draft_snapshot(
        draft,
        version,
        data_set_id=42,
        release_id=7,
        module_key="genes",
        file_key="data/42/genes.tsv",
        checksum="A" * 64,
    )

    with pytest.raises(ValidationError, match="object key"):
        validate_import_draft_snapshot(
            draft,
            version,
            data_set_id=42,
            release_id=7,
            module_key="genes",
            file_key="data/42/other.tsv",
            checksum="a" * 64,
        )
    with pytest.raises(ValidationError, match="release"):
        validate_import_draft_snapshot(
            draft,
            version,
            data_set_id=42,
            release_id=8,
            module_key="genes",
            file_key="data/42/genes.tsv",
            checksum="a" * 64,
        )
