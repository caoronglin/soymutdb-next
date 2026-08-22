"""Read-only OLS4 ontology query endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.plugins import get_plugin_registry
from ...schemas.ontology import (
    OntologyRelationshipGraphResponse,
    OntologySearchResponse,
    OntologyTermResponse,
)
from ...services.ontology_service import (
    get_relationship_graph,
    get_term,
    search_ontology,
)
from ...services.plugin_service import PluginService

router = APIRouter(prefix="/ontology", tags=["ontology"])


async def require_ols4_plugin(db: AsyncSession = Depends(get_db)) -> None:
    """Respect the verified deployment manifest and its persisted enable override."""
    registry = get_plugin_registry()
    state = await PluginService.status(db, registry, "ols4")
    registry.require_available("ols4", enabled_override=state.enabled)


@router.get("/search", response_model=OntologySearchResponse)
async def search(
    query: str = Query(min_length=1, max_length=200),
    ontology: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
    _: None = Depends(require_ols4_plugin),
) -> OntologySearchResponse:
    """Search public ontology terms without persisting or executing anything."""
    return await search_ontology(query=query, ontology=ontology, limit=limit)


@router.get("/term", response_model=OntologyTermResponse)
async def term(
    ontology: str = Query(min_length=1, max_length=64),
    iri: str = Query(min_length=1, max_length=2_048),
    _: None = Depends(require_ols4_plugin),
) -> OntologyTermResponse:
    """Read one bounded ontology term by IRI."""
    return await get_term(ontology=ontology, iri=iri)


@router.get("/graph", response_model=OntologyRelationshipGraphResponse)
async def relationship_graph(
    ontology: str = Query(min_length=1, max_length=64),
    iri: str = Query(min_length=1, max_length=2_048),
    max_nodes: int = Query(default=24, ge=1, le=50),
    max_edges: int = Query(default=32, ge=1, le=100),
    _: None = Depends(require_ols4_plugin),
) -> OntologyRelationshipGraphResponse:
    """Read a one-hop OLS4 relationship graph with strict node and edge caps."""
    return await get_relationship_graph(
        ontology=ontology,
        iri=iri,
        max_nodes=max_nodes,
        max_edges=max_edges,
    )


__all__ = ["router"]
