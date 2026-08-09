"""Email tasks (seed requests and friends) — smtplib + Jinja2 (D1).

Mail is sent with the stdlib ``smtplib`` (no new dependency): a MIME
``multipart/alternative`` message carries a plain-text and an HTML part,
both rendered from the Jinja2 templates in ``templates/email/`` (inline CSS,
science-green #2f6f4f brand, HarmonyOS Sans font fallback).

When SMTP is disabled (dev default, ``SOYMUTDB_SMTP_ENABLED=false``), the
rendered messages are written under ``logs/emails/`` instead — locally
verifiable without a mail server.  SMTP failures raise, so Celery retries
the task (at-least-once delivery, consistent with the outbox contract);
rendering and file-writing are pure and covered by unit tests.
"""

from __future__ import annotations

import logging
import re
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Any

from celery import Task
from jinja2 import Environment, FileSystemLoader, select_autoescape

from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.shared import JobPayload, SEED_REQUEST_EMAIL_TASK

logger = logging.getLogger(__name__)

#: Template directory (``soymutdb_worker/templates/email/``).
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"

#: Maximum recipients/address length guard (defense in depth).
_MAX_ADDR_LEN = 320

#: Minimal address shape guard (defense in depth on top of the API's
#: EmailStr validation — the worker must never hand a malformed address to
#: smtplib).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _jinja_env() -> Environment:
    """Jinja2 environment over the email template directory.

    HTML templates end in ``.html.j2`` and are autoescaped; plain-text
    templates end in ``.txt.j2`` and are not.
    """
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(("html", "html.j2")),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_email(kind: str, context: dict[str, Any]) -> tuple[str, str]:
    """Render ``(html, text)`` for an email *kind* (template stem).

    Raises ``TemplateNotFound`` for unknown kinds — callers only pass the
    template stems shipped with the worker.
    """
    env = _jinja_env()
    html = env.get_template(f"{kind}.html.j2").render(**context)
    text = env.get_template(f"{kind}.txt.j2").render(**context)
    return html, text


def build_message(
    *,
    subject: str,
    to_addr: str,
    html: str,
    text: str,
    from_addr: str,
    from_name: str = "SoyMutDB",
) -> EmailMessage:
    """Build a MIME ``multipart/alternative`` message (text + HTML)."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((from_name, from_addr))
    message["To"] = to_addr
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def _smtp_config() -> dict[str, Any]:
    """Read SMTP settings from the environment (canonical ``SOYMUTDB_`` names)."""
    enabled = get_setting("SMTP_ENABLED", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    return {
        "enabled": enabled,
        "host": get_setting("SMTP_HOST", "localhost"),
        "port": int(get_setting("SMTP_PORT", "587")),
        "username": get_setting("SMTP_USERNAME", ""),
        "password": get_setting("SMTP_PASSWORD", ""),
        "from_email": get_setting("SMTP_FROM_EMAIL", "no-reply@soymutdb.local"),
        "use_tls": get_setting("SMTP_USE_TLS", "true").strip().lower()
        in ("1", "true", "yes"),
        #: Admin notification recipient (defaults mirror the API's
        #: ``admin_email`` default).
        "admin_to": get_setting("SMTP_ADMIN_TO", "admin@soymutdb.local"),
        "log_dir": get_setting("EMAIL_LOG_DIR", "logs") + "/emails",
        "public_base_url": get_setting("PUBLIC_BASE_URL", "").rstrip("/"),
    }


def _smtp_send(message: EmailMessage, cfg: dict[str, Any]) -> None:
    """Deliver *message* over SMTP (STARTTLS + optional login).

    Any failure raises so the Celery task can retry.
    """
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
        if cfg["use_tls"]:
            server.starttls()
        if cfg["username"]:
            server.login(cfg["username"], cfg["password"])
        server.send_message(message)


def _sanitize_filename_part(value: str) -> str:
    """Reduce a free-text value to a safe filename fragment."""
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)[:64]


def _write_message_file(
    message: EmailMessage, log_dir: Path, *, kind: str, to_addr: str
) -> Path:
    """Persist the rendered message as an ``.eml`` file (dev fallback)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{stamp}_{kind}_{_sanitize_filename_part(to_addr)}.eml"
    path = log_dir / filename
    path.write_text(message.as_string(), encoding="utf-8")
    logger.info("Email %s to %s written to %s (SMTP disabled)", kind, to_addr, path)
    return path


def _deliver(
    *,
    kind: str,
    to_addr: str,
    subject: str,
    context: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Render and deliver one email; returns a delivery summary dict."""
    html, text = render_email(kind, context)
    message = build_message(
        subject=subject,
        to_addr=to_addr,
        html=html,
        text=text,
        from_addr=cfg["from_email"],
    )
    if cfg["enabled"]:
        _smtp_send(message, cfg)
        return {"delivered": True, "mode": "smtp", "to": to_addr, "kind": kind}
    path = _write_message_file(message, Path(cfg["log_dir"]), kind=kind, to_addr=to_addr)
    return {
        "delivered": False,
        "mode": "file",
        "to": to_addr,
        "kind": kind,
        "path": str(path),
    }


def _base_context(p: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Shared Jinja context for seed request emails."""
    gene_ids = [str(g) for g in (p.get("gene_ids") or [])]
    admin_url = ""
    if cfg["public_base_url"]:
        admin_url = f"{cfg['public_base_url']}/admin/seed-requests"
    return {
        "request_id": str(p.get("request_id", "")),
        "name": str(p.get("name", "")),
        "email": str(p.get("email", "")),
        "institution": str(p.get("institution", "")),
        "country": str(p.get("country", "")),
        "gene_ids": gene_ids,
        "gene_count": len(gene_ids),
        "notes": p.get("notes") or "",
        "status": str(p.get("status", "pending")),
        "created_at": str(p.get("created_at", "")),
        "admin_url": admin_url,
    }


@celery_app.task(
    bind=True,
    name=SEED_REQUEST_EMAIL_TASK,
    queue="default",
    max_retries=3,
    default_retry_delay=60,
)
def send_seed_request_email(
    self: Task,
    payload: dict | None = None,
    *,
    request_id: str | None = None,
    name: str | None = None,
    email: str | None = None,
    institution: str | None = None,
    country: str | None = None,
    gene_ids: list[str] | None = None,
    notes: str | None = None,
) -> dict:
    """Send the confirmation + admin-notification emails for a seed request.

    Two call styles are accepted:

    1. **Outbox contract** (canonical): ``payload`` is a serialized
       :class:`soymutdb_jobs.schemas.JobPayload` (versioned, idempotent).
    2. **Legacy kwargs** (compat for direct dispatches).

    The requester confirmation goes to the submitted address; the admin
    notification goes to ``SMTP_ADMIN_TO``.  With SMTP disabled both are
    written under ``logs/emails/`` (dev verification).  SMTP failures raise
    so Celery retries; redeliveries of the same event just re-send the same
    emails (idempotent from the recipient's perspective).
    """
    if payload is not None:
        job_payload = JobPayload.model_validate(payload)
        if job_payload.task_name != SEED_REQUEST_EMAIL_TASK:
            raise ValueError(
                f"Payload task_name {job_payload.task_name!r} does not match "
                f"task {SEED_REQUEST_EMAIL_TASK!r}"
            )
        req_id = str(job_payload.job_id)
        p = job_payload.payload
        request_id = str(p.get("request_id") or req_id)
        name = str(p["name"])
        email = str(p["email"])
        institution = str(p["institution"])
        country = str(p["country"])
        gene_ids = [str(g) for g in (p.get("gene_ids") or [])]
        notes = p.get("notes")
    else:
        if request_id is None or not name or not email:
            raise TypeError(
                "send_seed_request_email requires a JobPayload or legacy "
                "request_id/name/email kwargs"
            )
        gene_ids = list(gene_ids or [])

    if not email or len(email) > _MAX_ADDR_LEN or not _EMAIL_RE.match(email):
        raise ValueError(f"Refusing to send email to invalid address: {email!r}")

    cfg = _smtp_config()
    context = _base_context(
        {
            "request_id": request_id,
            "name": name,
            "email": email,
            "institution": institution or "",
            "country": country or "",
            "gene_ids": gene_ids,
            "notes": notes,
            "status": "pending",
        },
        cfg,
    )

    confirm = _deliver(
        kind="seed_request_confirm",
        to_addr=email,
        subject=f"SoyMutDB — Seed request received ({request_id[:8]})",
        context=context,
        cfg=cfg,
    )

    admin = _deliver(
        kind="seed_request_admin",
        to_addr=cfg["admin_to"],
        subject=f"SoyMutDB — New seed request from {name}",
        context=context,
        cfg=cfg,
    )

    logger.info(
        "Seed request %s emails dispatched (confirm=%s, admin=%s)",
        request_id,
        confirm["mode"],
        admin["mode"],
    )
    return {
        "request_id": request_id,
        "confirm": confirm,
        "admin": admin,
    }


__all__ = [
    "build_message",
    "render_email",
    "send_seed_request_email",
]
