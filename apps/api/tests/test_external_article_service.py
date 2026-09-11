"""Regression tests for the bounded, review-only external article preview service."""

from __future__ import annotations

import httpx
import pytest

from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.services.external_article_service import (
    ExternalArticlePreview,
    ExternalArticlePreviewService,
    extract_external_article,
    normalize_external_article_url,
    sign_external_article_preview,
    verify_external_article_preview_attestation,
)


@pytest.mark.parametrize(
    ("platform", "url", "expected"),
    [
        (
            "wechat",
            "HTTPS://MP.WEIXIN.QQ.COM/s?__biz=abc&mid=1#share",
            "https://mp.weixin.qq.com/s?__biz=abc&mid=1",
        ),
        (
            "xmol",
            "https://www.x-mol.com/university/article/123",
            "https://www.x-mol.com/university/article/123",
        ),
    ],
)
def test_normalize_external_article_url_accepts_only_canonical_platform_urls(
    platform: str, url: str, expected: str
) -> None:
    assert normalize_external_article_url(platform, url) == expected


@pytest.mark.parametrize(
    ("platform", "url"),
    [
        ("wechat", "http://mp.weixin.qq.com/s?x=1"),
        ("wechat", "https://evil.example/s?x=1"),
        ("wechat", "https://mp.weixin.qq.com:444/s?x=1"),
        ("wechat", "https://user:password@mp.weixin.qq.com/s?x=1"),
        ("xmol", "https://x-mol.com.evil.example/article"),
        ("unknown", "https://mp.weixin.qq.com/s?x=1"),
    ],
)
def test_normalize_external_article_url_rejects_non_allowlisted_origins(
    platform: str, url: str
) -> None:
    with pytest.raises(ValidationError):
        normalize_external_article_url(platform, url)


def test_extract_wechat_article_uses_content_root_and_sanitizes_html() -> None:
    html = """
    <html><head>
      <meta property="og:title" content="A source title">
      <meta property="article:published_time" content="2026-08-31T08:30:00Z">
    </head><body>
      <nav>Ignore navigation</nav>
      <div id="js_content">
        <p>Hello <strong>source</strong> article.</p>
        <script>alert('xss')</script>
        <a href="javascript:alert(1)" target="_blank">Unsafe link</a>
        <a href="https://example.org" target="_blank">Safe link</a>
      </div>
    </body></html>
    """

    preview = extract_external_article(
        "wechat", html, "https://mp.weixin.qq.com/s?__biz=abc"
    )

    assert preview.title == "A source title"
    assert preview.source_published_at is not None
    assert "Hello <strong>source</strong> article." in preview.content_html
    assert "Ignore navigation" not in preview.content_html
    assert "script" not in preview.content_html.lower()
    assert "javascript:" not in preview.content_html.lower()
    assert 'rel="noopener noreferrer"' in preview.content_html
    assert len(preview.source_content_hash) == 64


def test_extract_rejects_excessively_nested_markup() -> None:
    html = "<article>" + "<div>" * 300 + "body" + "</div>" * 300 + "</article>"

    with pytest.raises(ValidationError, match="too complex"):
        extract_external_article(
            "xmol", html, "https://www.x-mol.com/article/42"
        )


def test_extract_xmol_article_falls_back_to_article_element() -> None:
    preview = extract_external_article(
        "xmol",
        "<html><title>X-MOL source</title><body><article><h2>Heading</h2><p>Body</p></article></body></html>",
        "https://www.x-mol.com/article/42",
    )

    assert preview.title == "X-MOL source"
    assert preview.content_html == "<h2>Heading</h2><p>Body</p>"


async def test_preview_fetch_is_bounded_and_does_not_follow_redirects() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<title>Safe</title><div id='js_content'><p>Readable</p></div>",
        )

    service = ExternalArticlePreviewService(transport=httpx.MockTransport(handler))
    preview = await service.preview("wechat", "https://mp.weixin.qq.com/s?x=1")

    assert preview.title == "Safe"
    assert preview.content_html == "<p>Readable</p>"
    assert len(requests) == 1
    assert requests[0].url.host == "mp.weixin.qq.com"


async def test_preview_rejects_redirect_and_oversized_responses() -> None:
    redirect_service = ExternalArticlePreviewService(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(302, headers={"location": "https://evil.example"})
        )
    )
    with pytest.raises(ValidationError, match="redirected"):
        await redirect_service.preview("wechat", "https://mp.weixin.qq.com/s?x=1")

    too_large_service = ExternalArticlePreviewService(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/html", "content-length": "100"},
                content=b"x",
            )
        ),
        max_bytes=32,
    )
    with pytest.raises(ValidationError, match="too large"):
        await too_large_service.preview("wechat", "https://mp.weixin.qq.com/s?x=1")


async def test_preview_hides_upstream_failure_details() -> None:
    service = ExternalArticlePreviewService(
        transport=httpx.MockTransport(lambda _request: httpx.Response(403))
    )

    with pytest.raises(ServiceUnavailableError, match="did not return a readable article"):
        await service.preview("wechat", "https://mp.weixin.qq.com/s?x=1")


def test_preview_attestation_binds_canonical_source_provenance() -> None:
    preview = ExternalArticlePreview(
        platform="wechat",
        source_url="https://mp.weixin.qq.com/s?__biz=abc",
        title="Reviewed title",
        content_html="<p>Reviewed body</p>",
        source_content_hash="a" * 64,
        source_published_at=None,
    )

    attestation = verify_external_article_preview_attestation(
        sign_external_article_preview(preview, ttl=60)
    )

    assert attestation.platform == "wechat"
    assert attestation.source_url == preview.source_url
    assert attestation.source_content_hash == preview.source_content_hash


def test_preview_attestation_rejects_tampering_and_expiry() -> None:
    preview = ExternalArticlePreview(
        platform="xmol",
        source_url="https://www.x-mol.com/article/42",
        title="Reviewed title",
        content_html="<p>Reviewed body</p>",
        source_content_hash="b" * 64,
        source_published_at=None,
    )
    token = sign_external_article_preview(preview, ttl=60)

    with pytest.raises(ValidationError, match="invalid"):
        verify_external_article_preview_attestation(token[:-1] + "x")
    with pytest.raises(ValidationError, match="expired"):
        verify_external_article_preview_attestation(sign_external_article_preview(preview, ttl=-1))
