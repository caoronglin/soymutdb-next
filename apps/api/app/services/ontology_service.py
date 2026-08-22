"""Bounded read-only OLS4 ontology queries.

This service only queries the public OLS4 API.  It never executes or
persists uploaded content, and every returned string is length-bounded before
it reaches the API response.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx

from ..core.exceptions import ServiceUnavailableError, ValidationError
from ..schemas.ontology import (
    OntologyRelationshipGraphEdge,
    OntologyRelationshipGraphNode,
    OntologyRelationshipGraphResponse,
    OntologySearchResponse,
    OntologySearchResult,
    OntologyTermResponse,
)

OLS4_BASE_URL = "https://www.ebi.ac.uk/ols4/api"
ALLOWED_ONTOLOGIES = frozenset(
    {
        "go",
        "po",
        "chebi",
        "efo",
        "so",
        "bao",
        "mp",
        "pato",
        "ncbitaxon",
    }
)
MAX_QUERY_LENGTH = 200
MAX_RESULTS = 50
MAX_FIELD_LENGTH = 1_000
MAX_GRAPH_NODES = 50
MAX_GRAPH_EDGES = 100
#: Hard ceiling for the untrusted OLS4 relationship-graph HTTP body.
MAX_GRAPH_RESPONSE_BYTES = 1 * 1024 * 1024
_GRAPH_RESPONSE_READ_CHUNK_BYTES = 64 * 1024


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:MAX_FIELD_LENGTH]


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        cleaned: list[str] = []
        for item in value:
            text = _clean_string(item)
            if text is not None:
                cleaned.append(text)
        return cleaned
    text = _clean_string(value)
    return [text] if text is not None else []


def _parse_doc(doc: dict[str, Any]) -> OntologySearchResult:
    return OntologySearchResult(
        term_id=_clean_string(doc.get("obo_id") or doc.get("short_form")),
        label=_clean_string(doc.get("label") or doc.get("name")),
        iri=str(doc.get("iri") or ""),
        ontology_name=_clean_string(doc.get("ontology_name") or doc.get("ontologyId")),
        description=_string_list(doc.get("description")),
        synonyms=_string_list(doc.get("synonym") or doc.get("synonyms")),
        is_obsolete=bool(doc.get("is_obsolete", False)),
    )


def validate_ontology_query(*, query: str, ontology: str | None, limit: int) -> None:
    if not query.strip() or len(query) > MAX_QUERY_LENGTH:
        raise ValidationError(
            "Ontology query must be non-empty and at most 200 characters"
        )
    if ontology is not None and ontology not in ALLOWED_ONTOLOGIES:
        raise ValidationError(
            f"Ontology {ontology!r} is not in the read-only allowlist",
            details={"ontology": ontology},
        )
    if limit < 1 or limit > MAX_RESULTS:
        raise ValidationError(
            f"Ontology result limit must be between 1 and {MAX_RESULTS}"
        )


def validate_relationship_graph_request(
    *,
    ontology: str,
    iri: str,
    max_nodes: int,
    max_edges: int,
) -> None:
    """Validate graph requests before the adapter reaches the OLS4 upstream."""
    validate_ontology_query(query="graph", ontology=ontology, limit=1)
    if not iri.strip() or len(iri) > 2_048:
        raise ValidationError("Ontology term IRI must be non-empty and at most 2048 characters")
    if max_nodes < 1 or max_nodes > MAX_GRAPH_NODES:
        raise ValidationError(
            f"Ontology graph node limit must be between 1 and {MAX_GRAPH_NODES}"
        )
    if max_edges < 1 or max_edges > MAX_GRAPH_EDGES:
        raise ValidationError(
            f"Ontology graph edge limit must be between 1 and {MAX_GRAPH_EDGES}"
        )


def _graph_iri(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or len(text) > 2_048:
        return None
    return text


async def _read_bounded_relationship_graph_payload(response: httpx.Response) -> Any:
    """Read one OLS4 graph body without materialising an unbounded response."""
    declared_length = response.headers.get("content-length")
    if declared_length is not None:
        try:
            content_length = int(declared_length)
        except ValueError:
            content_length = None
        if content_length is not None and content_length > MAX_GRAPH_RESPONSE_BYTES:
            raise ValueError("OLS4 relationship graph response exceeds the byte limit")

    body = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=_GRAPH_RESPONSE_READ_CHUNK_BYTES):
        if len(body) + len(chunk) > MAX_GRAPH_RESPONSE_BYTES:
            raise ValueError("OLS4 relationship graph response exceeds the byte limit")
        body.extend(chunk)
    return json.loads(body)


def _bounded_relationship_graph(
    *,
    payload: dict[str, Any],
    ontology: str,
    root_iri: str,
    max_nodes: int,
    max_edges: int,
) -> OntologyRelationshipGraphResponse:
    """Project the OLS4 graph into a small, referentially closed graph.

    OLS4's graph endpoint can return every direct relationship for a term.
    The UI must never receive a large graph or an edge that points outside the
    returned node set, even if the upstream response changes shape or size.
    """
    raw_nodes = payload.get("nodes")
    raw_nodes = raw_nodes if isinstance(raw_nodes, list) else []

    unique_nodes: dict[str, OntologyRelationshipGraphNode] = {}
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            continue
        iri = _graph_iri(raw_node.get("iri"))
        if iri is None or iri in unique_nodes:
            continue
        unique_nodes[iri] = OntologyRelationshipGraphNode(
            iri=iri,
            label=_clean_string(raw_node.get("label") or raw_node.get("name")),
            is_obsolete=bool(raw_node.get("is_obsolete", False)),
        )

    root = unique_nodes.pop(root_iri, None)
    if root is None:
        root = OntologyRelationshipGraphNode(iri=root_iri)
    nodes = [root]
    truncated = False
    for node in unique_nodes.values():
        if len(nodes) >= max_nodes:
            truncated = True
            continue
        nodes.append(node)
    selected_iris = {node.iri for node in nodes}

    raw_edges = payload.get("edges")
    raw_edges = raw_edges if isinstance(raw_edges, list) else []
    edges: list[OntologyRelationshipGraphEdge] = []
    edge_keys: set[tuple[str, str, str | None]] = set()
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            continue
        source = _graph_iri(raw_edge.get("source"))
        target = _graph_iri(raw_edge.get("target"))
        label = _clean_string(raw_edge.get("label") or raw_edge.get("uri"))
        if (
            source is None
            or target is None
            or source not in selected_iris
            or target not in selected_iris
        ):
            truncated = True
            continue
        edge_key = (source, target, label)
        if edge_key in edge_keys:
            continue
        if len(edges) >= max_edges:
            truncated = True
            continue
        edge_keys.add(edge_key)
        edges.append(
            OntologyRelationshipGraphEdge(source=source, target=target, label=label)
        )

    return OntologyRelationshipGraphResponse(
        ontology=ontology,
        root_iri=root_iri,
        nodes=nodes,
        edges=edges,
        truncated=truncated,
    )


async def search_ontology(
    *,
    query: str,
    ontology: str | None,
    limit: int,
) -> OntologySearchResponse:
    validate_ontology_query(query=query, ontology=ontology, limit=limit)
    params: dict[str, Any] = {"q": query.strip(), "size": limit}
    if ontology is not None:
        params["ontology"] = ontology
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            response = await client.get(f"{OLS4_BASE_URL}/search", params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ServiceUnavailableError(
            "OLS4 ontology service is unavailable",
            details={"reason": "upstream_error"},
        ) from exc

    if isinstance(payload, dict):
        response_payload = (
            payload.get("response") if isinstance(payload.get("response"), dict) else {}
        )
        docs = (
            response_payload.get("docs", [])
            if isinstance(response_payload, dict)
            else []
        )
    else:
        docs = []
    if not isinstance(docs, list):
        docs = []
    items = [_parse_doc(doc) for doc in docs[:limit] if isinstance(doc, dict)]
    return OntologySearchResponse(
        query=query.strip(),
        ontology=ontology,
        count=len(items),
        items=items,
    )


async def get_term(*, ontology: str, iri: str) -> OntologyTermResponse:
    validate_ontology_query(query="term", ontology=ontology, limit=1)
    encoded_iri = quote(iri, safe="")
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            response = await client.get(
                f"{OLS4_BASE_URL}/ontologies/{ontology}/terms/{encoded_iri}"
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ServiceUnavailableError(
            "OLS4 ontology service is unavailable",
            details={"reason": "upstream_error"},
        ) from exc

    if not isinstance(payload, dict):
        raise ServiceUnavailableError("OLS4 returned an invalid term payload")
    links_value = payload.get("_links")
    links: dict[str, Any] = links_value if isinstance(links_value, dict) else {}
    parents = _string_list(payload.get("parents") or links.get("parents", []))
    children = _string_list(payload.get("children") or links.get("children", []))
    return OntologyTermResponse(
        iri=str(payload.get("iri") or iri),
        label=_clean_string(payload.get("label") or payload.get("name")),
        ontology_name=_clean_string(payload.get("ontology_name")),
        description=_string_list(payload.get("description")),
        synonyms=_string_list(payload.get("synonym") or payload.get("synonyms")),
        is_obsolete=bool(payload.get("is_obsolete", False)),
        parents=parents,
        children=children,
    )


async def get_relationship_graph(
    *,
    ontology: str,
    iri: str,
    max_nodes: int,
    max_edges: int,
) -> OntologyRelationshipGraphResponse:
    """Fetch one OLS4 relationship graph and enforce local response caps."""
    validate_relationship_graph_request(
        ontology=ontology,
        iri=iri,
        max_nodes=max_nodes,
        max_edges=max_edges,
    )
    encoded_iri = quote(iri.strip(), safe="")
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            async with client.stream(
                "GET",
                f"{OLS4_BASE_URL}/ontologies/{ontology}/terms/{encoded_iri}/graph",
            ) as response:
                response.raise_for_status()
                payload = await _read_bounded_relationship_graph_payload(response)
    except (httpx.HTTPError, ValueError) as exc:
        raise ServiceUnavailableError(
            "OLS4 ontology service is unavailable",
            details={"reason": "upstream_error"},
        ) from exc

    if not isinstance(payload, dict):
        raise ServiceUnavailableError("OLS4 returned an invalid relationship graph payload")
    return _bounded_relationship_graph(
        payload=payload,
        ontology=ontology,
        root_iri=iri.strip(),
        max_nodes=max_nodes,
        max_edges=max_edges,
    )


__all__ = [
    "ALLOWED_ONTOLOGIES",
    "MAX_GRAPH_EDGES",
    "MAX_GRAPH_NODES",
    "MAX_GRAPH_RESPONSE_BYTES",
    "MAX_RESULTS",
    "OLS4_BASE_URL",
    "get_term",
    "get_relationship_graph",
    "search_ontology",
    "validate_relationship_graph_request",
    "validate_ontology_query",
]
