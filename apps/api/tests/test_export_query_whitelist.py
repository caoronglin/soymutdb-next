"""The export query whitelist is derived, not retyped.

The builder, the manifest and the frontend all need to agree on which filters
exist. This file pins the two properties that keep them from drifting:

* the API whitelist is exactly the export schema's public fields — a name the
  schema does not declare must never be accepted, and a field it does declare
  must never be refused for lack of a hand-written list entry;
* the frontend's display mirror is byte-identical to the API set, read out of
  the TypeScript source, so "the card says it can filter by X" and "the API
  accepts X" are the same statement.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.schemas.export_query import (
    SUPPORTED_QUERY_FILTERS,
    UNSUPPORTED_QUERY_FILTERS,
    ExportQueryRequest,
)
from app.schemas.variant import VariantExportFilters
from app.services.variant_export_service import PUBLIC_MANIFEST_FILTER_KEYS

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_FILTERS = REPO_ROOT / "apps" / "web" / "src" / "lib" / "export-query-filters.ts"


def _ts_string_array(source: str, name: str) -> set[str]:
    match = re.search(
        rf"export const {name}\s*=\s*\[(.*?)\]\s*as const;", source, re.DOTALL
    )
    assert match is not None, f"{name} not found in {WEB_FILTERS}"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_whitelist_is_the_export_schema_minus_pagination() -> None:
    expected = set(VariantExportFilters.model_fields) - {"limit", "cursor"}
    assert SUPPORTED_QUERY_FILTERS == expected


def test_manifest_and_query_whitelists_are_the_same_set() -> None:
    """A filter a caller can submit is a filter a manifest can cite."""
    assert PUBLIC_MANIFEST_FILTER_KEYS == SUPPORTED_QUERY_FILTERS


def test_unbacked_filters_are_disjoint_from_supported_ones() -> None:
    assert SUPPORTED_QUERY_FILTERS.isdisjoint(UNSUPPORTED_QUERY_FILTERS)


def test_every_supported_filter_round_trips_through_the_request() -> None:
    """A whitelisted key must actually bind, not just be listed."""
    values = {
        "assembly": "Wm82.a4.v1",
        "chromosome": "chr01",
        "start": 1,
        "end": 10,
        "ref": "A",
        "alt": "T",
        "gene_id": "Glyma.01G000100",
        "variant_type": "SNP",
        "consequence": "missense_variant",
        "impact": "HIGH",
        "min_af": 0.1,
        "max_af": 0.9,
        "mutant_line_public_id": "ML-0001",
    }
    assert set(values) == set(SUPPORTED_QUERY_FILTERS)
    request = ExportQueryRequest(filters=values)
    assert set(request.filters) == set(SUPPORTED_QUERY_FILTERS)


def test_frontend_mirror_matches_the_api_whitelist() -> None:
    source = WEB_FILTERS.read_text()
    assert _ts_string_array(source, "SUPPORTED_EXPORT_QUERY_FILTERS") == set(
        SUPPORTED_QUERY_FILTERS
    )
    assert _ts_string_array(source, "EXPORT_QUERY_UNSUPPORTED_LABELS") == set(
        UNSUPPORTED_QUERY_FILTERS
    )
