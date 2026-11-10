"""Unit tests for :mod:`app.services.analytics_privacy`.

Pure-function tests only: no database, no HTTP client, no fixtures beyond
pytest itself. The route-table drift check reads the frontend TypeScript file
directly (UTF-8, at test time only) and fails — never skips — when the mirror in
the service module no longer matches.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.analytics_privacy import (
    CANONICAL_PAGE_TEMPLATES,
    MAX_RAW_INPUT_LENGTH,
    MAX_SEGMENT_LENGTH,
    OTHER_PAGE_TEMPLATE,
    PAGE_TEMPLATE_OR_OTHER,
    REFERRER_CATEGORIES,
    REFERRER_DIRECT,
    REFERRER_OTHER,
    REFERRER_SEARCH,
    REFERRER_SOCIAL,
    classify_referrer,
    normalize_analytics_page,
    referrer_column_value,
)

# --------------------------------------------------------------------------- #
# Sentinels: raw values that must never appear in a function's output.
# --------------------------------------------------------------------------- #

INTERNAL_ID_SENTINEL = "918273645"
PUBLIC_ID_SENTINEL = "MUT-000918273645"
SEARCH_SENTINEL = "sentinelqueryterm"
CREDENTIAL_SENTINEL = "sentinel-password-42"
HOST_SENTINEL = "sentinel-host.example"
EMAIL_SENTINEL = "sentinel.user@example.invalid"


# --------------------------------------------------------------------------- #
# Canonical mapping
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Static pages.
        ("/", "/"),
        ("/search", "/search"),
        ("/mutants", "/mutants"),
        ("/variants", "/variants"),
        ("/search/genes", "/search/genes"),
        ("/search/location", "/search/location"),
        ("/search/gbrowse", "/search/gbrowse"),
        ("/search/primer", "/search/primer"),
        ("/search/blast", "/search/blast"),
        ("/search/tools", "/search/tools"),
        ("/tools", "/tools"),
        ("/tools/seqfetch", "/tools/seqfetch"),
        ("/tools/sequence", "/tools/sequence"),
        ("/tools/exppattern", "/tools/exppattern"),
        ("/tools/enrichment", "/tools/enrichment"),
        ("/news", "/news"),
        ("/browser", "/browser"),
        ("/blast", "/blast"),
        ("/sra", "/sra"),
        ("/seed-request", "/seed-request"),
        ("/guide", "/guide"),
        ("/help", "/help"),
        ("/analytics", "/analytics"),
        ("/compare", "/compare"),
        ("/about", "/about"),
        ("/publications", "/publications"),
        ("/login", "/login"),
        ("/downloads", "/downloads"),
        ("/genes", "/genes"),
        # Public identifiers of every accepted parameter shape.
        (f"/mutants/{PUBLIC_ID_SENTINEL}", "/mutants/:publicId"),
        ("/mutants/42", "/mutants/:publicId"),
        # v4 and v5 gene ids are distinct namespaces; both collapse identically.
        ("/genes/Glyma.04G000100", "/genes/:geneId"),
        ("/genes/Glyma.16G000100", "/genes/:geneId"),
        ("/genes/GRMZM2G123456", "/genes/:geneId"),
        # Release/article slug.
        ("/news/2026-01-release-notes", "/news/:slug"),
        # Analysis job id.
        # Trailing slash tolerance.
        ("/mutants/", "/mutants"),
        ("/news/2026-01-release-notes/", "/news/:slug"),
        ("  /mutants  ", "/mutants"),
        # Absolute URLs: scheme, credentials, host, query and fragment are all
        # stripped, so the result is the same template as the bare path.
        (
            f"https://{HOST_SENTINEL}/mutants/{PUBLIC_ID_SENTINEL}",
            "/mutants/:publicId",
        ),
        (
            f"http://user:{CREDENTIAL_SENTINEL}@{HOST_SENTINEL}:8443"
            f"/genes/Glyma.16G000100?assembly=v5&q={SEARCH_SENTINEL}#frag",
            "/genes/:geneId",
        ),
        ("HTTPS://SOYMUTDB.EXAMPLE/news/2026-01-release-notes", "/news/:slug"),
    ],
)
def test_known_pages_map_to_their_template(raw: str, expected: str) -> None:
    assert normalize_analytics_page(raw) == expected


def test_internal_numeric_id_never_survives_as_a_value() -> None:
    """The historical leak shape: the raw id must not be the stored page."""
    result = normalize_analytics_page(f"/mutants/{INTERNAL_ID_SENTINEL}")
    assert result == "/mutants/:publicId"
    assert result != INTERNAL_ID_SENTINEL
    assert INTERNAL_ID_SENTINEL not in result


def test_stored_page_read_back_is_not_re_normalised_away() -> None:
    """A value that is already a template must survive a second pass."""
    result = normalize_analytics_page("/mutants/:publicId")
    assert result == "/mutants/:publicId"
    assert normalize_analytics_page(result) == result


@pytest.mark.parametrize(
    "raw",
    [
        # Trailing-slash tolerance (already a canonical page).
        "/news/",
        # Trailing slash plus a query/fragment on a canonical page.
        "/news#frag",
        "/news?q=sentinelqueryterm",
        # A scheme that is not http(s) keeps its own rejection.
        "ftp://sentinel.example/news",
        # Backslash and whitespace are not separators we honour.
        " /news ",
        # Nothing here may widen the identifier position into an echo.
        "/genes/Glyma.16G000100",
        f"/mutants/{INTERNAL_ID_SENTINEL}",
    ],
)
def test_normalization_is_idempotent(raw: str) -> None:
    once = normalize_analytics_page(raw)
    assert normalize_analytics_page(once) == once


def test_every_canonical_template_is_a_fixed_point() -> None:
    """The whole closed set, not a hand-picked sample of it."""
    assert CANONICAL_PAGE_TEMPLATES, "canonical template set is empty"
    for template in CANONICAL_PAGE_TEMPLATES:
        result = normalize_analytics_page(template)
        assert result == template, f"{template!r} is not idempotent: got {result!r}"
        assert normalize_analytics_page(result) == result


def test_other_is_a_fixed_point_too() -> None:
    assert normalize_analytics_page(OTHER_PAGE_TEMPLATE) == OTHER_PAGE_TEMPLATE


def test_relative_query_and_fragment_equate_the_absolute_form() -> None:
    """Root-relative input is stripped exactly like an absolute URL."""
    bare = "/mutants/42"
    expected = "/mutants/:publicId"
    assert normalize_analytics_page(bare) == expected
    assert normalize_analytics_page(f"{bare}?q={SEARCH_SENTINEL}") == expected
    assert normalize_analytics_page(f"{bare}#{SEARCH_SENTINEL}") == expected
    assert normalize_analytics_page(f"{bare}?q={SEARCH_SENTINEL}#{SEARCH_SENTINEL}") == expected
    for variant in (
        f"{bare}?q={SEARCH_SENTINEL}",
        f"{bare}#{SEARCH_SENTINEL}",
        f"https://{HOST_SENTINEL}{bare}?q={SEARCH_SENTINEL}",
        f"https://user:{CREDENTIAL_SENTINEL}@{HOST_SENTINEL}{bare}#{SEARCH_SENTINEL}",
    ):
        assert normalize_analytics_page(variant) == expected, variant
        assert SEARCH_SENTINEL not in normalize_analytics_page(variant)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # A static page behind a query string or fragment.
        ("/search?q=secret", "/search"),
        ("/search#secret", "/search"),
        ("/search/genes?assembly=v5", "/search/genes"),
        ("/search/primer#frag", "/search/primer"),
        # A dynamic page behind a query string or fragment.
        ("/mutants/42#secret", "/mutants/:publicId"),
        ("/genes/Glyma.16G000100?assembly=v5", "/genes/:geneId"),
        ("/news/2026-01-release-notes?ref=x", "/news/:slug"),
        # The root page keeps its identity behind a query string.
        ("/?utm_source=secret", "/"),
        # An unknown route still collapses: stripping is not widening.
        ("/admin/analytics/summary?q=secret", OTHER_PAGE_TEMPLATE),
        ("/mutants/a/b?q=secret", OTHER_PAGE_TEMPLATE),
    ],
)
def test_query_and_fragment_stripping_applies_to_relative_paths(raw: str, expected: str) -> None:
    assert normalize_analytics_page(raw) == expected
    # Same page, absolute form: the two spellings must agree.
    assert normalize_analytics_page(f"https://{HOST_SENTINEL}{raw}") == expected


@pytest.mark.parametrize(
    "raw",
    [
        # The reported shape: a caller-chosen parameter name on a fake route.
        "/fake/:callerParam",
        "/fake/:callerParam?q=secret",
        "/fake/:callerParam#secret",
        "https://sentinel.example/fake/:callerParam",
        # A known route with a parameter name that is not the router's.
        "/genes/:secretParam",
        "/mutants/:internalId",
        "/news/:unknownSlug",
        # Non-ASCII identifiers are not in the published identifier shape.
        "/mutants/café",
        "/genes/基因",
    ],
)
def test_caller_chosen_parameter_names_collapse_to_other(raw: str) -> None:
    assert normalize_analytics_page(raw) == OTHER_PAGE_TEMPLATE
    assert "callerParam" not in normalize_analytics_page(raw)


def test_canonical_parameter_names_are_the_only_ones_returned() -> None:
    """A colon-shaped output is one of four constants, never a caller's name."""
    expected = {"/genes/:geneId", "/mutants/:publicId", "/news/:slug"}
    # `/analyses/:jobId` left this set with the /analyses routes; the
    # assertion is about *which constants may escape*, not how many.
    produced = {
        normalize_analytics_page(f"{prefix}/{name}")
        for prefix in ("/genes", "/mutants", "/news", "/fake")
        for name in (":geneId", ":publicId", ":slug", ":jobId", ":callerParam", ":x")
    }
    assert {value for value in produced if ":" in value} == expected


@pytest.mark.parametrize(
    "raw",
    [
        # Unknown public paths and internal-only surfaces.
        "/admin",
        "/admin/users",
        "/admin/analytics/summary",
        "/console",
        "/api/v1/analytics/summary",
        "/internal/review",
        # Case is not a route: the canonical list is exact.
        "/Mutants",
        "/SEARCH",
        # Wrong arity for every known prefix.
        "/search/genes/extra",
        "/mutants/a/b",
        "/news/a/b",
        "/genes/a/b",
        # Relative and scheme-less forms.
        "mutants/42",
        "https-sentinel.example/mutants/42",
        "//sentinel.example/mutants/42",
        "",
        "   ",
        "\t\n",
        "not a path at all",
        None,
        42,
        3.14,
        b"/mutants/42",
        ["/mutants/42"],
    ],
)
def test_unknown_and_malformed_input_collapse_to_other(raw: object) -> None:
    assert normalize_analytics_page(raw) == OTHER_PAGE_TEMPLATE


@pytest.mark.parametrize(
    "raw",
    [
        # Traversal, in plain and percent-encoded form.
        "/mutants/../../admin/users",
        "/../admin/users",
        "/mutants/./42",
        "/mutants/..",
        "/..",
        "/mutants/%2e%2e%2fadmin",
        "/mutants/%2E%2E/admin",
        # Percent-encoding anomalies are never decoded.
        "/mutants/abc%20def",
        "/mutants/abc%zz",
        "/mutants/%",
        "/genes/Glyma.04G000100%2f%2fadmin",
        # Encoded or injected separators inside an identifier position.
        "/mutants/a%2Fb",
        "/mutants/a b",
        "/mutants/a+b",
        "/mutants/na@me",
        "/mutants/<script>",
        "/mutants/a'b",
        # Empty interior segments.
        "/mutants//42",
        "//mutants/42",
        # Over-long raw input and over-long segment.
        "/" + "a" * (MAX_RAW_INPUT_LENGTH + 1),
        "/mutants/" + "a" * (MAX_SEGMENT_LENGTH + 1),
        # Control characters.
        "/mutants/\n42",
        "/mutants/\x00",
        "/news/\x7fslug",
        # Malformed absolute URL authorities.
        "https://[::1/mutants/42",
    ],
)
def test_traversal_encoding_and_length_anomalies_collapse_to_other(raw: str) -> None:
    assert normalize_analytics_page(raw) == OTHER_PAGE_TEMPLATE


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Static templates win over the dynamic one that could also match.
        # (`/analyses/fastp` vs `/analyses/:jobId` used to cover this too;
        # both routes are gone, so `/news/news` and `/genes/genes` carry it.)
        ("/news/news", "/news/:slug"),
        ("/genes/genes", "/genes/:geneId"),
        ("/search/genes", "/search/genes"),
        ("/mutants/mutants", "/mutants/:publicId"),
    ],
)
def test_static_templates_win_over_dynamic_ones(raw: str, expected: str) -> None:
    """Matching is structural; no string-similarity inference is involved."""
    assert normalize_analytics_page(raw) == expected


def test_output_is_always_a_canonical_template_or_other() -> None:
    inputs = [
        "/",
        "/mutants/42",
        "/genes/Glyma.04G000100",
        "/news/2026-01-release-notes",
        "/analyses/8f2c0f3a-1f0a-4c2e-9a2e-6a4f1f0d77b1",
        f"https://{CREDENTIAL_SENTINEL}@{HOST_SENTINEL}/mutants/42?q={SEARCH_SENTINEL}",
        "/admin/users",
        "../etc/passwd",
        "",
        None,
    ]
    for raw in inputs:
        assert normalize_analytics_page(raw) in PAGE_TEMPLATE_OR_OTHER


@pytest.mark.parametrize(
    "sentinel",
    [
        INTERNAL_ID_SENTINEL,
        PUBLIC_ID_SENTINEL,
        SEARCH_SENTINEL,
        CREDENTIAL_SENTINEL,
        HOST_SENTINEL,
        EMAIL_SENTINEL,
    ],
)
def test_no_counterexample_leaks_its_raw_sentinel(sentinel: str) -> None:
    """Every shape that carries a sentinel must reduce it to a template."""
    shapes = [
        f"/mutants/{sentinel}",
        f"/genes/{sentinel}",
        f"/news/{sentinel}",
        f"https://{sentinel}:{sentinel}@soymutdb.example/mutants/{sentinel}",
        f"https://soymutdb.example/search?q={sentinel}",
        f"https://soymutdb.example/search#{sentinel}",
        f"/mutants/{sentinel}?ref={sentinel}",
    ]
    for raw in shapes:
        result = normalize_analytics_page(raw)
        assert sentinel not in result, f"{sentinel!r} leaked through {raw!r}"


# --------------------------------------------------------------------------- #
# Mirror drift against the frontend route table (test-time only)
# --------------------------------------------------------------------------- #

_ROUTES_TS = Path(__file__).resolve().parents[3] / "apps/web/src/router/routes.ts"
_PORTAL_ROUTES_MARKER = "export const PORTAL_ROUTES"
_PATH_LITERAL = re.compile(r"""path:\s*"([^"]*)\"""")


def _read_utf8(path: Path) -> str:
    """Read a source file with an explicit codec, never the locale default.

    The mirror below compares Python literals against TypeScript literals; a
    locale-dependent decode would make that comparison environment-dependent.
    """
    return path.read_text(encoding="utf-8")


def _portal_route_paths() -> set[str]:
    text = _read_utf8(_ROUTES_TS)
    marker_at = text.index(_PORTAL_ROUTES_MARKER)
    paths = {match for match in _PATH_LITERAL.findall(text[marker_at:])}
    assert paths, "no path literals parsed from PORTAL_ROUTES"
    return paths


def test_route_template_mirror_matches_portal_routes() -> None:
    """Fails on drift; it never skips when the frontend table is missing."""
    assert _ROUTES_TS.is_file(), f"missing route table: {_ROUTES_TS}"
    assert CANONICAL_PAGE_TEMPLATES == _portal_route_paths()


def test_route_table_is_decoded_as_utf8_not_the_locale_default(tmp_path: Path) -> None:
    """Non-ASCII bytes must survive the mirror read unchanged.

    The non-ASCII input is a controlled fixture written by this test, so the
    assertion cannot be broken by unrelated copy edits to the real route table
    (a retitled page, a different dash character). The real table is still read
    through the same explicit codec in the mirror check above.
    """
    probe = tmp_path / "routes.ts"
    probe.write_bytes('path: "/基因/café"\n'.encode())
    text = _read_utf8(probe)
    assert "基因" in text
    assert "café" in text
    # The explicit codec, not the locale default, is what decoded those bytes.
    assert text == 'path: "/基因/café"\n'


# --------------------------------------------------------------------------- #
# Referrer classification
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", REFERRER_DIRECT),
        ("   ", REFERRER_DIRECT),
        ("-", REFERRER_DIRECT),
        (None, REFERRER_DIRECT),
        (12345, REFERRER_DIRECT),
        ("https://www.google.com/search?q=soybean", REFERRER_SEARCH),
        ("https://google.com/", REFERRER_SEARCH),
        ("https://www.bing.com/search?q=x", REFERRER_SEARCH),
        ("https://duckduckgo.com/?q=x", REFERRER_SEARCH),
        ("https://baidu.com/s?wd=x", REFERRER_SEARCH),
        ("https://yandex.ru/search/?text=x", REFERRER_SEARCH),
        ("https://www.facebook.com/", REFERRER_SOCIAL),
        ("https://twitter.com/soymutdb", REFERRER_SOCIAL),
        ("https://x.com/soymutdb", REFERRER_SOCIAL),
        ("https://www.reddit.com/r/soybean/", REFERRER_SOCIAL),
        ("https://news.ycombinator.com/", REFERRER_OTHER),
        ("https://soymutdb.example/mutants/42", REFERRER_OTHER),
        ("https://", REFERRER_OTHER),
        ("https://google.com.evil.example/", REFERRER_OTHER),
        ("//google.com/", REFERRER_OTHER),
        ("google.com/search", REFERRER_OTHER),
        ("ftp://google.com/", REFERRER_OTHER),
        ("https://[::1/", REFERRER_OTHER),
        ("https://example.org/\n", REFERRER_OTHER),
        ("https://example.org/" + "a" * 4000, REFERRER_OTHER),
    ],
)
def test_referrer_categories(raw: object, expected: str) -> None:
    assert classify_referrer(raw) == expected


def test_referrer_output_is_only_a_category() -> None:
    raw = f"https://{EMAIL_SENTINEL}:{CREDENTIAL_SENTINEL}@{HOST_SENTINEL}:8443/search?q={SEARCH_SENTINEL}"
    result = classify_referrer(raw)
    assert result in REFERRER_CATEGORIES
    for sentinel in (EMAIL_SENTINEL, CREDENTIAL_SENTINEL, HOST_SENTINEL, SEARCH_SENTINEL):
        assert sentinel not in result


@pytest.mark.parametrize("hint", sorted(REFERRER_CATEGORIES))
def test_every_canonical_referrer_hint_is_a_fixed_point(hint: str) -> None:
    """All four hints, not a hand-picked sample.

    A stored category is read back by the same function that wrote it, so it
    has to survive a second pass unchanged: without that, ``direct`` would be
    re-classified as ``other`` and the summary would misreport every direct
    visit on a second read.
    """
    assert classify_referrer(hint) == hint
    assert classify_referrer(f"  {hint}  ") == hint
    assert classify_referrer(classify_referrer(hint)) == hint
    assert referrer_column_value(hint) == hint
    assert referrer_column_value(classify_referrer(hint)) == hint


@pytest.mark.parametrize("blank", ["", "   ", None, 42])
def test_a_missing_hint_stores_no_category_at_all(blank: object) -> None:
    """The column adapter keeps "no hint" empty; the header rule says ``direct``.

    The two are not a second policy: a blank *header* really is a direct visit,
    while a caller that supplied no hint at all must not have one recorded for
    it. ``direct`` is still a legal stored value, so this cannot erase a real
    direct visit.
    """
    assert classify_referrer(blank) == REFERRER_DIRECT
    assert referrer_column_value(blank) == ""


def test_referrer_category_is_header_based_not_origin_based() -> None:
    """A self-reported header is a hint; the docstring must keep saying so."""
    doc = classify_referrer.__doc__ or ""
    assert "client-controlled" in doc
    assert "Referer" in doc
    # An unknown host and a spoofed search engine land in the same finite set of
    # categories; neither is treated as authenticated origin.
    assert classify_referrer("https://www.google.com/") == REFERRER_SEARCH
    assert classify_referrer("https://soymutdb.example/") == REFERRER_OTHER
