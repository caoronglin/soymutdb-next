"""Jinja2 rendering engine with bleach HTML sanitization for widgets."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import bleach
from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bleach sanitisation configuration
# ---------------------------------------------------------------------------

ALLOWED_TAGS: list[str] = [
    "div", "span", "p", "a", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
    "img", "br", "strong", "em", "code", "pre",
    "section", "article", "header", "footer", "small",
    "button", "input", "form", "label", "select", "option",
    "svg", "path", "g", "circle", "rect",
]

ALLOWED_ATTRIBUTES: dict[str, list[str]] = {
    "*": ["class", "id", "title"],
    "a": ["href", "title"],
    "img": ["src", "alt", "title", "width", "height"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
    "button": ["type", "name", "value", "disabled"],
    "input": ["type", "name", "value", "placeholder", "disabled", "checked"],
    "select": ["name", "disabled", "multiple"],
    "option": ["value", "selected", "disabled"],
    "form": ["action", "method"],
    "label": ["for"],
    "svg": ["viewBox", "width", "height", "fill"],
    "path": ["d", "fill"],
    "circle": ["cx", "cy", "r", "fill"],
    "rect": ["x", "y", "width", "height", "fill"],
    "g": ["fill"],
}


def _data_attr_filter(tag: str, name: str, value: str) -> bool:
    """Allow data-* wildcard attributes on any element."""
    if name.startswith("data-"):
        return True
    allowed = ALLOWED_ATTRIBUTES.get(tag, [])
    if name in allowed:
        return True
    if name in ALLOWED_ATTRIBUTES.get("*", []):
        return True
    return False


def sanitize_html(html: str) -> str:
    """Sanitize rendered widget HTML through bleach.

    Allows the configured set of tags and attributes, stripping everything
    else while preserving text content.
    """
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=_data_attr_filter,
        strip=True,
    )


# ---------------------------------------------------------------------------
# Jinja2 environment
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).parent / "templates"


@lru_cache(maxsize=1)
def _get_jinja_env() -> Environment:
    """Return a cached Jinja2 environment configured for widget templates."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env


def render_error_fragment(widget_name: str, error_msg: str) -> str:
    """Return a safe HTML error fragment for a widget that failed to render."""
    safe_name = bleach.clean(widget_name)
    safe_msg = bleach.clean(error_msg)
    return (
        f'<div class="widget widget-error" data-widget="{safe_name}">'
        f'<div class="widget-error-inner">'
        f'<small>Widget error</small>'
        f'<p><strong>{safe_name}</strong>: {safe_msg}</p>'
        f'</div>'
        f'</div>'
    )


class WidgetEngine:
    """Render widget templates with sanitization.

    The engine lazily creates a Jinja2 environment pointed at the bundled
    ``templates/`` directory.  Every rendered fragment is passed through
    :func:`sanitize_html` before being returned.
    """

    def __init__(self) -> None:
        self._env: Environment | None = None

    @property
    def env(self) -> Environment:
        if self._env is None:
            self._env = _get_jinja_env()
        return self._env

    def render(
        self,
        template_path: str,
        context: dict[str, Any] | None = None,
        *,
        widget_name: str = "unknown",
    ) -> str:
        """Render *template_path* with *context* and return sanitized HTML.

        On any rendering failure (missing template, undefined variable, etc.)
        a safe error fragment is returned instead of raising — widgets must
        never crash the page.
        """
        ctx = context or {}
        try:
            template = self.env.get_template(template_path)
            html = template.render(**ctx)
        except TemplateNotFound:
            logger.warning("widget_template_not_found", template=template_path, widget=widget_name)
            return render_error_fragment(widget_name, f"Template not found: {template_path}")
        except Exception as exc:
            logger.warning(
                "widget_render_error",
                widget=widget_name,
                template=template_path,
                error=str(exc),
            )
            return render_error_fragment(widget_name, str(exc))

        return sanitize_html(html)

    def list_builtin_templates(self) -> list[str]:
        """List all built-in template names (without .html extension)."""
        if not _TEMPLATES_DIR.is_dir():
            return []
        return sorted(
            p.stem for p in _TEMPLATES_DIR.glob("*.html") if p.is_file()
        )


# Singleton instance for convenience
_engine: WidgetEngine | None = None


def get_engine() -> WidgetEngine:
    """Return the shared :class:`WidgetEngine` singleton."""
    global _engine
    if _engine is None:
        _engine = WidgetEngine()
    return _engine
