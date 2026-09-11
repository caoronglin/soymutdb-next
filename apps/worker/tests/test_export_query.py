"""Variant export query contract tests."""

from __future__ import annotations

from soymutdb_worker.tasks.export import build_export_query


def test_export_query_applies_every_public_api_filter() -> None:
    filters = {
        "release_key": "release-7",
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
        "release_key = %(release_key)s",
        "assembly_key = %(assembly)s",
        "chromosome = %(chromosome)s",
        "position >= %(start)s",
        "position <= %(end)s",
        "ref_allele = %(ref)s",
        "alt_allele = %(alt)s",
        "gene_id = %(gene_id)s",
        "mutant_line_surrogate_id = %(ml_id)s",
        "variant_type = %(vtype)s",
        "consequence = %(consequence)s",
        "impact = %(impact)s",
        "allele_frequency >= %(min_af)s",
        "allele_frequency <= %(max_af)s",
    )
    assert all(fragment in query for fragment in expected_fragments)
    assert params == {
        "release_key": "release-7",
        "assembly": "Wm82.a4.v1",
        "chromosome": "Gm01",
        "start": 10,
        "end": 20,
        "ref": "A",
        "alt": "T",
        "gene_id": "Glyma.01G000100",
        "ml_id": 42,
        "vtype": "SNP",
        "consequence": "missense_variant",
        "impact": "MODERATE",
        "min_af": 0.1,
        "max_af": 0.9,
    }


def test_export_values_are_never_interpolated_into_sql() -> None:
    hostile = "Gm01' OR 1=1 --"
    query, params = build_export_query({"chromosome": hostile})

    assert hostile not in query
    assert params["chromosome"] == hostile
