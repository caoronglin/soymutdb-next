"""Variant export query contract tests."""

from __future__ import annotations

import pytest

from soymutdb_worker.tasks.export import build_export_query


def test_export_query_applies_every_public_api_filter() -> None:
    filters = {
        "release_key": "7",
        "assembly": "Wm82.a4.v1",
        "chromosome": "Gm01",
        "start": 10,
        "end": 20,
        "ref": "A",
        "alt": "T",
        "gene_id": "Glyma.01G000100",
        "mutant_line_name": "private-lab-line",
        "variant_type": "SNP",
        "consequence": "missense_variant",
        "impact": "MODERATE",
        "min_af": 0.1,
        "max_af": 0.9,
    }

    query, params = build_export_query(filters)

    expected_fragments = (
        "v.release_id = :release_id",
        "assembly_key = :assembly",
        "chromosome = :chromosome",
        "position >= :start",
        "position <= :end",
        "ref_allele = :ref",
        "alt_allele = :alt",
        "gene_id = :gene_id",
        "mutant_line_name = :mutant_line_name",
        "variant_type = :variant_type",
        "consequence = :consequence",
        "impact = :impact",
        "allele_frequency >= :min_af",
        "allele_frequency <= :max_af",
    )
    assert all(fragment in query for fragment in expected_fragments)
    assert params == {
        "release_id": 7,
        "assembly": "Wm82.a4.v1",
        "chromosome": "Gm01",
        "start": 10,
        "end": 20,
        "ref": "A",
        "alt": "T",
        "gene_id": "Glyma.01G000100",
        "mutant_line_name": "private-lab-line",
        "variant_type": "SNP",
        "consequence": "missense_variant",
        "impact": "MODERATE",
        "min_af": 0.1,
        "max_af": 0.9,
        "record_limit": 100_000_001,
    }


def test_export_values_are_never_interpolated_into_sql() -> None:
    hostile = "Gm01' OR 1=1 --"
    query, params = build_export_query(
        {"release_key": "7", "assembly": "Wm82.a4.v1", "chromosome": hostile}
    )

    assert hostile not in query
    assert params["chromosome"] == hostile


@pytest.mark.parametrize("field", ["mutant_line_id", "mutant_line_public_id"])
def test_export_rejects_unresolved_mutant_filters(field: str) -> None:
    with pytest.raises(ValueError, match="resolved by the API"):
        build_export_query({"release_key": "7", "assembly": "Wm82.a4.v1", field: "42"})


def test_resolved_mutant_name_is_bound_not_interpolated() -> None:
    name = "private' OR true --"
    query, params = build_export_query(
        {"release_key": "7", "assembly": "Wm82.a4.v1", "mutant_line_name": name}
    )
    assert name not in query
    assert "v.mutant_line_name = :mutant_line_name" in query
    assert params["mutant_line_name"] == name


def test_export_refuses_to_span_assembly_namespaces() -> None:
    """An artifact must name exactly one namespace.

    The task is a public entry point — anything that can enqueue can call it.
    Without an assembly the query would cover every namespace of the release
    while the export record advertises a single one, so the file would mix
    coordinate systems under one name.
    """
    with pytest.raises(ValueError, match="assembly namespace is required"):
        build_export_query({"release_key": "7"})

    with pytest.raises(ValueError, match="assembly namespace is required"):
        build_export_query({"release_key": "7", "assembly": "  "})


def test_export_binds_the_assembly_namespace() -> None:
    query, params = build_export_query({"release_key": "7", "assembly": "Wm82.a4.v1"})

    assert "v.assembly_key = :assembly" in query
    assert params["assembly"] == "Wm82.a4.v1"
