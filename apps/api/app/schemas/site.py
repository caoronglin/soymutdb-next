"""Pydantic schemas for public site-information endpoints (D4).

Contract:
- ``GET /api/v1/site/about`` -> AboutContentResponse
- ``GET /api/v1/site/home``  -> HomeContentResponse

All fields are optional — a fresh deployment without the corresponding
``system_settings`` rows returns ``None`` for every field.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.footer_content import FooterNavigationGroup

SiteVariant = Literal["external", "internal"]


class SiteBrandValues(BaseModel):
    """Bilingual display names and a verified media-library icon URL."""

    name_zh: str
    name_en: str
    icon_url: str | None = None


class SiteBrandResponse(SiteBrandValues):
    """Brand values for one explicitly selected public site variant."""

    variant: SiteVariant


class AdminSiteBrandResponse(BaseModel):
    """Versioned admin view; values are adapted from the settings registry."""

    model_config = ConfigDict(extra="forbid")

    variant: SiteVariant
    version: int = Field(ge=0)
    values: SiteBrandValues


class SiteBrandPatchValues(BaseModel):
    """Sparse site-brand patch. An explicit null icon clears the selection."""

    model_config = ConfigDict(extra="forbid")

    name_zh: str | None = Field(default=None, min_length=1, max_length=120)
    name_en: str | None = Field(default=None, min_length=1, max_length=120)
    icon_url: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def _at_least_one_value(self) -> "SiteBrandPatchValues":
        if not self.model_fields_set:
            raise ValueError("values must contain at least one brand field")
        for field in ("name_zh", "name_en"):
            value = getattr(self, field)
            if value is not None:
                normalized = value.strip()
                if not normalized:
                    raise ValueError(f"{field} must not be blank")
                setattr(self, field, normalized)
        if self.icon_url is not None:
            normalized_url = self.icon_url.strip()
            if not normalized_url:
                raise ValueError("icon_url must be a verified media URL or null")
            self.icon_url = normalized_url
        return self


class SiteBrandPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    values: SiteBrandPatchValues


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
    """Variant-specific, plain-text footer content and visible navigation."""

    # Legacy fields remain available to existing clients.
    contact_person: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    copyright: str | None = None
    address: str | None = None

    # New per-language content; phone/email values are shared across locales.
    contact_person_en: str | None = None
    contact_person_zh: str | None = None
    contact_phone_value: str | None = None
    contact_email_value: str | None = None
    address_en: str | None = None
    address_zh: str | None = None
    copyright_en: str | None = None
    copyright_zh: str | None = None
    navigation: list[FooterNavigationGroup] = Field(default_factory=list)
