"""Server-side rich-text sanitization (E2-1).

Single source of truth for the API's rich-text allowlist.  Applied at every
admin write boundary (news content, static page content, ``about.*`` content
keys) so untrusted HTML never reaches the database unsanitised.

Three-tier strategy (docs/design/static-content-richtext-2026-08.md §4.3):
server-side bleach (this module) + portal DOMPurify + SSG-side re-clean.

Contract:
- ``sanitize_rich_html(html: str) -> str`` — bleach allowlist cleaning.
- Tags: p/br/strong/em/u/s/h1-h6/ul/ol/li/a/img/table/thead/tbody/tr/th/td/
  pre/code/blockquote/hr.  ``span`` is intentionally NOT allowed (style-based
  formatting is out of scope; text colour is not supported).
- Attributes: href/src/alt/title/target/colspan/rowspan (plus ``rel`` on
  ``a`` so the ``target="_blank"`` enforcement can be expressed).
- URL protocols: http/https/data:image/ (relative URLs are allowed by bleach
  since they carry no scheme).  ``data:image/svg+xml`` is rejected — SVG is
  banned by the upload validation and is a known XSS vector.
- ``target="_blank"`` links always gain ``rel="noopener noreferrer"``
  (reverse-tabnabbing protection).
- script/style/iframe/object/event attributes are stripped.
"""

from __future__ import annotations

import re

import bleach

#: Allowed tags — TipTap rich-text subset.  ``span`` deliberately excluded.
ALLOWED_TAGS = [
    "p",
    "br",
    "strong",
    "em",
    "u",
    "s",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "a",
    "img",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "pre",
    "code",
    "blockquote",
    "hr",
]

#: Per-tag attribute allowlist.  ``*`` applies to every tag; tag-specific
#: entries add attributes for that tag only.
_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "*": {"title"},
    "a": {"href", "title", "target", "rel"},
    "img": {"src", "alt", "title"},
    "th": {"colspan", "rowspan", "title"},
    "td": {"colspan", "rowspan", "title"},
}

#: URL protocols allowed on href/src.  ``data`` is required by bleach for any
#: ``data:`` URI; the image-only restriction is enforced by the attribute
#: filter below (bleach 6.x does not apply its own content-type check).
_ALLOWED_PROTOCOLS = ["http", "https", "data"]

#: ``target="_blank"`` must always carry ``rel="noopener noreferrer"``.
#: bleach cannot add attributes, so this is enforced with a post-clean
#: rewrite of the (already well-formed) bleach output.
_REL_NOOPENER_RE = re.compile(
    r'<a\b(?=[^>]*\btarget=["\']_blank["\'])(?![^>]*\brel=)[^>]*>',
    re.IGNORECASE,
)


def _rich_attr_filter(tag: str, name: str, value: str) -> bool:
    """bleach attribute callable: allowlist + ``data:image/`` restriction.

    Returns ``True`` to keep the attribute, ``False`` to drop it.  bleach
    additionally applies its own protocol check on URI attributes, so a
    ``javascript:`` URL is stripped even if this filter returns ``True``.
    """
    allowed = set(_ALLOWED_ATTRIBUTES.get(tag, set())) | _ALLOWED_ATTRIBUTES["*"]
    if name not in allowed:
        return False
    if name in ("href", "src"):
        lowered = value.strip().lower()
        if lowered.startswith("data:"):
            # Only inline raster images are permitted; SVG data URIs are a
            # known XSS vector and are banned alongside the upload rule.
            if not lowered.startswith("data:image/"):
                return False
            if lowered.startswith("data:image/svg+xml"):
                return False
    return True


def _add_rel_noopener(match: re.Match) -> str:
    """Insert ``rel="noopener noreferrer"`` into a matched ``<a ...>`` tag."""
    tag = match.group(0)
    return tag[:-1] + ' rel="noopener noreferrer">'


def sanitize_rich_html(html: str) -> str:
    """Sanitize *html* against the rich-text allowlist.

    Strips disallowed tags/attributes/event handlers, restricts URL protocols
    to http/https/data:image/ (relative URLs allowed), and forces
    ``rel="noopener noreferrer"`` on any ``target="_blank"`` link.  Returns
    the cleaned HTML string (empty input is returned unchanged).
    """
    if not html:
        return html
    cleaned = bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=_rich_attr_filter,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )
    return _REL_NOOPENER_RE.sub(_add_rel_noopener, cleaned)


__all__ = ["ALLOWED_TAGS", "sanitize_rich_html"]
