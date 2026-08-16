"""Safe Admin Page Builder package.

Server-owned component registry, definition validation, and PageDefinition
service.  There is no admin-provided renderer or template path: every
component is resolved through :mod:`app.page_builder.registry`.
"""

from __future__ import annotations

from .registry import (
    COMPONENT_REGISTRY,
    ComponentDefinition,
    validate_definition,
)

__all__ = [
    "COMPONENT_REGISTRY",
    "ComponentDefinition",
    "validate_definition",
]
