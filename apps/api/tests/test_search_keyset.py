"""Pure A-04 global-search cursor contracts.

PostgreSQL continuation coverage lives in ``test_search_database_integration``;
these tests deliberately exercise validation and the sealed cursor without a
database or API virtualenv.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ValidationError
from app.core.site_variant import SiteVariant
from app.schemas.search import SearchResultType
from app.schemas.search import MatchType, SearchHit
from app.services.release_context import ReleaseContext
from app.services.search_service import (
    SearchService,
    _decode_global_cursor,
    _encode_global_cursor,
    _query_fingerprint,
)


def _payload(site_variant: SiteVariant = SiteVariant.EXTERNAL) -> dict:
    mutant = (
        {"rank": 1, "score": 1.0, "public_id": "SM000044", "exhausted": False}
        if site_variant == SiteVariant.EXTERNAL
        else {"rank": 1, "score": 1.0, "name": "L-12", "id": 8, "exhausted": False}
    )
    return {
        "v": 1,
        "q": _query_fingerprint("Glyma"),
        "types": ["gene", "mutant_line", "publication"],
        "site_variant": site_variant.value,
        "release_id": 7,
        "assembly_id": 11,
        "positions": {
            "gene": {
                "rank": 1,
                "score": 1.0,
                "accession": "Glyma.01G000100",
                "assembly_id": 11,
                "exhausted": False,
            },
            "mutant_line": mutant,
            "publication": {"rank": 1, "score": 1.0, "id": 44, "exhausted": False},
        },
    }


def test_global_cursor_is_url_safe_opaque_and_round_trips() -> None:
    cursor = _encode_global_cursor(_payload())
    assert cursor
    assert set(cursor) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-." )
    assert "Glyma.01G000100" not in cursor
    assert '"gene_pk":123' not in cursor
    assert '"id":8' not in cursor
    decoded = _decode_global_cursor(
        cursor,
        query=" glyMA ",
        active_types=[
            SearchResultType.PUBLICATION,
            SearchResultType.GENE,
            SearchResultType.MUTANT_LINE,
        ],
        site_variant=SiteVariant.EXTERNAL,
        release_id=7,
        assembly_id=11,
    )
    assert decoded["positions"]["gene"]["assembly_id"] == 11


@pytest.mark.parametrize("cursor", ["", "not-a-cursor", "1.0", "-1"])
def test_global_cursor_rejects_malformed_values(cursor: str) -> None:
    with pytest.raises(ValidationError):
        _decode_global_cursor(
            cursor,
            query="Glyma",
            active_types=[SearchResultType.GENE],
            site_variant=SiteVariant.EXTERNAL,
            release_id=7,
            assembly_id=11,
        )


def test_global_cursor_keeps_decimal_legacy_compatibility() -> None:
    assert _decode_global_cursor(
        "002",
        query="anything",
        active_types=[SearchResultType.GENE],
        site_variant=SiteVariant.EXTERNAL,
        release_id=999,
        assembly_id=None,
    ) == 2


def test_global_cursor_rejects_context_mismatch() -> None:
    cursor = _encode_global_cursor(_payload())
    with pytest.raises(ValidationError, match="query"):
        _decode_global_cursor(
            cursor,
            query="other",
            active_types=[
                SearchResultType.GENE,
                SearchResultType.MUTANT_LINE,
                SearchResultType.PUBLICATION,
            ],
            site_variant=SiteVariant.EXTERNAL,
            release_id=7,
            assembly_id=11,
        )


def test_global_cursor_ignores_selected_type_order() -> None:
    """The same result types in a different order are the same filter set.

    The bound context is digested with ``json.dumps(sort_keys=True)``, which
    orders dict keys and leaves list elements alone. A list of type names was
    therefore order-significant: ``types=gene,publication`` and
    ``types=publication,gene`` produced different digests, and the second
    request was rejected with "Cursor context does not match this release or
    filter set" even though the caller had asked for exactly the same rows.
    ``_normalize_active_types`` exists to make cursor bindings deterministic and
    is now applied on both the encoding and the decoding side.
    """
    cursor = _encode_global_cursor(_payload())
    decoded = _decode_global_cursor(
        cursor,
        query="Glyma",
        active_types=[
            SearchResultType.PUBLICATION,
            SearchResultType.MUTANT_LINE,
            SearchResultType.GENE,
        ],
        site_variant=SiteVariant.EXTERNAL,
        release_id=7,
        assembly_id=11,
    )
    assert decoded["positions"]["gene"]["assembly_id"] == 11


def test_cursor_rejection_names_the_changed_part_without_echoing_values() -> None:
    """A rejected cursor says which bound part moved, but not what it holds.

    Without attribution a client cannot tell a stale cursor from one replayed
    against a different query. The value is deliberately withheld: the filter
    set carries the caller's own query text, and echoing it into an error
    response would hand one caller's search terms to another.
    """
    cursor = _encode_global_cursor(_payload())
    with pytest.raises(ValidationError) as error:
        _decode_global_cursor(
            cursor,
            query="other",
            active_types=[
                SearchResultType.GENE,
                SearchResultType.MUTANT_LINE,
                SearchResultType.PUBLICATION,
            ],
            site_variant=SiteVariant.EXTERNAL,
            release_id=7,
            assembly_id=11,
        )
    message = str(error.value)
    assert "query" in message
    assert "other" not in message


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 2])
async def test_global_cursor_merges_sources_by_score_without_skipping(
    monkeypatch: pytest.MonkeyPatch, limit: int
) -> None:
    """Each page is a score-contiguous merge of independently keyseted sources."""
    rows = {
        SearchResultType.GENE: [
            ("G_EXACT", 3.0, {"rank": 3, "score": 3.0, "accession": "G_EXACT", "assembly_id": 11}),
            ("G_TEXT", 1.0, {"rank": 1, "score": 1.0, "accession": "G_TEXT", "assembly_id": 11}),
        ],
        SearchResultType.MUTANT_LINE: [
            ("M_EXACT", 3.0, {"rank": 3, "score": 3.0, "public_id": "M_EXACT"}),
            ("M_TEXT", 1.0, {"rank": 1, "score": 1.0, "public_id": "M_TEXT"}),
        ],
        SearchResultType.PUBLICATION: [
            ("P_TEXT", 1.0, {"rank": 1, "score": 1.0, "id": 1}),
        ],
    }

    def make_hit(source: SearchResultType, row: tuple[str, float, dict]) -> SearchHit:
        item_id, score, cursor_key = row
        return SearchHit(
            id=item_id,
            type=source,
            title=item_id,
            score=score,
            match_type=MatchType.EXACT if score == 3.0 else MatchType.TEXT,
            url=f"/{source.value}/{item_id}",
            metadata={
                "release_id": 7,
                "assembly_id": 11 if source == SearchResultType.GENE else None,
                "_cursor": cursor_key,
            },
        )

    async def source_rows(source: SearchResultType, cursor_key: dict | None) -> list[SearchHit]:
        source_rows = rows[source]
        if cursor_key is not None:
            key_name = (
                "accession"
                if source == SearchResultType.GENE
                else "public_id"
                if source == SearchResultType.MUTANT_LINE
                else "id"
            )
            seen = cursor_key[key_name]
            next_index = next(
                index
                for index, row in enumerate(source_rows)
                if row[2][key_name] == seen
            )
            source_rows = source_rows[next_index + 1 :]
        return [make_hit(source, row) for row in source_rows]

    async def genes(
        db,
        query,
        pattern,
        limit,
        offset=0,
        *,
        cursor_key=None,
        release_id,
        assembly_id,
        site_variant,
    ):
        del db, query, pattern, limit, offset, release_id, assembly_id, site_variant
        return await source_rows(SearchResultType.GENE, cursor_key)

    async def mutants(
        db,
        query,
        pattern,
        limit,
        offset=0,
        *,
        cursor_key=None,
        release_id,
        site_variant,
    ):
        del db, query, pattern, limit, offset, release_id, site_variant
        return await source_rows(SearchResultType.MUTANT_LINE, cursor_key)

    async def publications(db, pattern, limit, offset=0, *, cursor_key=None):
        del db, pattern, limit, offset
        return await source_rows(SearchResultType.PUBLICATION, cursor_key)

    service = SearchService()
    async def resolve_context(db):
        del db
        return _resolved_context()

    monkeypatch.setattr(
        "app.services.search_service.resolve_release_context",
        resolve_context,
    )
    monkeypatch.setattr(
        "app.services.search_service.get_or_set",
        lambda name, ttl, loader, *, params=None: loader(),
    )
    monkeypatch.setattr(service, "_search_genes", genes)
    monkeypatch.setattr(service, "_search_mutant_lines", mutants)
    monkeypatch.setattr(service, "_search_publications", publications)

    async def gene_assembly_distribution(db, query, pattern, *, release_id):
        del db, query, pattern, release_id
        distribution: dict[str, int] = {}
        for row in rows[SearchResultType.GENE]:
            key = str(row[2]["assembly_id"])
            distribution[key] = distribution.get(key, 0) + 1
        return distribution

    monkeypatch.setattr(
        service, "_gene_assembly_distribution", gene_assembly_distribution
    )

    response = await service.global_search(
        object(), "same query", types=list(rows), limit=limit
    )
    all_scores = [item.score for item in response.results]
    assert all(score >= next_score for score, next_score in zip(all_scores, all_scores[1:]))
    assert all_scores == ([3.0] if limit == 1 else [3.0, 3.0])

    pages = [response]
    while pages[-1].next_cursor is not None:
        pages.append(
            await service.global_search(
                object(),
                "same query",
                types=list(rows),
                cursor=pages[-1].next_cursor,
                limit=limit,
            )
        )
    flattened = [item for page in pages for item in page.results]
    flattened_scores = [item.score for item in flattened]
    assert flattened_scores == sorted(flattened_scores, reverse=True)
    assert len({item.id for item in flattened}) == 5


def _resolved_context() -> ReleaseContext:
    return ReleaseContext(release_id=7, assembly_id=11)
