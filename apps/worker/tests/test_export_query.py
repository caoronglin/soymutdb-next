"""Variant export query contract tests."""

from __future__ import annotations

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
        "mutant_line_id": 42,
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
        "mutant_line_surrogate_id = :mutant_line_id",
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
        "mutant_line_id": 42,
        "variant_type": "SNP",
        "consequence": "missense_variant",
        "impact": "MODERATE",
        "min_af": 0.1,
        "max_af": 0.9,
        "record_limit": 100_000_001,
    }


def test_export_values_are_never_interpolated_into_sql() -> None:
    hostile = "Gm01' OR 1=1 --"
    query, params = build_export_query({"release_key": "7", "chromosome": hostile})

    assert hostile not in query
    assert params["chromosome"] == hostile
