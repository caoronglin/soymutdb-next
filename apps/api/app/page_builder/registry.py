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
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class ResourceCardItem(_Strict):
    """A safe, editor-configurable resource card (text, image, and link)."""

    title: str = Field(..., min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1_000)
    image_url: str | None = Field(default=None, max_length=2_048)
    href: str | None = Field(default=None, max_length=2_048)

    @field_validator("title", "description")
    @classmethod
    def reject_dangerous_text(cls, value: str | None, info) -> str | None:
        if value is not None:
            _reject_dangerous(value, field_name=info.field_name)
        return value

    @field_validator("image_url", "href")
    @classmethod
    def validate_safe_url(cls, value: str | None, info) -> str | None:
        if value is None:
            return value
        _reject_dangerous(value, field_name=info.field_name)
        return _validate_url(value, field_name=info.field_name)


class ResourceCardsConfig(_Strict):
    """Bounded resource-directory cards editable by administrators."""

    heading: str | None = Field(default=None, max_length=160)
    cards: list[ResourceCardItem] = Field(default_factory=list, max_length=24)


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
    #: The launcher always opens a DIAMOND blastp search; there is no other
    #: program to preselect, so the field is retained purely for stored configs.
    program: Literal["blastn", "blastp", "blastx", "tblastn", "tblastx"] = "blastp"
    assembly: str | None = Field(default=None, max_length=128)


class OntologyRelationshipGraphConfig(_Strict):
    """A bounded, first-party OLS4 graph; no caller-controlled endpoint exists."""

    ontology: str = Field(pattern=r"^[a-z0-9]+$", min_length=1, max_length=64)
    iri: str = Field(min_length=1, max_length=2_048)
    max_nodes: int = Field(default=24, ge=1, le=50)
    max_edges: int = Field(default=32, ge=1, le=100)


class PageDataSourceConfig(_Strict):
    """A bounded reference to server-owned data; never an executable adapter."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    kind: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    dataset_version_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("config")
    @classmethod
    def validate_bounded_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 32:
            raise ValueError("data-source config has too many fields")

        forbidden_key = re.compile(r"(?i)(css|html|script|style|template|url|uri|endpoint|host)")

        def walk(candidate: Any, *, depth: int = 0) -> None:
            if depth > 4:
                raise ValueError("data-source config is nested too deeply")
            if candidate is None or isinstance(candidate, (bool, int, float)):
                return
            if isinstance(candidate, str):
                if len(candidate) > 1_000:
                    raise ValueError("data-source config string is too long")
                _reject_dangerous(candidate, field_name="data_sources.config")
                if re.match(r"(?i)^[a-z][a-z0-9+.-]*:", candidate.strip()):
                    raise ValueError("data-source config cannot contain a URL or URI")
                return
            if isinstance(candidate, list):
                if len(candidate) > 100:
                    raise ValueError("data-source config list is too large")
                for item in candidate:
                    walk(item, depth=depth + 1)
                return
            if isinstance(candidate, dict):
                if len(candidate) > 32:
                    raise ValueError("data-source config object has too many fields")
                for key, item in candidate.items():
                    if not isinstance(key, str) or forbidden_key.search(key):
                        raise ValueError("data-source config contains a forbidden field")
                    walk(item, depth=depth + 1)
                return
            raise ValueError("data-source config must contain JSON values only")

        walk(value)
        return value


class LayoutPlacement(_Strict):
    component: str = Field(
        pattern=r"^root(?:\.children\[[0-9]+\])*$",
        max_length=256,
    )
    x: int = Field(ge=0, le=23)
    y: int = Field(ge=0, le=10_000)
    width: int = Field(ge=1, le=24)
    height: int = Field(ge=1, le=10_000)


class ResponsiveLayoutConfig(_Strict):
    columns: int | None = Field(default=None, ge=1, le=24)
    gap: int | None = Field(default=None, ge=0, le=64)
    placements: list[LayoutPlacement] | None = Field(default=None, max_length=256)


class PageLayouts(_Strict):
    desktop: ResponsiveLayoutConfig = Field(default_factory=ResponsiveLayoutConfig)
    tablet: ResponsiveLayoutConfig = Field(default_factory=ResponsiveLayoutConfig)
    mobile: ResponsiveLayoutConfig = Field(default_factory=ResponsiveLayoutConfig)


_PAGE_THEMES = frozenset(
    {
        "scientific-light",
        "scientific-dark",
        "high-contrast",
        "compact-data",
        "print",
    }
)


_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "navigation": NavigationConfig,
    "news_list": NewsListConfig,
    "media_carousel": MediaCarouselConfig,
    "resource_cards": ResourceCardsConfig,
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
    "ontology_relationship_graph": OntologyRelationshipGraphConfig,
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
    ComponentDefinition("resource_cards", "Resource Cards", ResourceCardsConfig),
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
    ComponentDefinition(
        "ontology_relationship_graph",
        "Ontology Relationship Graph",
        OntologyRelationshipGraphConfig,
    ),
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
    # ``/`` is the portal homepage; it is the only route with no path segment
    # and is deliberately editable so Admin can own the homepage layout.
    if route != "/" and not ROUTE_PATTERN.match(route):
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
    allowed_fields = {
        "schema_version",
        "title_key",
        "root",
        "data_sources",
        "theme_id",
        "layouts",
    }
    unknown_fields = sorted(set(definition) - allowed_fields)
    if unknown_fields:
        raise ValidationError(
            "Definition contains unknown fields",
            details={"fields": unknown_fields},
        )
    if "root" not in definition:
        raise ValidationError("Definition must contain a 'root' component")

    schema_version = definition.get("schema_version")
    if schema_version not in (None, 1, 2):
        raise ValidationError(
            "Unsupported PageDefinition schema version",
            details={"schema_version": schema_version},
        )

    root = definition["root"]
    if not isinstance(root, dict):
        raise ValidationError("Definition 'root' must be an object")
    cleaned_root = _validate_node(root, path="root")

    try:
        data_sources = [
            PageDataSourceConfig.model_validate(item).model_dump(
                mode="python", exclude_none=True
            )
            for item in definition.get("data_sources", [])
        ]
        layouts = PageLayouts.model_validate(definition.get("layouts", {})).model_dump(
            mode="python", exclude_none=True
        )
    except Exception as exc:  # pydantic ValidationError
        raise ValidationError(
            "Invalid PageDefinition v2 metadata",
            details={"reason": str(exc)},
        ) from exc

    if len(data_sources) > 32:
        raise ValidationError("PageDefinition cannot reference more than 32 data sources")
    data_source_ids = [source["id"] for source in data_sources]
    if len(set(data_source_ids)) != len(data_source_ids):
        raise ValidationError("PageDefinition data-source IDs must be unique")

    theme_id = definition.get("theme_id", "scientific-light")
    if theme_id not in _PAGE_THEMES:
        raise ValidationError(
            "Unknown PageDefinition theme",
            details={"theme_id": theme_id},
        )

    cleaned: dict[str, Any] = {
        "schema_version": 2,
        "root": cleaned_root,
        "data_sources": data_sources,
        "theme_id": theme_id,
        "layouts": layouts,
    }
    title_key = definition.get("title_key")
    if title_key is not None:
        if not isinstance(title_key, str) or not title_key:
            raise ValidationError("title_key must be a non-empty string")
        cleaned["title_key"] = title_key
    return cleaned


_LAUNCHER_PLUGIN_REQUIREMENTS = {
    "jbrowse_launcher": ("jbrowse", True, True),
    "blast_launcher": ("blast", True, True),
    # The graph is rendered in-process, so it needs no external URL or assembly.
    "ontology_relationship_graph": ("ols4", False, False),
}


def _state_value(state: Any, name: str) -> Any:
    """Read a plugin-state field from a dataclass or a dict."""
    if isinstance(state, dict):
        return state.get(name)
    return getattr(state, name, None)


def _is_https_origin(value: Any) -> bool:
    """Only an HTTPS origin with no credentials/query/fragment is accepted."""
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _validate_plugin_launcher_node(
    node: dict[str, Any],
    *,
    path: str,
    plugin_states: dict[str, Any],
) -> None:
    node_type = node.get("type")
    requirements = _LAUNCHER_PLUGIN_REQUIREMENTS.get(str(node_type))
    if requirements is None:
        return
    plugin_key, requires_public_url, requires_assembly = requirements

    state = plugin_states.get(plugin_key)
    if state is None:
        raise ValidationError(
            f"Plugin launcher at {path} requires installed plugin {plugin_key!r}",
            details={"plugin": plugin_key, "path": path},
        )

    for field_name, display in (
        ("installed", "installed"),
        ("enabled", "enabled"),
        ("configured", "configured"),
        ("healthy", "healthy"),
    ):
        if not bool(_state_value(state, field_name)):
            raise ValidationError(
                f"Plugin {plugin_key!r} is not {display} for launcher at {path}",
                details={"plugin": plugin_key, "path": path, "reason": display},
            )

    if requires_public_url:
        public_url = _state_value(state, "public_url")
        if not _is_https_origin(public_url):
            raise ValidationError(
                f"Plugin {plugin_key!r} has no HTTPS public URL for launcher at {path}",
                details={"plugin": plugin_key, "path": path},
            )

    if requires_assembly:
        assemblies = _state_value(state, "assemblies")
        assembly = (node.get("props") or {}).get("assembly")
        if not isinstance(assembly, str) or not assembly:
            raise ValidationError(
                f"Plugin launcher at {path} must declare an assembly",
                details={"plugin": plugin_key, "path": path},
            )
        supported = list(assemblies or [])
        if assembly not in supported:
            raise ValidationError(
                f"Assembly {assembly!r} is not supported by plugin {plugin_key!r}",
                details={
                    "plugin": plugin_key,
                    "path": path,
                    "assembly": assembly,
                    "supported_assemblies": supported,
                },
            )


def validate_plugin_launchers(
    definition: dict[str, Any],
    plugin_states: dict[str, Any],
) -> dict[str, Any]:
    """Fail closed when a launcher references an unavailable plugin/assembly."""
    if not isinstance(definition, dict) or not isinstance(plugin_states, dict):
        raise ValidationError("Plugin launcher validation requires a definition and states")

    def walk(node: dict[str, Any], path: str) -> None:
        _validate_plugin_launcher_node(node, path=path, plugin_states=plugin_states)
        for index, child in enumerate(node.get("children") or []):
            if isinstance(child, dict):
                walk(child, f"{path}.children[{index}]")

    root = definition.get("root")
    if isinstance(root, dict):
        walk(root, "root")
    return definition


__all__ = [
    "COMPONENT_REGISTRY",
    "ROUTE_PATTERN",
    "RESERVED_ROUTES",
    "ComponentDefinition",
    "validate_definition",
    "validate_plugin_launchers",
    "validate_route",
]
