"""WeCom group-robot delivery: disabled-by-default and best effort."""
from __future__ import annotations

import json

from soymutdb_worker.utils import wecom_bot


class _Response:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def test_format_table_is_readable_and_sanitizes_untrusted_cells():
    text = wecom_bot.format_table_message(
        "Import completed", [("status", "ready|<script>"), ("rows", 12)]
    )
    assert text.startswith("### Import completed")
    assert "ready¦‹script›" in text
    assert "**rows：** 12" in text


def test_missing_webhook_is_noop(monkeypatch):
    monkeypatch.setattr(wecom_bot, "get_setting", lambda *_args: "")
    def unexpected(*_args, **_kwargs):
        raise AssertionError("must not make a network call when disabled")
    monkeypatch.setattr(wecom_bot, "urlopen", unexpected)
    assert wecom_bot.send_table("title", [("key", "value")]) is False


def test_sends_wecom_markdown_and_accepts_errcode_zero(monkeypatch):
    monkeypatch.setattr(
        wecom_bot, "get_setting", lambda *_args: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret"
    )
    captured = {}
    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response({"errcode": 0, "errmsg": "ok"})
    monkeypatch.setattr(wecom_bot, "urlopen", fake_urlopen)
    assert wecom_bot.send_table("Seed request", [("gene count", 3)]) is True
    assert captured["body"]["msgtype"] == "markdown"
    assert "Seed request" in captured["body"]["markdown"]["content"]
    assert captured["timeout"] <= 5
    assert "secret" not in str(captured["body"])


def test_refuses_non_official_or_http_webhook(monkeypatch):
    for url in ("http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x",
                "https://example.com/webhook?key=x"):
        monkeypatch.setattr(wecom_bot, "get_setting", lambda *_args, value=url: value)
        assert wecom_bot.send_markdown("test") is False


def test_nonzero_wecom_errcode_is_reported_as_failure(monkeypatch):
    monkeypatch.setattr(
        wecom_bot, "get_setting", lambda *_args: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x"
    )
    monkeypatch.setattr(
        wecom_bot,
        "urlopen",
        lambda *_args, **_kwargs: _Response({"errcode": 93000}),
    )
    assert wecom_bot.send_markdown("test") is False
