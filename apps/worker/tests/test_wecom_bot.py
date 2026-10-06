"""WeCom delivery via the official CLI: disabled-by-default and best effort.

The transport is exercised through a fake ``WecomCli`` so these tests assert
the module's own contract — disabled without configuration, silent on every
failure, never raising — rather than the CLI's behaviour, which the CLI's own
test suite owns. ``test_wecom_cli.py`` covers how a CLI result is interpreted.
"""
from __future__ import annotations

from soymutdb_worker.utils import wecom_bot
from soymutdb_worker.wecom.cli import CliResult


class _FakeCli:
    """Records what would have been sent; never touches a subprocess."""

    def __init__(self, result: CliResult, *, installed: bool = True) -> None:
        self.result = result
        self.installed = installed
        self.sent: list[tuple[str, str]] = []

    def is_installed(self) -> bool:
        return self.installed

    def send_markdown(self, chat_id: str, content: str) -> CliResult:
        self.sent.append((chat_id, content))
        return self.result


def _wire(monkeypatch, cli: _FakeCli, chat_id: str = "chat-1") -> _FakeCli:
    monkeypatch.setattr(wecom_bot, "_cli", cli)
    monkeypatch.setattr(wecom_bot, "_warned_unusable", False)
    monkeypatch.setattr(
        wecom_bot,
        "get_setting",
        lambda name, default="": chat_id if name.endswith("CHAT_ID") else default,
    )
    return cli


def test_format_table_is_readable_and_sanitizes_untrusted_cells():
    text = wecom_bot.format_table_message(
        "Import completed", [("status", "ready|<script>"), ("rows", 12)]
    )
    assert text.startswith("### Import completed")
    assert "ready¦‹script›" in text
    assert "**rows：** 12" in text


def test_an_overlong_summary_is_truncated_rather_than_rejected():
    text = wecom_bot.format_table_message("t", [("k", "x" * 9000)])
    assert len(text) <= 4096
    assert "内容已截断" in text


def test_missing_chat_id_is_a_noop(monkeypatch):
    cli = _wire(monkeypatch, _FakeCli(CliResult(ok=True, exit_code=0)), chat_id="")

    assert wecom_bot.send_table("title", [("key", "value")]) is False
    assert cli.sent == [], "must not invoke the CLI when the channel is disabled"


def test_a_delivery_that_succeeds_returns_true(monkeypatch):
    cli = _wire(monkeypatch, _FakeCli(CliResult(ok=True, exit_code=0)))

    assert wecom_bot.send_table("Seed request", [("gene count", 3)]) is True
    assert len(cli.sent) == 1
    chat_id, content = cli.sent[0]
    assert chat_id == "chat-1"
    assert "Seed request" in content


def test_a_missing_cli_degrades_instead_of_raising(monkeypatch):
    cli = _wire(monkeypatch, _FakeCli(CliResult(ok=True, exit_code=0), installed=False))

    assert wecom_bot.send_markdown("test") is False
    assert cli.sent == [], "an uninstalled CLI must not receive a message"


def test_a_rejected_delivery_is_reported_as_failure(monkeypatch):
    cli = _wire(
        monkeypatch,
        _FakeCli(CliResult(ok=False, exit_code=1, error_type="BackendError")),
    )

    assert wecom_bot.send_markdown("test") is False
    assert len(cli.sent) == 1


def test_an_auth_failure_is_reported_as_failure(monkeypatch):
    cli = _wire(
        monkeypatch,
        _FakeCli(CliResult(ok=False, exit_code=1, error_type="AuthError")),
    )

    assert wecom_bot.send_markdown("test") is False
    assert len(cli.sent) == 1


def test_the_retired_webhook_variable_no_longer_enables_the_channel(monkeypatch):
    """A host still carrying the old setting must go quiet, not half-work.

    Falling back to the webhook would keep two transports alive, which is the
    duplicate-owner state this change exists to remove.
    """
    monkeypatch.setattr(wecom_bot, "_cli", _FakeCli(CliResult(ok=True, exit_code=0)))
    monkeypatch.setattr(
        wecom_bot,
        "get_setting",
        lambda name, default="": (
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret"
            if name.endswith("WEBHOOK")
            else default
        ),
    )

    assert wecom_bot.send_markdown("test") is False
