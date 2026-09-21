"""P2-2 / ADR-0005: the import fingerprint covers exactly the semantic inputs."""

import pytest

from app.services.import_fingerprint import compute_import_fingerprint

BASE = {
    "source_sha256": "a" * 64,
    "release_id": 1,
    "assembly_id": 2,
    "importer_version": "imp-1",
    "schema_version": "sch-1",
    "normalization_version": "norm-1",
    "config_hash": "cfg-1",
}


def test_fingerprint_is_stable_and_64_hex() -> None:
    fp = compute_import_fingerprint(**BASE)
    assert fp == compute_import_fingerprint(**BASE)
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("source_sha256", "b" * 64),
        ("release_id", 99),
        ("assembly_id", 99),
        ("importer_version", "imp-2"),
        ("schema_version", "sch-2"),
        ("normalization_version", "norm-2"),
        ("config_hash", "cfg-2"),
    ],
)
def test_semantic_change_changes_fingerprint(field: str, new_value: object) -> None:
    """Every semantic input is inside the fingerprint: changing it must change
    the dedup key, so a re-import with different semantics is a new logical
    import rather than a false idempotent hit."""
    changed = {**BASE, field: new_value}
    assert compute_import_fingerprint(**changed) != compute_import_fingerprint(**BASE)
