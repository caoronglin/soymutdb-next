"""Seed request email task tests (D1) – no docker, no DB, no real SMTP.

Covers:
- Jinja2 template rendering: HTML contains the key nodes (request ID, gene
  list, brand color), text rendering works, admin template carries the
  processing link.
- ``build_message`` produces a multipart/alternative message with both a
  plain-text and an HTML part.
- SMTP-enabled path sends via a mocked ``smtplib`` (STARTTLS + login called).
- SMTP-disabled path writes both messages under ``logs/emails/`` and the
  task returns file-mode delivery summaries.
- Payload contract: wrong task name rejected.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from soymutdb_worker.shared import JobPayload, SEED_REQUEST_EMAIL_TASK
from soymutdb_worker.tasks import email as email_module


class _FakeSMTP:
    """Records smtplib interactions for assertions."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.tls_called = False
        self.login_called = False
        self.login_credentials = None
        self.sent: list[Any] = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def starttls(self):
        self.tls_called = True

    def login(self, username, password):
        self.login_called = True
        self.login_credentials = (username, password)

    def send_message(self, message):
        self.sent.append(message)


def _payload(
    *,
    request_id: str | None = None,
    name: str = "Jane Doe",
    email: str = "jane@example.org",
    institution: str = "University of Soy",
    country: str = "China",
    gene_ids: list[str] | None = None,
    notes: str | None = "For my lab's drought project",
    task_name: str = SEED_REQUEST_EMAIL_TASK,
) -> dict:
    request_id = request_id or str(uuid.uuid4())
    now = datetime.now(UTC)
    p = JobPayload(
        job_id=request_id,
        task_name=task_name,
        payload={
            "request_id": request_id,
            "name": name,
            "email": email,
            "institution": institution,
            "country": country,
            "gene_ids": gene_ids or ["Glyma.01G000100", "Glyma.01G000200"],
            "notes": notes,
            "status": "pending",
        },
        idempotency_key=f"seed-request-email:{request_id}",
        created_at=now,
        updated_at=now,
    )
    return p.model_dump(mode="json")


def _call_task(task, *args, **kwargs):
    """Invoke the raw task function (bypassing Celery's bound-task wrapper)."""
    return task.run.__func__(*args, **kwargs)


def _disabled_config(tmp_path: Path) -> dict[str, Any]:
    return {
        "enabled": False,
        "host": "localhost",
        "port": 587,
        "username": "",
        "password": "",
        "from_email": "no-reply@soymutdb.local",
        "use_tls": True,
        "admin_to": "admin@soymutdb.local",
        "log_dir": str(tmp_path / "logs" / "emails"),
        "public_base_url": "https://soymutdb.example.org",
    }


def _enabled_config(tmp_path: Path) -> dict[str, Any]:
    cfg = _disabled_config(tmp_path)
    cfg["enabled"] = True
    cfg["username"] = "mailuser"
    cfg["password"] = "secret"
    return cfg


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


class TestRendering:
    def test_confirm_html_contains_key_nodes(self):
        html, text = email_module.render_email(
            "seed_request_confirm",
            {
                "request_id": "req-123",
                "name": "Jane Doe",
                "email": "jane@example.org",
                "institution": "University of Soy",
                "country": "China",
                "gene_ids": ["Glyma.01G000100", "Glyma.01G000200"],
                "gene_count": 2,
                "notes": "",
                "status": "pending",
                "created_at": "",
                "admin_url": "",
            },
        )
        # Unified layout: science-green brand + footer.
        assert "#2f6f4f" in html
        assert "SoyMutDB" in html
        assert "Seed request received" in html
        assert "req-123" in html
        assert "Jane Doe" in html
        assert "University of Soy" in html
        assert "Glyma.01G000100" in html
        assert "Glyma.01G000200" in html
        # Plain-text counterpart renders without markup.
        assert "Jane Doe" in text
        assert "<" not in text.splitlines()[0]

    def test_confirm_html_escapes_user_input(self):
        html, _ = email_module.render_email(
            "seed_request_confirm",
            {
                "request_id": "req-1",
                "name": "<script>alert(1)</script>",
                "email": "jane@example.org",
                "institution": "A&B",
                "country": "China",
                "gene_ids": ["Glyma.01G000100"],
                "gene_count": 1,
                "notes": "",
                "status": "pending",
                "created_at": "",
                "admin_url": "",
            },
        )
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_admin_html_contains_processing_link(self):
        html, text = email_module.render_email(
            "seed_request_admin",
            {
                "request_id": "req-456",
                "name": "Jane Doe",
                "email": "jane@example.org",
                "institution": "University of Soy",
                "country": "China",
                "gene_ids": ["Glyma.01G000100"],
                "gene_count": 1,
                "notes": "",
                "status": "pending",
                "created_at": "2026-08-09T10:00:00Z",
                "admin_url": "https://soymutdb.example.org/admin/seed-requests",
            },
        )
        assert "New seed request" in html
        assert "https://soymutdb.example.org/admin/seed-requests" in html
        assert "Manage seed requests" in html
        assert "req-456" in text

    def test_unknown_template_raises(self):
        with pytest.raises(Exception):
            email_module.render_email("does_not_exist", {})


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------


class TestBuildMessage:
    def test_message_is_multipart_alternative_with_both_parts(self):
        message = email_module.build_message(
            subject="Test subject",
            to_addr="jane@example.org",
            html="<p>Hello</p>",
            text="Hello",
            from_addr="no-reply@soymutdb.local",
        )
        assert message["Subject"] == "Test subject"
        assert message["To"] == "jane@example.org"
        assert "SoyMutDB" in message["From"]
        assert message.is_multipart()
        types = [part.get_content_type() for part in message.iter_parts()]
        assert "text/plain" in types
        assert "text/html" in types


# ---------------------------------------------------------------------------
# Delivery paths
# ---------------------------------------------------------------------------


class TestDeliver:
    def test_smtp_enabled_sends_via_smtplib(self, monkeypatch, tmp_path):
        fake_smtp = _FakeSMTP()
        monkeypatch.setattr(email_module.smtplib, "SMTP", lambda *a, **k: fake_smtp)

        result = email_module._deliver(
            kind="seed_request_confirm",
            to_addr="jane@example.org",
            subject="S",
            context={"name": "Jane"},
            cfg=_enabled_config(tmp_path),
        )

        assert result["delivered"] is True
        assert result["mode"] == "smtp"
        assert fake_smtp.tls_called is True
        assert fake_smtp.login_called is True
        assert fake_smtp.login_credentials == ("mailuser", "secret")
        assert len(fake_smtp.sent) == 1
        assert fake_smtp.sent[0]["To"] == "jane@example.org"
        assert fake_smtp.closed is True

    def test_smtp_failure_raises(self, monkeypatch, tmp_path):
        def boom(*args, **kwargs):
            raise ConnectionRefusedError("port closed")

        monkeypatch.setattr(email_module.smtplib, "SMTP", boom)
        with pytest.raises(ConnectionRefusedError):
            email_module._deliver(
                kind="seed_request_confirm",
                to_addr="jane@example.org",
                subject="S",
                context={"name": "Jane"},
                cfg=_enabled_config(tmp_path),
            )

    def test_disabled_writes_eml_file(self, tmp_path):
        result = email_module._deliver(
            kind="seed_request_confirm",
            to_addr="jane@example.org",
            subject="S",
            context={"name": "Jane", "gene_ids": [], "gene_count": 0},
            cfg=_disabled_config(tmp_path),
        )
        assert result["delivered"] is False
        assert result["mode"] == "file"
        path = Path(result["path"])
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "multipart/alternative" in content
        assert "text/plain" in content
        assert "text/html" in content


class TestTask:
    def test_disabled_task_writes_both_emails_to_logs(self, monkeypatch, tmp_path):
        payload = _payload()
        monkeypatch.setattr(
            email_module, "_smtp_config", lambda: _disabled_config(tmp_path)
        )
        result = _call_task(
            email_module.send_seed_request_email,
            None,
            payload=payload,
        )
        # File mode: both messages land under logs/emails/.
        assert result["request_id"] == payload["payload"]["request_id"]
        assert result["confirm"]["kind"] == "seed_request_confirm"
        assert result["admin"]["kind"] == "seed_request_admin"
        assert result["confirm"]["to"] == "jane@example.org"
        assert result["admin"]["to"] == "admin@soymutdb.local"
        assert result["confirm"]["mode"] == "file"
        assert result["admin"]["mode"] == "file"
        confirm_path = Path(result["confirm"]["path"])
        admin_path = Path(result["admin"]["path"])
        assert confirm_path.exists()
        assert admin_path.exists()
        assert str(tmp_path) in str(confirm_path)

    def test_smtp_enabled_task_sends_two_messages(self, monkeypatch, tmp_path):
        payload = _payload()
        fake_smtp = _FakeSMTP()
        monkeypatch.setattr(email_module.smtplib, "SMTP", lambda *a, **k: fake_smtp)
        monkeypatch.setattr(
            email_module, "_smtp_config", lambda: _enabled_config(tmp_path)
        )
        result = _call_task(
            email_module.send_seed_request_email,
            None,
            payload=payload,
        )
        assert result["confirm"]["mode"] == "smtp"
        assert result["admin"]["mode"] == "smtp"
        assert len(fake_smtp.sent) == 2
        to_addrs = {message["To"] for message in fake_smtp.sent}
        assert to_addrs == {"jane@example.org", "admin@soymutdb.local"}

    def test_wrong_task_name_in_payload_is_rejected(self):
        payload = _payload(task_name="soymutdb_worker.tasks.email.other_task")
        with pytest.raises(ValueError, match="does not match"):
            _call_task(email_module.send_seed_request_email, None, payload=payload)

    def test_missing_legacy_kwargs_rejected(self):
        with pytest.raises(TypeError, match="requires"):
            _call_task(email_module.send_seed_request_email, None, request_id="x")

    def test_invalid_recipient_rejected(self):
        payload = _payload(email="not-an-email")
        with pytest.raises(ValueError, match="invalid address"):
            _call_task(email_module.send_seed_request_email, None, payload=payload)
