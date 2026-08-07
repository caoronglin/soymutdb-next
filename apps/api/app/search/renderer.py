"""Jinja2 rendering + bleach sanitization for search HTML fragments."""

from __future__ import annotations

from pathlib import Path

import bleach
import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import ExternalSearchResponse

logger = structlog.get_logger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

_env: Environment | None = None


def _get_env() -> Environment:
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "j2", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _env


# Allowed HTML tags / attributes for rendered fragments.  Kept intentionally
# conservative: structural layout + safe inline semantics.  Forms/scripts/
# event handlers/iframes are all stripped.
ALLOWED_TAGS: list[str] = [
    "div", "span", "section", "ul", "ol", "li",
    "a", "p", "strong", "em", "b", "i", "small",
    "h3", "h4", "h5", "h6",
    "br", "hr",
    "abbr", "code", "pre",
    "svg", "path", "circle",
]

ALLOWED_ATTRS: dict[str, list[str]] = {
    "a": ["href", "title", "rel", "target", "class", "data-source", "data-id"],
    "div": ["class", "data-source", "data-status"],
    "span": ["class", "title"],
    "section": ["class", "data-source", "data-status"],
    "ul": ["class"],
    "ol": ["class"],
    "li": ["class"],
    "h3": ["class"],
    "h4": ["class"],
    "h5": ["class"],
    "p": ["class"],
    "small": ["class"],
    "abbr": ["title", "class"],
    "svg": ["class", "viewBox", "width", "height", "fill", "aria-hidden", "xmlns"],
    "path": ["d", "fill"],
    "circle": ["cx", "cy", "r", "fill"],
    "code": ["class"],
    "pre": ["class"],
}

ALLOWED_PROTOCOLS: list[str] = ["http", "https", "mailto"]


def _sanitize(html: str) -> str:
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )


def render_search_html(response: ExternalSearchResponse, cache_key: str | None = None) -> str:
    """Render the top-level search-results fragment and sanitize it.

    The rendered HTML is a *fragment* (no ``<html>``/``<body>``) so the
    frontend can drop it directly into a results container via ``innerHTML``.
    """
    env = _get_env()
    template = env.get_template("search_results.html.j2")
    rendered = template.render(resp=response, cache_key=cache_key)
    return _sanitize(rendered)


def render_source_error(message: str, source_label: str) -> str:
    """Render a minimal per-source error fragment (also sanitized)."""
    env = _get_env()
    template = env.get_template("source_error.html.j2")
    rendered = template.render(message=message, source_label=source_label)
    return _sanitize(rendered)
