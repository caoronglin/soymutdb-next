"""Object-key namespacing for pre-rendered gene artifacts (R07).

The static-page builder writes two artifacts per gene to object storage. Their
keys must be scoped by **release** and **assembly**: an accession repeats across
assemblies (v4 and v5 are distinct coordinate namespaces) and the same assembly
is republished under each release. A key that omits either component lets one
artifact silently overwrite another.

These tests lock the pure key builder. Real object-storage read/write remains an
integration concern (see the module docstring note in the repository docs);
no in-memory mock is treated as evidence of storage isolation.
"""

from __future__ import annotations

import pytest

from soymutdb_worker.tasks.static_pages import gene_object_key


def test_key_is_release_and_assembly_scoped() -> None:
    key = gene_object_key(
        "Glyma.01G000100", assembly_id=1, release_id=7, extension="json.gz"
    )
    assert key == "7/1/genes/Glyma.01G000100.json.gz"


def test_same_accession_in_two_assemblies_does_not_collide() -> None:
    v4 = gene_object_key("Glyma.01G000100", assembly_id=1, release_id=7, extension="html.gz")
    v5 = gene_object_key("Glyma.01G000100", assembly_id=2, release_id=7, extension="html.gz")
    assert v4 != v5
    assert v4 == "7/1/genes/Glyma.01G000100.html.gz"
    assert v5 == "7/2/genes/Glyma.01G000100.html.gz"


def test_same_assembly_in_two_releases_does_not_collide() -> None:
    r1 = gene_object_key("Glyma.01G000100", assembly_id=1, release_id=7, extension="json.gz")
    r2 = gene_object_key("Glyma.01G000100", assembly_id=1, release_id=8, extension="json.gz")
    assert r1 != r2


def test_json_and_html_artifacts_do_not_collide() -> None:
    json_key = gene_object_key("G1", assembly_id=1, release_id=7, extension="json.gz")
    html_key = gene_object_key("G1", assembly_id=1, release_id=7, extension="html.gz")
    assert json_key != html_key


def test_release_omitted_falls_back_to_assembly_only_namespace() -> None:
    """Backward compatibility for archives written before release scoping."""
    key = gene_object_key("Glyma.01G000100", assembly_id=1, release_id=None, extension="json.gz")
    assert key == "1/genes/Glyma.01G000100.json.gz"


def test_string_and_int_identifiers_agree() -> None:
    assert gene_object_key("G1", assembly_id="1", release_id="7", extension="json.gz") == (
        gene_object_key("G1", assembly_id=1, release_id=7, extension="json.gz")
    )


def test_empty_accession_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        gene_object_key("  ", assembly_id=1, release_id=7, extension="json.gz")


def test_accession_with_path_separator_is_rejected() -> None:
    """A crafted accession must not escape the gene namespace."""
    for accession in ("../secret", "a/b", "a\\\\b"):
        with pytest.raises(ValueError, match="path separator"):
            gene_object_key(accession, assembly_id=1, release_id=7, extension="json.gz")


def test_unknown_extension_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported artifact extension"):
        gene_object_key("G1", assembly_id=1, release_id=7, extension="json")
