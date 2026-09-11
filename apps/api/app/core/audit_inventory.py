"""Inventory declared audit policies without enforcing repository-wide coverage."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from fastapi.routing import APIRoute

from .audit_policy import get_audit_policy

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True, slots=True)
class AuditRouteInventoryItem:
    """One mutating route and its optional declared audit policy."""

    path: str
    methods: tuple[str, ...]
    action: str | None
    roles: tuple[str, ...]

    @property
    def declared(self) -> bool:
        return self.action is not None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"declared": self.declared}


def inventory_write_routes(routes: list[Any]) -> list[AuditRouteInventoryItem]:
    """Return a deterministic, non-blocking inventory of mutating API routes.

    Only FastAPI APIRoute instances with POST/PUT/PATCH/DELETE are included.
    Missing declarations are represented in the result rather than raising: this
    supports staged A-12 migration and gives A-19 a stable future input.
    """
    inventory: list[AuditRouteInventoryItem] = []
    for route in routes:
        if not isinstance(route, APIRoute):
            continue
        methods = tuple(sorted(set(route.methods or ()) & _WRITE_METHODS))
        if not methods:
            continue
        policy = get_audit_policy(route.endpoint)
        inventory.append(
            AuditRouteInventoryItem(
                path=route.path,
                methods=methods,
                action=policy.action if policy else None,
                roles=tuple(sorted(policy.roles)) if policy else (),
            )
        )
    return sorted(inventory, key=lambda item: (item.path, item.methods))


__all__ = ["AuditRouteInventoryItem", "inventory_write_routes"]
