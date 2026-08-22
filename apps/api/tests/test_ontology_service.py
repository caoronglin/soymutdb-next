"""Offline contracts for the read-only OLS4 ontology service."""

from __future__ import annotations

import json

import pytest
from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.services import ontology_service
from app.services.ontology_service import search_ontology


class _Response:
    def __init__(
        self,
        payload: object,
        *,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.payload = payload
        self.headers = headers or {}
        self._chunks = chunks if chunks is not None else [json.dumps(payload).encode("utf-8")]
        self.streamed_bytes = 0

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload

    async def aiter_bytes(self, chunk_size: int | None = None):
        for chunk in self._chunks:
            if chunk_size is None:
                self.streamed_bytes += len(chunk)
                yield chunk
                continue
            for start in range(0, len(chunk), chunk_size):
                fragment = chunk[start : start + chunk_size]
                self.streamed_bytes += len(fragment)
                yield fragment


class _StreamContext:
    def __init__(self, response: _Response) -> None:
        self.response = response

    async def __aenter__(self) -> _Response:
        return self.response

    async def __aexit__(self, *args: object) -> None:
        return None


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.request: tuple[str, dict[str, object]] | None = None

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, **kwargs: object) -> _Response:
        self.request = (url, kwargs)
        return self.response

    def stream(self, method: str, url: str, **kwargs: object) -> _StreamContext:
        self.request = (url, kwargs)
        assert method == "GET"
        return _StreamContext(self.response)


@pytest.mark.asyncio
async def test_search_parses_bounded_ols4_docs(monkeypatch) -> None:
    client = _Client(
        _Response(
            {
                "response": {
                    "docs": [
                        {
                            "obo_id": "GO:0000001",
                            "label": "mitochondrion inheritance",
                            "iri": "http://purl.obolibrary.org/obo/GO_0000001",
                            "ontology_name": "go",
                            "description": ["a process"],
                            "synonym": ["mitochondrial inheritance"],
                            "is_obsolete": False,
                        }
                    ]
                }
            }
        )
    )
    monkeypatch.setattr(ontology_service.httpx, "AsyncClient", lambda *a, **k: client)

    result = await search_ontology(query="mitochondrion", ontology="go", limit=10)
    assert result.count == 1
    assert result.items[0].label == "mitochondrion inheritance"
    assert client.request is not None
    assert client.request[0].endswith("/search")


@pytest.mark.asyncio
async def test_search_fails_closed_on_invalid_inputs_and_upstream_error(
    monkeypatch,
) -> None:
    with pytest.raises(ValidationError):
        await search_ontology(query="", ontology="go", limit=10)
    with pytest.raises(ValidationError):
        await search_ontology(query="x", ontology="not-allowed", limit=10)

    class _Broken:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object):
            return None

        async def get(self, *args: object, **kwargs: object):
            raise ontology_service.httpx.ConnectError("network")

    monkeypatch.setattr(ontology_service.httpx, "AsyncClient", lambda *a, **k: _Broken())
    with pytest.raises(ServiceUnavailableError):
        await search_ontology(query="x", ontology="go", limit=10)


@pytest.mark.asyncio
async def test_relationship_graph_caps_nodes_edges_and_drops_dangling_edges(
    monkeypatch,
) -> None:
    root = "http://example.test/ROOT"
    parent = "http://example.test/PARENT"
    omitted = "http://example.test/OMITTED"
    client = _Client(
        _Response(
            {
                "nodes": [
                    {"iri": root, "label": "Root"},
                    {"iri": parent, "label": "Parent"},
                    {"iri": omitted, "label": "Omitted"},
                ],
                "edges": [
                    {"source": root, "target": parent, "label": "is_a"},
                    {"source": parent, "target": omitted, "label": "is_a"},
                ],
            }
        )
    )
    monkeypatch.setattr(ontology_service.httpx, "AsyncClient", lambda *a, **k: client)

    result = await ontology_service.get_relationship_graph(
        ontology="go",
        iri=root,
        max_nodes=2,
        max_edges=1,
    )

    assert [node.iri for node in result.nodes] == [root, parent]
    assert [(edge.source, edge.target) for edge in result.edges] == [(root, parent)]
    assert result.truncated is True
    assert client.request is not None
    assert client.request[0].endswith("/graph")


@pytest.mark.asyncio
async def test_relationship_graph_rejects_limits_above_the_server_caps() -> None:
    with pytest.raises(ValidationError):
        await ontology_service.get_relationship_graph(
            ontology="go",
            iri="http://example.test/ROOT",
            max_nodes=51,
            max_edges=1,
        )

    with pytest.raises(ValidationError):
        await ontology_service.get_relationship_graph(
            ontology="go",
            iri="http://example.test/ROOT",
            max_nodes=1,
            max_edges=101,
        )


@pytest.mark.asyncio
async def test_relationship_graph_rejects_an_advertised_oversized_upstream_body(
    monkeypatch,
) -> None:
    root = "http://example.test/ROOT"
    byte_limit = 100
    monkeypatch.setattr(ontology_service, "MAX_GRAPH_RESPONSE_BYTES", byte_limit, raising=False)
    client = _Client(
        _Response(
            {"nodes": [{"iri": root, "label": "Root"}], "edges": []},
            headers={"content-length": str(byte_limit + 1)},
        )
    )
    monkeypatch.setattr(ontology_service.httpx, "AsyncClient", lambda *a, **k: client)

    with pytest.raises(ServiceUnavailableError) as raised:
        await ontology_service.get_relationship_graph(
            ontology="go",
            iri=root,
            max_nodes=1,
            max_edges=1,
        )

    assert raised.value.details == {"reason": "upstream_error"}
    assert client.response.streamed_bytes == 0


@pytest.mark.asyncio
async def test_relationship_graph_rejects_chunked_upstream_body_over_byte_limit(
    monkeypatch,
) -> None:
    root = "http://example.test/ROOT"
    byte_limit = 100
    monkeypatch.setattr(ontology_service, "MAX_GRAPH_RESPONSE_BYTES", byte_limit, raising=False)
    client = _Client(
        _Response(
            {"nodes": [{"iri": root, "label": "Root"}], "edges": []},
            chunks=[b"x" * (byte_limit + 1)],
        )
    )
    monkeypatch.setattr(ontology_service.httpx, "AsyncClient", lambda *a, **k: client)

    with pytest.raises(ServiceUnavailableError) as raised:
        await ontology_service.get_relationship_graph(
            ontology="go",
            iri=root,
            max_nodes=1,
            max_edges=1,
        )

    assert raised.value.details == {"reason": "upstream_error"}


@pytest.mark.asyncio
async def test_relationship_graph_preserves_a_supported_long_root_iri(monkeypatch) -> None:
    root = f"http://example.test/{'a' * 1_001}"
    client = _Client(_Response({"nodes": [{"iri": root, "label": "Root"}], "edges": []}))
    monkeypatch.setattr(ontology_service.httpx, "AsyncClient", lambda *a, **k: client)

    result = await ontology_service.get_relationship_graph(
        ontology="go",
        iri=root,
        max_nodes=1,
        max_edges=1,
    )

    assert result.nodes == [
        ontology_service.OntologyRelationshipGraphNode(iri=root, label="Root")
    ]
