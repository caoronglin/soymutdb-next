"""Pydantic schemas for public site-information endpoints (D4).

Contract:
- ``GET /api/v1/site/about`` -> AboutContentResponse

All fields are optional — a fresh deployment without ``about.*`` settings
rows returns ``None`` for every field.
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
