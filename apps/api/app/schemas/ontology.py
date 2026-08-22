"""Read-only OLS4 ontology query contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OntologySearchResult(BaseModel):
    term_id: str | None = None
    label: str | None = None
    iri: str
    ontology_name: str | None = None
    description: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    is_obsolete: bool = False


class OntologySearchResponse(BaseModel):
    query: str
    ontology: str | None = None
    count: int = Field(ge=0)
    items: list[OntologySearchResult] = Field(default_factory=list)


class OntologyTermResponse(BaseModel):
    iri: str
    label: str | None = None
    ontology_name: str | None = None
    description: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    is_obsolete: bool = False
    parents: list[str] = Field(default_factory=list)
    children: list[str] = Field(default_factory=list)


class OntologyRelationshipGraphNode(BaseModel):
    """One OLS4 graph vertex projected for the bounded browser renderer."""

    iri: str = Field(min_length=1, max_length=2_048)
    label: str | None = Field(default=None, max_length=1_000)
    is_obsolete: bool = False


class OntologyRelationshipGraphEdge(BaseModel):
    """A relation whose endpoints both occur in the bounded node projection."""

    source: str = Field(min_length=1, max_length=2_048)
    target: str = Field(min_length=1, max_length=2_048)
    label: str | None = Field(default=None, max_length=1_000)


class OntologyRelationshipGraphResponse(BaseModel):
    """One-hop graph after server-side node/edge caps have been applied."""

    ontology: str
    root_iri: str = Field(min_length=1, max_length=2_048)
    nodes: list[OntologyRelationshipGraphNode] = Field(default_factory=list, max_length=50)
    edges: list[OntologyRelationshipGraphEdge] = Field(default_factory=list, max_length=100)
    truncated: bool = False


__all__ = [
    "OntologySearchResponse",
    "OntologySearchResult",
    "OntologyTermResponse",
    "OntologyRelationshipGraphEdge",
    "OntologyRelationshipGraphNode",
    "OntologyRelationshipGraphResponse",
]
