"""First-party analytics sanitisation: route templates and referrer categories.

Pure functions only — no I/O, no database, no network, no settings reads and no
schema knowledge. Nothing here is wired to an endpoint yet.

Privacy contract
----------------
:func:`normalize_analytics_page` reduces a requested page (a path or an absolute
HTTP(S) URL) to **one member of a fixed set of canonical route templates** or to
``/other``. The output is always a constant taken from this module: no user
input, query string, fragment, host, credential or identifier is ever echoed
back, so a record derived from it cannot disclose a search term, a full URL or
an internal identifier. Identifier-shaped path segments are *not* validated
against any table: ``/mutants/42`` and ``/mutants/MUT-000123`` both collapse to
``/mutants/:publicId``, and a record is never checked for existence.

A query string or fragment is stripped from an absolute URL **and** from a
root-relative path by the same rule, so ``/search?q=secret``,
``/mutants/42#secret`` and ``https://host/mutants/42?q=secret`` all reduce to the
same two templates ``/search`` and ``/mutants/:publicId``.

Every canonical template — and ``/other`` itself — is a *fixed point* of the
function: normalising an already-normalised value returns it unchanged, so a
stored page or an aggregate read back from storage cannot drift to ``/other`` on
a second pass. The four dynamic templates are therefore accepted on the way back
in as those four exact literals, matched against the closed set below. That is
deliberately *not* a widening of the identifier position: a caller-chosen
parameter name such as ``/fake/:callerParam`` still reduces to ``/other``.

:func:`classify_referrer` reduces a ``Referer`` header to one of four fixed
categories. That header is supplied by the client, so the category is a hint
about a *self-reported header* — never evidence of a true traffic source — and
the raw origin, host and any userinfo are dropped rather than returned. Like
:func:`normalize_analytics_page` it is a fixed point on its own output, so a
stored category is not re-classified when it is read back;
:func:`referrer_column_value` is the only adapter that adds the storage rule
for an absent hint.

Route-table mirror
------------------
``_STATIC_PAGE_TEMPLATES`` / ``_DYNAMIC_PAGE_TEMPLATES`` mirror the ``path``
literals of ``PORTAL_ROUTES`` in ``apps/web/src/router/routes.ts``. This module
never reads that TypeScript file at runtime; the mirror is checked by
``apps/api/tests/test_analytics_sanitization.py``, which fails when the two
drift apart rather than skipping.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# --------------------------------------------------------------------------- #
# Canonical page templates (mirror of apps/web/src/router/routes.ts)
# --------------------------------------------------------------------------- #

#: Returned for anything that is not a canonical template.
OTHER_PAGE_TEMPLATE = "/other"

_STATIC_PAGE_TEMPLATES: tuple[str, ...] = (
    "/",
    "/about",
    "/analytics",
    "/analyses",
    "/analyses/fastp",
    "/analyses/scanpy",
    "/blast",
    "/browser",
    "/compare",
    "/downloads",
    "/genes",
    "/guide",
    "/help",
    "/login",
    "/mutants",
    "/news",
    "/publications",
    "/search",
    "/search/blast",
    "/search/gbrowse",
    "/search/genes",
    "/search/location",
    "/search/primer",
    "/search/tools",
    "/seed-request",
    "/sra",
    "/tools",
    "/tools/enrichment",
    "/tools/exppattern",
    "/tools/seqfetch",
    "/variants",
)

#: Parameter names are fixed and match the router; a template segment never
#: accepts a caller-chosen parameter name.
_DYNAMIC_PAGE_TEMPLATES: tuple[str, ...] = (
    "/analyses/:jobId",
    "/genes/:geneId",
    "/mutants/:publicId",
    "/news/:slug",
)

CANONICAL_PAGE_TEMPLATES: frozenset[str] = frozenset(_STATIC_PAGE_TEMPLATES) | frozenset(
    _DYNAMIC_PAGE_TEMPLATES
)

# Every value :func:`normalize_analytics_page` may return.
PAGE_TEMPLATE_OR_OTHER: frozenset[str] = CANONICAL_PAGE_TEMPLATES | {OTHER_PAGE_TEMPLATE}

# Static templates are matched first: ``/analyses/fastp`` is a real page, not an
# analysis job whose id happens to be "fastp".
_STATIC_SEGMENT_KEYS: frozenset[tuple[str, ...]] = frozenset(
    tuple(template.split("/")[1:]) for template in _STATIC_PAGE_TEMPLATES
)

# ``None`` marks the parameter position of a dynamic template.
_DYNAMIC_SEGMENT_PATTERNS: tuple[tuple[tuple[str | None, ...], str], ...] = tuple(
    (
        tuple(None if segment.startswith(":") else segment for segment in tpl.split("/")[1:]),
        tpl,
    )
    for tpl in _DYNAMIC_PAGE_TEMPLATES
)

# --------------------------------------------------------------------------- #
# Bounded input rules
# --------------------------------------------------------------------------- #

#: Inputs longer than this are rejected outright instead of being parsed.
MAX_RAW_INPUT_LENGTH = 2048
#: A single path segment longer than this cannot be an identifier we publish.
MAX_SEGMENT_LENGTH = 128

_ABSOLUTE_HTTP_URL = re.compile(r"\Ahttps?://", re.IGNORECASE)
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
#: Unreserved URL characters only (RFC 3986). Anything else in an identifier
#: position — a space, a slash, an "@", a decoded escape — is an anomaly.
_OPAQUE_SEGMENT = re.compile(r"\A[A-Za-z0-9._~-]+\Z")
_DOT_SEGMENTS = frozenset({".", ".."})


def _split_query_and_fragment(raw: str) -> str:
    """Drop a ``?query`` string and a ``#fragment`` from a root-relative input.

    ``urlsplit`` already does this for an absolute URL. Doing it by hand here
    gives both input forms one identical rule, and keeps ``urlsplit`` from ever
    seeing a leading ``//`` — which it would read as an authority and turn the
    protocol-relative ``//host/path`` into an acceptable path.
    """
    return raw.split("#", 1)[0].split("?", 1)[0]


def _extract_path(raw: str) -> str | None:
    """Return the path of *raw*, or ``None`` when it cannot be trusted.

    Strips an ``http(s)`` scheme together with its authority — which is where
    userinfo, host and port live — plus any query string or fragment. The same
    query/fragment stripping is applied to a root-relative path, so both forms
    of the same page normalise identically. A percent sign is never decoded:
    encoded input is an anomaly, not a value to be repaired, so decoding could
    only re-introduce traversal or separators that the segment checks below are
    there to reject.
    """
    if _ABSOLUTE_HTTP_URL.match(raw):
        try:
            parsed = urlsplit(raw)
        except ValueError:
            # Malformed authority (an unterminated IPv6 literal, for example).
            return None
        # ``.path`` excludes the userinfo, host, port, query and fragment, so
        # credentials cannot survive this assignment.
        path: str | None = parsed.path
    else:
        # A protocol-relative "//host/path" is not a path we accept; it keeps
        # its leading empty segment and is rejected by the caller.
        path = _split_query_and_fragment(raw)

    if path is None:
        return None
    if not path.startswith("/"):
        return None
    if "%" in path:
        return None
    if _CONTROL_CHARACTERS.search(path):
        return None
    return path


def normalize_analytics_page(value: object) -> str:
    """Map a requested page to a canonical template or to ``/other``.

    Accepts a path (``/mutants/42``) or an absolute HTTP(S) URL
    (``https://user:pw@host/mutants/42?q=x#y``). The return value is always one
    of :data:`PAGE_TEMPLATE_OR_OTHER`; no part of *value* is preserved, so an
    internal numeric identifier normalises exactly like a public one.

    The function is idempotent: every member of :data:`PAGE_TEMPLATE_OR_OTHER`
    is its own fixed point, so normalising an already-normalised value returns
    that value unchanged.
    """
    if not isinstance(value, str):
        return OTHER_PAGE_TEMPLATE

    raw = value.strip()
    if not raw or len(raw) > MAX_RAW_INPUT_LENGTH:
        return OTHER_PAGE_TEMPLATE
    if _CONTROL_CHARACTERS.search(raw):
        return OTHER_PAGE_TEMPLATE

    path = _extract_path(raw)
    if path is None:
        return OTHER_PAGE_TEMPLATE

    segments = path[1:].split("/")
    # Tolerate exactly one or more trailing slashes ("/news/" == "/news").
    while segments and segments[-1] == "":
        segments.pop()
    if not segments:
        return "/"
    if any(segment == "" for segment in segments):
        # Interior empty segment: "//" in the input, never a real route.
        return OTHER_PAGE_TEMPLATE
    if any(segment in _DOT_SEGMENTS for segment in segments):
        return OTHER_PAGE_TEMPLATE
    if any(len(segment) > MAX_SEGMENT_LENGTH for segment in segments):
        return OTHER_PAGE_TEMPLATE

    key = tuple(segments)
    if key in _STATIC_SEGMENT_KEYS:
        return "/" + "/".join(segments)

    # Round trip: a stored page is already a template, and its parameter name is
    # the router's own. It is matched against the closed canonical set above,
    # never against a colon-shaped pattern, so ``/mutants/:publicId`` returns
    # unchanged while ``/fake/:callerParam`` and ``/genes/:anythingElse`` fall
    # through to ``/other``: no caller-chosen name can enter the output.
    literal = "/" + "/".join(segments)
    if literal in CANONICAL_PAGE_TEMPLATES:
        return literal

    for pattern, template in _DYNAMIC_SEGMENT_PATTERNS:
        if len(pattern) != len(key):
            continue
        matched = True
        for expected, segment in zip(pattern, key):
            if expected is None:
                # An identifier position: opaque characters only, and the value
                # itself is discarded.
                if not _OPAQUE_SEGMENT.match(segment):
                    matched = False
                    break
            elif expected != segment:
                matched = False
                break
        if matched:
            return template

    # Not a public portal route (including internal-only paths such as
    # /admin/...): collapse rather than guess.
    return OTHER_PAGE_TEMPLATE


# --------------------------------------------------------------------------- #
# Referrer classification
# --------------------------------------------------------------------------- #

REFERRER_DIRECT = "direct"
REFERRER_SEARCH = "search"
REFERRER_SOCIAL = "social"
REFERRER_OTHER = "other"

REFERRER_CATEGORIES: frozenset[str] = frozenset(
    {REFERRER_DIRECT, REFERRER_SEARCH, REFERRER_SOCIAL, REFERRER_OTHER}
)

#: Maximum accepted referrer length; longer headers are not classified.
MAX_REFERRER_LENGTH = 2048

#: Hosts are matched on a label boundary, so "evil-google.com" never matches
#: "google.com". The lists are fixed constants, not a downloaded suffix list,
#: so classification needs no third-party data source.
_SEARCH_REFERER_HOSTS: frozenset[str] = frozenset(
    {
        "baidu.com",
        "bing.com",
        "duckduckgo.com",
        "ecosia.org",
        "google.com",
        "google.co.jp",
        "naver.com",
        "qwant.com",
        "search.brave.com",
        "so.com",
        "sogou.com",
        "yahoo.com",
        "yandex.ru",
    }
)

_SOCIAL_REFERER_HOSTS: frozenset[str] = frozenset(
    {
        "bilibili.com",
        "douban.com",
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "mastodon.social",
        "reddit.com",
        "telegram.org",
        "tiktok.com",
        "twitter.com",
        "weibo.com",
        "x.com",
        "youtube.com",
        "zhihu.com",
    }
)


def _host_in(host: str, domains: frozenset[str]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def classify_referrer(value: object) -> str:
    """Map a ``Referer`` header to ``direct``, ``search``, ``social`` or ``other``.

    A missing or blank referrer is ``direct``. The ``Referer`` header is
    client-controlled: the category describes a self-reported header only and
    is not a trustworthy statement about where a visit actually came from.

    The function is idempotent, like :func:`normalize_analytics_page`: a value
    that already *is* one of the four categories is returned unchanged, so a
    stored ``direct`` is not re-classified into ``other`` when it is read back.
    That fixed point is why this function, and not a second copy of the policy
    next to the store boundary, is the single owner of referrer classification.
    """
    if not isinstance(value, str):
        return REFERRER_DIRECT

    raw = value.strip()
    if not raw or raw == "-":
        return REFERRER_DIRECT
    if raw in REFERRER_CATEGORIES:
        # Already canonical: a stored category survives a second pass.
        return raw
    if len(raw) > MAX_REFERRER_LENGTH or _CONTROL_CHARACTERS.search(raw):
        return REFERRER_OTHER
    if not _ABSOLUTE_HTTP_URL.match(raw):
        # Scheme-relative or host-only values are not classified; we never
        # guess a host out of a non-URL string.
        return REFERRER_OTHER

    try:
        parsed = urlsplit(raw)
        # ``.hostname`` already drops any "user:password@" userinfo.
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return REFERRER_OTHER
    if not host:
        return REFERRER_OTHER
    if host.startswith("www."):
        host = host[4:]
    if _host_in(host, _SEARCH_REFERER_HOSTS):
        return REFERRER_SEARCH
    if _host_in(host, _SOCIAL_REFERER_HOSTS):
        return REFERRER_SOCIAL
    return REFERRER_OTHER


def referrer_column_value(value: object) -> str:
    """Return the canonical ``referrer``/``source`` **column** value for *value*.

    This is the storage adapter around :func:`classify_referrer`, not a second
    classification policy: every non-empty value is classified by that one
    function, and this wrapper only adds the column rule — *no hint at all*
    stores an empty column rather than claiming ``direct``, so an event that
    carried no referrer is not recorded as having come directly from the
    browser.

    The HTTP ingress therefore sees ``classify_referrer("") == "direct"`` (a
    blank header really is a direct visit), while the stored column stays empty
    for a value the caller never supplied.
    """
    if not isinstance(value, str) or not value.strip():
        return ""
    return classify_referrer(value)
