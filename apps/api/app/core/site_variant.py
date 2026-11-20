"""Explicit site-variant contract shared by public site endpoints and builds.

A variant is selected by the deployment/build configuration.  It is never
inferred from request headers, hostnames, IP addresses, cookies, or user-agent.
"""

from __future__ import annotations

from .compat import StrEnum


class SiteVariant(StrEnum):
    """The two independently generated SoyMutDB site artifacts."""

    EXTERNAL = "external"
    INTERNAL = "internal"


SITE_VARIANTS: tuple[SiteVariant, ...] = (SiteVariant.EXTERNAL, SiteVariant.INTERNAL)
SITE_VARIANT_VALUES = frozenset(variant.value for variant in SITE_VARIANTS)
SITE_VARIANT_BASE_SECTIONS = frozenset({"about", "home", "footer", "header", "content"})


def variant_section(base_section: str, variant: SiteVariant) -> str:
    """Return the storage section for one explicit site variant."""
    if base_section not in SITE_VARIANT_BASE_SECTIONS:
        raise ValueError(f"Unsupported site-content section '{base_section}'")
    return f"{base_section}_{variant.value}"


def legacy_section_for_variant(section: str) -> str | None:
    """Return the legacy global section covered by a variant namespace."""
    for variant in SITE_VARIANTS:
        suffix = f"_{variant.value}"
        if section.endswith(suffix):
            base_section = section[: -len(suffix)]
            return base_section if base_section in SITE_VARIANT_BASE_SECTIONS else None
    return None


__all__ = [
    "SITE_VARIANT_BASE_SECTIONS",
    "SITE_VARIANT_VALUES",
    "SITE_VARIANTS",
    "SiteVariant",
    "legacy_section_for_variant",
    "variant_section",
]
