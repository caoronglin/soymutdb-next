import inspect

from app.schemas.search import GlobalSearchResponse, SearchResultItem, SearchResultType
from app.services.search_service import SearchService


def test_search_response_has_url_by_type_and_cursor_fields():
    response = GlobalSearchResponse(
        query="G1",
        results=[
            SearchResultItem(
                type=SearchResultType.GENE,
                id="G1",
                url="/search/genes/G1",
            )
        ],
        by_type={"gene": 1},
        cursor=None,
        next_cursor=None,
        has_more=False,
        total_count=1,
    )

    assert response.results[0].url == "/search/genes/G1"
    assert response.by_type == {"gene": 1}
    assert response.total_count == 1


def test_global_search_signature_is_canonical():
    assert list(inspect.signature(SearchService.global_search).parameters) == [
        "self",
        "db",
        "query",
        "types",
        "cursor",
        "limit",
    ]
