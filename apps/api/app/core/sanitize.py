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
#:
#: The rewrite has to be *quote-aware*: bleach leaves a literal ``>`` inside an
#: attribute value untouched (``title="a>b"`` survives cleaning), so a plain
#: ``[^>]*>`` tag matcher ends the tag early and injects the new attribute
#: into the middle of an existing one.  ``_TAG_BODY`` therefore consumes a
#: quoted value as a unit and only treats an unquoted ``>`` as the tag end.
_TAG_BODY = r'(?:[^>"\']|"[^"]*"|\'[^\']*\')*'

_REL_OPEN_LINK_RE = re.compile(
    rf'<a\b(?={_TAG_BODY}\btarget\s*=\s*["\']_blank["\']){_TAG_BODY}>',
    re.IGNORECASE | re.DOTALL,
)

#: Attribute tokeniser used to locate ``rel`` inside a cleaned tag.  Each match
#: consumes the attribute *including* its quoted value, so the next search
#: position is always the start of a real attribute and never a substring of a
#: value (``title="a rel='b'"`` cannot produce a spurious ``rel`` hit).
_TAG_ATTR_RE = re.compile(
    r"""\s+(?P<name>[^\s=/>]+)(?:\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'))?"""
)

#: An author-supplied ``rel`` never wins over the two tokens this module owns:
#: ``rel="opener"`` re-enables ``window.opener`` on the opened page, which is
#: exactly the reverse-tabnabbing vector ``noopener`` closes.
_REL_OWNED_TOKENS: tuple[str, ...] = ("noopener", "noreferrer")
_REL_DROPPED_TOKENS: frozenset[str] = frozenset({*_REL_OWNED_TOKENS, "opener"})


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


def _force_safe_rel(match: re.Match) -> str:
    """Rewrite the ``rel`` of a matched ``<a target="_blank">`` tag.

    Any author-supplied ``rel`` is kept except for the tokens this module
    owns plus ``opener`` (which contradicts ``noopener``); ``noopener`` and
    ``noreferrer`` are then appended.  Rewriting an existing attribute rather
    than only adding a missing one is what keeps ``rel="opener"`` — the one
    value that actively re-enables the opener — from surviving.  When ``rel``
    is absent the pair is appended before the tag's own ``>``, which the
    quote-aware matcher has already proven to be the real tag end.
    """
    tag = match.group(0)
    rel_attr = next(
        (
            attr
            for attr in _TAG_ATTR_RE.finditer(tag)
            if attr.group("name").lower() == "rel"
        ),
        None,
    )
    if rel_attr is None:
        owned = " ".join(_REL_OWNED_TOKENS)
        return f'{tag[:-1]} rel="{owned}">'

    quoted = rel_attr.group("dq")
    group = "dq" if quoted is not None else "sq"
    carried = (quoted if quoted is not None else rel_attr.group("sq") or "").split()
    kept = [token for token in carried if token.lower() not in _REL_DROPPED_TOKENS]
    tokens = " ".join([*kept, *_REL_OWNED_TOKENS])
    return f"{tag[: rel_attr.start(group)]}{tokens}{tag[rel_attr.end(group):]}"


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
    return _REL_OPEN_LINK_RE.sub(_force_safe_rel, cleaned)


__all__ = ["ALLOWED_TAGS", "sanitize_rich_html"]
