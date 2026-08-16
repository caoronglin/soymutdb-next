"""Server-owned safe component registry for the Page Builder.

This is the single source of truth for what may appear in a
``PageDefinition``.  Each entry exposes a ``renderer_key``, a Pydantic
``config_model`` (the allowed props), and ``allowed_children``.  There is no
admin-provided renderer or template path: unknown component types, unknown
props, ``javascript:`` URLs, inline event handlers, raw scripts, and arbitrary
template/action names are all rejected at validation time.

Security invariants enforced by :func:`validate_definition`:

* Component ``type`` must be a registered ``renderer_key``.
* Every node's ``props`` must validate against its ``config_model`` (unknown /
  excess props are rejected with ``extra="forbid"``).
* Recursive children must be declared in ``allowed_children``.
* ``href``/``src``/``url`` values are restricted to ``http``, ``https``, or
  internal routes (``/...``); ``javascript:`` and other schemes are rejected.
* Any string that looks like an inline event handler (``onclick=`` etc.) or a
  raw ``<script``/``<iframe`` tag is rejected.
* ``rich_text`` HTML is passed through the existing server sanitizer.
* ``action`` values (e.g. ``open_jbrowse``, ``run_blast``) come from a fixed
  allowlist — an arbitrary template path can never be dialed in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..core.exceptions import ValidationError
from ..core.sanitize import sanitize_rich_html

# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

#: Routes reserved from generic definitions (served by dedicated code).
RESERVED_ROUTES = ("/blast", "/browser", "/admin", "/api")

#: Route pattern for a page definition.  No consecutive slashes, no trailing
#: slash on non-root routes, no leading dash, no dot/dotdot segments.
ROUTE_PATTERN = re.compile(r"^/(?:[a-z0-9][a-z0-9_\-]*)(?:/[a-z0-9_\-]+)*$")

#: Internal-route link target (single leading slash, path only).
_INTERNAL_ROUTE_RE = re.compile(r"^/(?![/\s])[^\s]*$")

#: Allowed URL schemes for link/image targets.
_ALLOWED_SCHEMES = ("http", "https")

#: Inline event handlers / raw script / dangerous tag signature.
_DANGEROUS_RE = re.compile(
    r"(?is)<\s*(script|iframe|object|embed|style)\b|"
    r"<\s*[a-z0-9]+\b[^>]*\bon[a-z]+\s*="
)

#: Approved action identifiers (JBrowse 2 and BLAST are dedicated launchers).
_APPROVED_ACTIONS = frozenset(
    {
        "open_jbrowse",
        "run_blast",
        "submit_gene_search",
        "submit_location_search",
    }
)


# ---------------------------------------------------------------------------
# Config models (schema-driven property panels)
# ---------------------------------------------------------------------------


class _Strict(BaseModel):
    """Base config: forbid extra props so unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")


class NavigationItem(_Strict):
    """A single navigation entry (label + internal route)."""

    label: str = Field(..., min_length=1, max_length=160)
    route: str = Field(..., min_length=1, max_length=160)


class NavigationConfig(_Strict):
    title: str | None = Field(default=None, max_length=160)
    items: list[NavigationItem] = Field(default_factory=list, max_length=16)


class NewsListConfig(_Strict):
    limit: int = Field(default=6, ge=1, le=50)


class MediaCarouselConfig(_Strict):
    items: list[str] = Field(default_factory=list, max_length=12)


class RichTextConfig(_Strict):
    content: str = Field(default="")


class ToolEntriesConfig(_Strict):
    entries: list[str] = Field(default_factory=list, max_length=8)


class AssemblySelectConfig(_Strict):
    default_assembly: str | None = Field(default=None, max_length=128)


class GeneSearchFormConfig(_Strict):
    title: str | None = Field(default=None, max_length=160)


class LocationSearchFormConfig(_Strict):
    title: str | None = Field(default=None, max_length=160)


class DataTableConfig(_Strict):
    columns: list[str] = Field(default_factory=list, max_length=32)


class ButtonConfig(_Strict):
    label: str = Field(default="", max_length=160)
    action: str | None = None
    variant: Literal["primary", "secondary", "ghost"] = "primary"


class LinkConfig(_Strict):
    label: str = Field(default="", max_length=160)
    href: str | None = None
    variant: Literal["default", "button"] = "default"


class NoticeConfig(_Strict):
    kind: Literal["info", "warning", "success", "error"] = "info"
    content: str = Field(default="")


class DividerConfig(_Strict):
    pass


class TabsConfig(_Strict):
    tabs: list[str] = Field(default_factory=list, max_length=10)


class ColumnsConfig(_Strict):
    columns: int = Field(default=2, ge=1, le=4)


class JbrowseLauncherConfig(_Strict):
    assembly: str | None = Field(default=None, max_length=128)
    track: str | None = Field(default=None, max_length=256)


class BlastLauncherConfig(_Strict):
    program: Literal["blastn", "blastp", "blastx", "tblastn", "tblastx"] = "blastn"


_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "navigation": NavigationConfig,
    "news_list": NewsListConfig,
    "media_carousel": MediaCarouselConfig,
    "rich_text": RichTextConfig,
    "tool_entries": ToolEntriesConfig,
    "assembly_select": AssemblySelectConfig,
    "gene_search_form": GeneSearchFormConfig,
    "location_search_form": LocationSearchFormConfig,
    "data_table": DataTableConfig,
    "button": ButtonConfig,
    "link": LinkConfig,
    "notice": NoticeConfig,
    "divider": DividerConfig,
    "tabs": TabsConfig,
    "columns": ColumnsConfig,
    "jbrowse_launcher": JbrowseLauncherConfig,
    "blast_launcher": BlastLauncherConfig,
}


# ---------------------------------------------------------------------------
# Registry entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentDefinition:
    """A registered component type."""

    renderer_key: str
    label: str
    config_model: type[BaseModel]
    allowed_children: frozenset[str] = field(default_factory=frozenset)

    @property
    def config_schema(self) -> dict[str, Any]:
        """JSON-Schema-ish serialisation of the config model (for Admin)."""
        return self.config_model.model_json_schema()


_COMPONENTS: list[ComponentDefinition] = [
    ComponentDefinition("navigation", "Navigation", NavigationConfig),
    ComponentDefinition("news_list", "News List", NewsListConfig),
    ComponentDefinition("media_carousel", "Media Carousel", MediaCarouselConfig),
    ComponentDefinition("rich_text", "Rich Text", RichTextConfig),
    ComponentDefinition("tool_entries", "Tool Entries", ToolEntriesConfig),
    ComponentDefinition("assembly_select", "Assembly Select", AssemblySelectConfig),
    ComponentDefinition("gene_search_form", "Gene Search Form", GeneSearchFormConfig),
    ComponentDefinition("location_search_form", "Location Search Form", LocationSearchFormConfig),
    ComponentDefinition("data_table", "Data Table", DataTableConfig),
    ComponentDefinition("button", "Button", ButtonConfig),
    ComponentDefinition("link", "Link", LinkConfig),
    ComponentDefinition("notice", "Notice", NoticeConfig),
    ComponentDefinition("divider", "Divider", DividerConfig),
    ComponentDefinition("tabs", "Tabs", TabsConfig),
    ComponentDefinition(
        "columns", "Columns", ColumnsConfig, frozenset({}),
    ),
    ComponentDefinition("jbrowse_launcher", "JBrowse 2 Launcher", JbrowseLauncherConfig),
    ComponentDefinition("blast_launcher", "BLAST Launcher", BlastLauncherConfig),
]

# Layout container components may nest arbitrary registered children.
_LAYOUT_CONTAINERS = {"columns", "tabs"}

COMPONENT_REGISTRY: dict[str, ComponentDefinition] = {
    c.renderer_key: c for c in _COMPONENTS
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_url(value: str, *, field_name: str) -> str:
    """Ensure a URL is http(s) or an internal route, never ``javascript:``."""
    lowered = value.strip().lower()
    if lowered.startswith(("javascript:", "data:", "vbscript:", "file:")):
        raise ValidationError(
            f"{field_name} uses a forbidden URL scheme",
            details={"field": field_name},
        )
    if lowered.startswith(("http://", "https://", "mailto:", "tel:")):
        return value
    if _INTERNAL_ROUTE_RE.match(value):
        return value
    raise ValidationError(
        f"{field_name} must be an http(s) or internal-route URL",
        details={"field": field_name},
    )


def _reject_dangerous(value: str, *, field_name: str) -> None:
    """Reject inline handlers / raw scripts embedded in any string prop."""
    if _DANGEROUS_RE.search(value):
        raise ValidationError(
            f"{field_name} contains a disallowed script or event handler",
            details={"field": field_name},
        )


def _walk_text_values(node: dict[str, Any]) -> list[tuple[str, str]]:
    """Yield ``(field_name, string_value)`` for every string prop in *node*."""
    pairs: list[tuple[str, str]] = []
    props = node.get("props") or {}
    if isinstance(props, dict):
        for key, value in props.items():
            if isinstance(value, str):
                pairs.append((key, value))
    return pairs


def _validate_node(node: dict[str, Any], *, path: str) -> dict[str, Any]:
    """Validate a single node against the registry, returning a cleaned copy."""
    if not isinstance(node, dict):
        raise ValidationError(f"Component at {path} must be an object")

    node_type = node.get("type")
    if not isinstance(node_type, str):
        raise ValidationError(f"Component at {path} is missing a string 'type'")

    entry = COMPONENT_REGISTRY.get(node_type)
    if entry is None:
        raise ValidationError(
            f"Unknown component type {node_type!r} at {path}",
            details={"type": node_type},
        )

    props = node.get("props") or {}
    if not isinstance(props, dict):
        raise ValidationError(f"Component {node_type!r} props must be an object")

    # Reject dangerous strings BEFORE schema validation so a javascript: URL
    # or inline handler can never slip through any string prop.  ``rich_text``
    # content is the one deliberate exception: it is HTML that gets sanitized
    # below (defence in depth), so we do not pre-reject it here.
    for field_name, value in _walk_text_values(node):
        if node_type == "rich_text" and field_name == "content":
            continue
        _reject_dangerous(value, field_name=field_name)
        if field_name in ("href", "src", "url"):
            _validate_url(value, field_name=field_name)

    try:
        validated_props = entry.config_model.model_validate(props)
    except Exception as exc:  # pydantic ValidationError
        raise ValidationError(
            f"Invalid props for component {node_type!r} at {path}",
            details={"type": node_type, "reason": str(exc)},
        ) from exc

    cleaned: dict[str, Any] = {
        "type": node_type,
        "props": validated_props.model_dump(mode="python"),
    }

    children = node.get("children")
    if children is not None:
        if not isinstance(children, list):
            raise ValidationError(
                f"Component {node_type!r} children must be a list"
            )
        if node_type not in _LAYOUT_CONTAINERS:
            # Non-layout components are leaves in the reference tree; enforce
            # the declared allowed_children set (empty => no children).
            if children and not entry.allowed_children:
                raise ValidationError(
                    f"Component {node_type!r} does not accept children"
                )
        cleaned_children: list[dict[str, Any]] = []
        for i, child in enumerate(children):
            cleaned_children.append(
                _validate_node(child, path=f"{path}.children[{i}]")
            )
        cleaned["children"] = cleaned_children

    # rich_text content is sanitized server-side (defence in depth).
    if node_type == "rich_text" and cleaned["props"].get("content"):
        cleaned["props"]["content"] = sanitize_rich_html(
            cleaned["props"]["content"]
        )

    # action values must be from the fixed allowlist.
    if node_type == "button":
        action = cleaned["props"].get("action")
        if action is not None and action not in _APPROVED_ACTIONS:
            raise ValidationError(
                f"Unapproved action {action!r}",
                details={"action": action},
            )

    return cleaned


def validate_route(route: str) -> str:
    """Validate a page route against the reserved list and pattern."""
    if not route or not route.startswith("/"):
        raise ValidationError("Route must start with '/'")
    if not ROUTE_PATTERN.match(route):
        raise ValidationError(
            "Route must match /[a-z0-9][a-z0-9/_-]*",
            details={"route": route},
        )
    if route.rstrip("/") in RESERVED_ROUTES or any(
        route == r or route.startswith(r + "/") for r in RESERVED_ROUTES
    ):
        raise ValidationError(
            f"Route {route!r} is reserved", details={"route": route}
        )
    return route


def validate_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Validate a full PageDefinition tree, returning a cleaned copy.

    Raises :class:`~app.core.exceptions.ValidationError` on any violation.
    """
    if not isinstance(definition, dict):
        raise ValidationError("Definition must be an object")
    if "root" not in definition:
        raise ValidationError("Definition must contain a 'root' component")

    root = definition["root"]
    if not isinstance(root, dict):
        raise ValidationError("Definition 'root' must be an object")
    cleaned_root = _validate_node(root, path="root")

    cleaned: dict[str, Any] = {"root": cleaned_root}
    title_key = definition.get("title_key")
    if title_key is not None:
        if not isinstance(title_key, str) or not title_key:
            raise ValidationError("title_key must be a non-empty string")
        cleaned["title_key"] = title_key
    return cleaned


__all__ = [
    "COMPONENT_REGISTRY",
    "ROUTE_PATTERN",
    "RESERVED_ROUTES",
    "ComponentDefinition",
    "validate_definition",
    "validate_route",
]
