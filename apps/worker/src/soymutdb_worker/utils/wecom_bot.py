"""Best-effort WeCom delivery through the official CLI.

Delivery goes through `wecom-cli` (https://github.com/WecomTeam/wecom-cli),
the official client, rather than hand-rolled HTTP. The CLI owns the wire
format, the encrypted credential store and the service schema; this module owns
only what the CLI cannot do for us: formatting a compact, injection-safe summary
and degrading to silence when the channel is not configured.

Configure two things in the worker's secret environment:

- ``SOYMUTDB_WECOM_BOT_CHAT_ID`` — the conversation to post to. A single chat takes the
  member's userid; a group takes the group conversation id. Run
  ``wecom-cli message aibot sessions list`` to discover it.
- the CLI's own credentials, once per host: ``wecom-cli auth init``.

If ``SOYMUTDB_WECOM_BOT_CHAT_ID`` is unset this channel is disabled and the
application's normal work continues. That is the contract the import, job and
email call sites rely on, so every failure path here returns False instead of
raising.

``WECOM_BOT_WEBHOOK`` is no longer read. Group-robot webhook delivery was
retired when the CLI became the transport; a host still setting the old
variable simply has no chat id and stays silent.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from soymutdb_worker.config import get_setting
from soymutdb_worker.wecom.cli import WecomCli

logger = logging.getLogger(__name__)
_MAX_CONTENT = 4096

#: Replaced in tests. A module-level indirection rather than a default argument
#: so a test can swap the transport without changing the public signature that
#: three production call sites already depend on.
_cli: WecomCli | None = None

_warned_unusable = False


def _client() -> WecomCli:
    global _cli
    if _cli is None:
        _cli = WecomCli()
    return _cli


def _safe_cell(value: object) -> str:
    """Keep one untrusted value on one line and out of Markdown control syntax."""
    text = str(value if value is not None else "—")
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    return text.replace("&", "＆").replace("<", "‹").replace(">", "›").replace("|", "¦")


def format_table_message(
    title: str,
    rows: Iterable[tuple[str, object]],
    *,
    link: str | None = None,
) -> str:
    """Format a small, readable field/value table for a WeCom Markdown message.

    WeCom's robot Markdown is not an interactive table widget, so rows become a
    compact summary that links back to the admin page for the full, sortable
    table. This avoids exposing whole database rows in chat.
    """
    lines = [f"### {_safe_cell(title)}"]
    for label, value in rows:
        lines.append(f"> **{_safe_cell(label)}：** {_safe_cell(value)}")
    if link:
        lines.append(f"\n[打开管理后台]({_safe_cell(link)})")
    content = "\n".join(lines)
    if len(content) > _MAX_CONTENT:
        content = content[: _MAX_CONTENT - 20].rstrip() + "\n…（内容已截断）"
    return content


def send_markdown(content: str) -> bool:
    """Send a Markdown message to the configured conversation.

    Returns False when disabled or when delivery fails. It never raises, so an
    external chat service cannot make an import/job/email task fail.
    """
    global _warned_unusable

    chat_id = str(get_setting("WECOM_BOT_CHAT_ID", "") or "").strip()
    if not chat_id:
        return False

    client = _client()
    if not client.is_installed():
        if not _warned_unusable:
            _warned_unusable = True
            logger.warning(
                "wecom_bot: wecom-cli is not installed; set WECOM_BOT_CHAT_ID and run "
                "`npm install -g @wecom/cli && wecom-cli auth init` to enable this channel"
            )
        return False

    result = client.send_markdown(chat_id, content[:_MAX_CONTENT])
    if result.ok:
        return True

    # Auth failures are a deployment problem, not a transient one: they repeat
    # on every message until an operator runs `wecom-cli auth init`. Say so once.
    if result.is_auth_failure:
        if not _warned_unusable:
            _warned_unusable = True
            logger.warning("wecom_bot: CLI credentials rejected; run `wecom-cli auth init`")
    else:
        logger.warning(
            "wecom_bot: delivery failed (exit=%s type=%s)",
            result.exit_code,
            result.error_type,
        )
    return False


def send_table(
    title: str,
    rows: Iterable[tuple[str, object]],
    *,
    link: str | None = None,
) -> bool:
    """Send a compact table-like Markdown summary, if the channel is configured."""
    return send_markdown(format_table_message(title, rows, link=link))


__all__ = ["format_table_message", "send_markdown", "send_table"]
