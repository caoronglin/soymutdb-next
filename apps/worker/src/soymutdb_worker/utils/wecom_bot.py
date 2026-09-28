"""Best-effort WeCom group-robot delivery.

Configure ``SOYMUTDB_WECOM_BOT_WEBHOOK`` with a group-robot webhook URL in the
worker's secret environment. The webhook is never logged or persisted. If it is
unset, this channel is disabled and the application's normal work continues.

WeCom's robot Markdown is not an interactive table widget; ``send_table``
formats rows as a compact Markdown summary and links back to the admin page for
the full, sortable table. This avoids exposing whole database rows in chat.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from soymutdb_worker.config import get_setting

logger = logging.getLogger(__name__)
_MAX_CONTENT = 4096
_TIMEOUT_SECONDS = 4


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
    """Format a small, readable field/value table for a WeCom Markdown robot."""
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
    """Send a Markdown message to the configured WeCom group robot.

    Returns False when disabled or when delivery fails. It never raises, so an
    external chat service cannot make an import/job/email task fail.
    """
    webhook = str(get_setting("WECOM_BOT_WEBHOOK", "") or "").strip()
    if not webhook:
        return False
    parsed = urlsplit(webhook)
    if parsed.scheme != "https" or parsed.hostname != "qyapi.weixin.qq.com":
        logger.warning("wecom_bot: refusing non-official or non-HTTPS webhook host")
        return False
    payload = json.dumps(
        {"msgtype": "markdown", "markdown": {"content": content[:_MAX_CONTENT]}},
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
        errcode = int(result.get("errcode", -1))
        if errcode != 0:
            logger.warning("wecom_bot: delivery rejected (errcode=%s)", errcode)
            return False
        return True
    except HTTPError as exc:
        logger.warning("wecom_bot: HTTP delivery failed (status=%s)", exc.code)
    except (URLError, TimeoutError, OSError, ValueError, TypeError) as exc:
        logger.warning("wecom_bot: delivery failed (%s)", type(exc).__name__)
    return False


def send_table(
    title: str,
    rows: Iterable[tuple[str, object]],
    *,
    link: str | None = None,
) -> bool:
    """Send a compact table-like Markdown summary, if the robot is configured."""
    return send_markdown(format_table_message(title, rows, link=link))


__all__ = ["format_table_message", "send_markdown", "send_table"]
