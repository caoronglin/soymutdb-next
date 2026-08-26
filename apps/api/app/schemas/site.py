"""Pydantic schemas for public site-information endpoints (D4).

Contract:
- ``GET /api/v1/site/about`` -> AboutContentResponse
- ``GET /api/v1/site/home``  -> HomeContentResponse

All fields are optional — a fresh deployment without the corresponding
``system_settings`` rows returns ``None`` for every field.
"""

from __future__ import annotations

from pydantic import BaseModel


class AboutContentResponse(BaseModel):
    """Editable "About us" content backed by ``system_settings``."""

    title_en: str | None = None
    title_zh: str | None = None
    summary_en: str | None = None
    summary_zh: str | None = None
    content_en: str | None = None
    content_zh: str | None = None


class HomeContentResponse(BaseModel):
    """Editable homepage welcome block backed by ``system_settings``.

    Values are rich HTML (``home.*`` keys) — the public endpoint re-runs
    ``sanitize_rich_html`` on read so even rows written outside the admin
    settings API can never serve untrusted markup.
    """

    welcome_en: str | None = None
    welcome_zh: str | None = None


class FooterContentResponse(BaseModel):
    """Editable footer contact block backed by ``system_settings``.

    Values are plain text (``footer.*`` keys). A fresh deployment without the
    rows returns the registered defaults so the public footer renders without
    a separate fallback.
    """

    contact_person: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    copyright: str | None = None
    address: str | None = None
