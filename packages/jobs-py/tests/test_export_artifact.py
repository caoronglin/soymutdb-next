"""Contract of the export artifact identity (API and worker share it).

The worker writes the artifact and records its object key; the API signs a
download URL for that same key later.  If the two sides derived the key
independently, a download would 404 — so the derivation is pinned here.
"""

from __future__ import annotations

import pytest

from soymutdb_jobs.export_artifact import (
    EXPORT_ARTIFACT_PREFIX,
    EXPORT_FORMATS,
    build_export_artifact_key,
    build_export_filename,
)

EXPORT_ID = "3f1b2c4d-0000-4000-8000-000000000000"


def test_the_filename_states_the_export_and_the_format() -> None:
    assert build_export_filename(EXPORT_ID, "tsv", False) == (
        f"soymutdb_export_{EXPORT_ID}.tsv"
    )
    assert build_export_filename(EXPORT_ID, "vcf", True) == (
        f"soymutdb_export_{EXPORT_ID}.vcf.gz"
    )


def test_the_key_is_scoped_to_the_export() -> None:
    filename = build_export_filename(EXPORT_ID, "json", False)
    assert build_export_artifact_key(EXPORT_ID, filename) == (
        f"{EXPORT_ARTIFACT_PREFIX}/{EXPORT_ID}/{filename}"
    )


def test_the_key_cannot_escape_its_prefix() -> None:
    key = build_export_artifact_key(EXPORT_ID, "file.tsv")
    assert key.startswith(f"{EXPORT_ARTIFACT_PREFIX}/")
    assert ".." not in key


def test_only_the_supported_formats_are_accepted() -> None:
    assert EXPORT_FORMATS == frozenset({"vcf", "tsv", "csv", "json", "bed"})
    with pytest.raises(ValueError):
        build_export_filename(EXPORT_ID, "xlsx", False)
