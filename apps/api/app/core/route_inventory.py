"""Deterministic inventory helpers for explicitly scoped API route guards."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from fastapi.routing import APIRoute, APIRouter


@dataclass(frozen=True, slots=True)
class PaginatedRouteInventoryItem:
    """The pagination-relevant public shape of one declared API route."""

    path: str
    methods: tuple[str, ...]
    query_parameters: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iter_api_routes(routes: Iterable[Any], prefix: str = "") -> Iterable[tuple[APIRoute, str]]:
    """Yield APIRoute objects through FastAPI's nested router representation."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route, prefix
            continue
        nested_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        nested_prefix = getattr(include_context, "prefix", "") if include_context else ""
        if isinstance(nested_router, APIRouter):
            yield from _iter_api_routes(nested_router.routes, prefix + nested_prefix)


def inventory_paginated_routes(routes: Iterable[Any]) -> list[PaginatedRouteInventoryItem]:
    """Return only routes that explicitly expose pagination parameters.

    This deliberately does not infer which legacy collection endpoints ought to
    paginate. A reviewed guard chooses a finite baseline from this inventory.
    """
    items: list[PaginatedRouteInventoryItem] = []
    for route, prefix in _iter_api_routes(routes):
        parameters = tuple(
            sorted(
                parameter.name
                for parameter in route.dependant.query_params
                if parameter.name in {"page", "page_size", "cursor", "limit", "offset"}
            )
        )
        if parameters:
            items.append(
                PaginatedRouteInventoryItem(
                    path=prefix + route.path,
                    methods=tuple(sorted(route.methods or ())),
                    query_parameters=parameters,
                )
            )
    return sorted(items, key=lambda item: (item.path, item.methods))


__all__ = ["PaginatedRouteInventoryItem", "inventory_paginated_routes"]
