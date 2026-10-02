"""Public seed-request demand endpoint: shape, caps and the privacy contract.

Unit tests with the service stubbed out. The SQL itself is verified against
PostgreSQL in ``test_seed_request_stats_sql.py``; what matters here is the
boundary — this route is anonymous, so it must be impossible for it to hand a
caller anything about a requester.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.api.v1 import seed_requests as module
from app.schemas.seed_request import MAX_GENE_IDS

#: Field names that must never appear on this public surface.
FORBIDDEN = ("name", "email", "institution", "country", "notes", "processed_by")


@pytest.fixture
def stub_counts(monkeypatch: pytest.MonkeyPatch):
    """Record what the route asked for and return canned counts."""

    seen: dict[str, Any] = {"gene_ids": None}

    async def fake_counts(_db: Any, *, gene_ids: list[str], max_gene_ids: int = 200):
        seen["gene_ids"] = gene_ids
        return {gene: 3 for gene in gene_ids}

    async def fake_total(_db: Any) -> int:
        return 7

    monkeypatch.setattr(module.service, "count_requests_by_gene", fake_counts)
    monkeypatch.setattr(module.service, "total_requests", fake_total)
    return seen


async def test_echoes_every_requested_gene_including_zero(stub_counts) -> None:
    response = await module.seed_request_stats(db=None, gene_ids="A,B,C")
    body = response.model_dump()

    assert [item["gene_id"] for item in body["items"]] == ["A", "B", "C"]
    assert all(item["requests"] == 3 for item in body["items"])
    assert body["total_requests"] == 7


async def test_empty_query_returns_no_items(stub_counts) -> None:
    body = (await module.seed_request_stats(db=None, gene_ids="")).model_dump()

    assert body["items"] == []
    assert body["total_requests"] == 7
    assert stub_counts["gene_ids"] == []


async def test_whitespace_and_blanks_are_ignored_and_order_deduped(stub_counts) -> None:
    body = (
        await module.seed_request_stats(db=None, gene_ids=" A ,, B ,A,  ")
    ).model_dump()

    assert [item["gene_id"] for item in body["items"]] == ["A", "B"]


async def test_gene_list_is_capped(stub_counts) -> None:
    over = ",".join(f"GENE{i}" for i in range(MAX_GENE_IDS + 50))
    body = (await module.seed_request_stats(db=None, gene_ids=over)).model_dump()

    assert len(body["items"]) == MAX_GENE_IDS
    assert len(stub_counts["gene_ids"]) <= MAX_GENE_IDS


async def test_response_carries_no_requester_fields(stub_counts) -> None:
    """The anonymous route must not be able to leak who asked for what."""
    payload = (await module.seed_request_stats(db=None, gene_ids="A")).model_dump()
    serialized = repr(payload)

    for field in FORBIDDEN:
        assert field not in payload.get("items", [{}])[0], f"{field} leaked into a public item"
        assert f"'{field}'" not in serialized, f"{field} appears in the public payload"


def test_route_is_registered_under_the_public_prefix() -> None:
    """A `/admin` path would imply a capability check that this route has none of."""
    paths = {getattr(route, "path", None) for route in module.router.routes}
    assert "/seed-requests/stats" in paths
