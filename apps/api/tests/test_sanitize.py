"""Server-side rich-text sanitisation tests (E2-1)."""

from __future__ import annotations

import pytest

from app.core.sanitize import sanitize_rich_html


class TestSanitizeRichHtml:
    def test_allows_whitelisted_tags(self) -> None:
        html = "<p>Hello <strong>bold</strong> <em>em</em> <a href='https://x'>x</a></p>"
        out = sanitize_rich_html(html)
        assert "<strong>" in out
        assert "<em>" in out
        assert "<p>" in out

    def test_strips_script_and_style(self) -> None:
        html = "<p>x</p><script>alert(1)</script><style>.a{}</style>"
        out = sanitize_rich_html(html)
        assert "script" not in out
        assert "style" not in out

    def test_strips_event_handlers(self) -> None:
        html = "<img src='x.png' onerror='alert(1)'>"
        out = sanitize_rich_html(html)
        assert "onerror" not in out

    def test_strips_javascript_url(self) -> None:
        html = "<a href='javascript:alert(1)'>x</a>"
        out = sanitize_rich_html(html)
        assert "javascript:" not in out

    def test_strips_iframe_and_object(self) -> None:
        html = "<iframe src='https://x'></iframe><object data='y'></object>"
        out = sanitize_rich_html(html)
        assert "iframe" not in out
        assert "object" not in out

    def test_allows_data_image_url(self) -> None:
        html = "<img src='data:image/png;base64,AAAA'>"
        out = sanitize_rich_html(html)
        assert "data:image/png" in out

    def test_rejects_data_svg(self) -> None:
        html = "<img src='data:image/svg+xml;base64,AAAA'>"
        out = sanitize_rich_html(html)
        assert "svg" not in out.lower()

    def test_target_blank_gets_rel(self) -> None:
        html = "<a href='https://x' target='_blank'>x</a>"
        out = sanitize_rich_html(html)
        assert "rel=" in out
        assert "noopener" in out

    def test_span_deliberately_removed(self) -> None:
        html = "<p><span style='color:red'>x</span></p>"
        out = sanitize_rich_html(html)
        assert "span" not in out
        assert "style" not in out

    def test_table_structure_kept(self) -> None:
        html = "<table><thead><tr><th>a</th></tr></thead><tbody><tr><td>b</td></tr></tbody></table>"
        out = sanitize_rich_html(html)
        assert "<table>" in out
        assert "<th>" in out
        assert "<td>" in out

    def test_empty_and_none_inputs(self) -> None:
        assert sanitize_rich_html("") == ""
        assert sanitize_rich_html("<p>x</p>") == "<p>x</p>"

    def test_plain_text_passthrough(self) -> None:
        out = sanitize_rich_html("hello world")
        assert "hello world" in out

    def test_href_allowed_protocols_only(self) -> None:
        html = "<a href='https://ok'>a</a><a href='file:///etc/passwd'>b</a>"
        out = sanitize_rich_html(html)
        assert "https://ok" in out
        assert "file:" not in out
