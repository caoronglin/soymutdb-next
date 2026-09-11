"""Route-level declarations for write operations with required audit trails."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class AuditPolicy:
    """Auditable write-route contract consumed by future A-19 architecture guards."""

    action: str
    roles: frozenset[str]


def declares_audit(
    action: str,
    *,
    roles: frozenset[str] | set[str] | tuple[str, ...],
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Attach immutable audit and authorization intent to a route handler.

    This is intentionally metadata-only: the route/service still records the
    audit event in its transaction. A future A-19 guard can inspect the marker
    without requiring broad route rewrites or runtime reflection.
    """
    if not action or not action.strip():
        raise ValueError("audit action must be non-empty")
    normalized_roles = frozenset(roles)
    if not normalized_roles:
        raise ValueError("audited routes must declare at least one role")

    def decorator(fn: Callable[P, T]) -> Callable[P, T]:
        setattr(fn, "__audit_policy__", AuditPolicy(action=action, roles=normalized_roles))
        return fn

    return decorator


def get_audit_policy(endpoint: object) -> AuditPolicy | None:
    """Return a handler audit declaration, if one was made."""
    policy = getattr(endpoint, "__audit_policy__", None)
    return policy if isinstance(policy, AuditPolicy) else None


__all__ = ["AuditPolicy", "declares_audit", "get_audit_policy"]
