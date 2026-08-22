"""Typed, server-owned registry for mutable runtime settings.

``system_settings`` is deliberately only a storage mechanism.  This module is
the authority for which values administrators may write and how those values
are validated before persistence.  Credentials remain deployment secrets and
are never accepted by the runtime settings API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from urllib.parse import urlsplit


class SettingKind(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ENUM = "enum"
    EMAIL = "email"
    URL = "url"
    SECRET = "secret"


class SettingPermission(StrEnum):
    ADMINISTRATOR = "administrator"


class SettingScope(StrEnum):
    GLOBAL = "global"


class SettingRedaction(StrEnum):
    NONE = "none"
    OMIT = "omit"


type SettingDefault = str | int | bool | None


@dataclass(frozen=True)
class SettingDefinition:
    section: str
    key: str
    default: SettingDefault
    permission: SettingPermission
    scope: SettingScope
    hot_reload: bool
    redaction: SettingRedaction
    requires_approval: bool
    kind: SettingKind = SettingKind.STRING
    allowed_values: frozenset[str] = frozenset()
    allowed_url_hosts: frozenset[str] = frozenset()
    minimum: int | None = None
    maximum: int | None = None
    max_length: int = 10_000

    @property
    def full_key(self) -> str:
        return f"{self.section}.{self.key}"


class SettingValidationError(ValueError):
    """A setting key or value is outside the server-owned contract."""


def _definition(
    section: str,
    key: str,
    kind: SettingKind = SettingKind.STRING,
    *,
    default: SettingDefault,
    permission: SettingPermission,
    scope: SettingScope,
    hot_reload: bool,
    redaction: SettingRedaction,
    requires_approval: bool,
    **kwargs: object,
) -> SettingDefinition:
    return SettingDefinition(
        section=section,
        key=key,
        kind=kind,
        default=default,
        permission=permission,
        scope=scope,
        hot_reload=hot_reload,
        redaction=redaction,
        requires_approval=requires_approval,
        **kwargs,
    )


_DEFINITIONS = (
    _definition(
        "general",
        "siteName",
        default="SoyMutDB",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=120,
    ),
    _definition(
        "general",
        "siteDescription",
        default=("Comprehensive multi-species mutant database for functional genomics research"),
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=2_000,
    ),
    _definition(
        "general",
        "defaultLanguage",
        SettingKind.ENUM,
        default="en",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        allowed_values=frozenset({"en", "zh"}),
    ),
    _definition(
        "general",
        "defaultTheme",
        SettingKind.ENUM,
        default="light",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        allowed_values=frozenset({"light", "dark", "system"}),
    ),
    _definition(
        "about",
        "title_en",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=240,
    ),
    _definition(
        "about",
        "title_zh",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=240,
    ),
    _definition(
        "about",
        "summary_en",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=2_000,
    ),
    _definition(
        "about",
        "summary_zh",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=2_000,
    ),
    _definition(
        "about",
        "content_en",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=200_000,
    ),
    _definition(
        "about",
        "content_zh",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=200_000,
    ),
    _definition(
        "data",
        "defaultAssembly",
        default="Wm82v4.0",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=128,
    ),
    _definition(
        "data",
        "maxExportRecords",
        SettingKind.INTEGER,
        default=10_000,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        minimum=1,
        maximum=10_000_000,
    ),
    _definition(
        "data",
        "cacheTtlSeconds",
        SettingKind.INTEGER,
        default=300,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        minimum=0,
        maximum=86_400,
    ),
    _definition(
        "data",
        "enableClickhouse",
        SettingKind.BOOLEAN,
        default=True,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=False,
        redaction=SettingRedaction.NONE,
        requires_approval=True,
    ),
    _definition(
        "email",
        "smtpHost",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=False,
        redaction=SettingRedaction.NONE,
        requires_approval=True,
        max_length=255,
    ),
    _definition(
        "email",
        "smtpPort",
        SettingKind.INTEGER,
        default=587,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=False,
        redaction=SettingRedaction.NONE,
        requires_approval=True,
        minimum=1,
        maximum=65_535,
    ),
    _definition(
        "email",
        "fromAddress",
        SettingKind.EMAIL,
        default="noreply@soymutdb.org",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=320,
    ),
    _definition(
        "email",
        "enableNotifications",
        SettingKind.BOOLEAN,
        default=True,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
    ),
    # A stable forbidden definition produces a useful error instead of
    # treating a common credential name as an ordinary unknown key.
    _definition(
        "email",
        "smtpPassword",
        SettingKind.SECRET,
        default=None,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=False,
        redaction=SettingRedaction.OMIT,
        requires_approval=True,
    ),
    _definition(
        "security",
        "sessionTimeoutMinutes",
        SettingKind.INTEGER,
        default=60,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=True,
        minimum=5,
        maximum=10_080,
    ),
    _definition(
        "security",
        "maxLoginAttempts",
        SettingKind.INTEGER,
        default=5,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=True,
        minimum=1,
        maximum=100,
    ),
    _definition(
        "security",
        "requireTwoFactor",
        SettingKind.BOOLEAN,
        default=False,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=True,
    ),
    _definition(
        "security",
        "passwordMinLength",
        SettingKind.INTEGER,
        default=8,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=True,
        minimum=8,
        maximum=256,
    ),
    _definition(
        "file_preview",
        "enabled",
        SettingKind.BOOLEAN,
        default=True,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
    ),
    _definition(
        "file_preview",
        "max_size_mb",
        SettingKind.INTEGER,
        default=10,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        minimum=1,
        maximum=100,
    ),
    _definition(
        "file_preview",
        "enabled_formats",
        default="fasta,vcf,gff3,csv,tsv,png,jpg,svg,txt",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "navigation",
        "defaultSource",
        SettingKind.ENUM,
        default="published",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        allowed_values=frozenset({"published", "immutable_fallback"}),
    ),
    _definition(
        "seo",
        "defaultIndexingPolicy",
        SettingKind.ENUM,
        default="noindex",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=False,
        redaction=SettingRedaction.NONE,
        requires_approval=True,
        allowed_values=frozenset({"noindex", "published_only"}),
    ),
    _definition(
        "geo",
        "defaultCrawlerPolicy",
        SettingKind.ENUM,
        default="deny",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=False,
        redaction=SettingRedaction.NONE,
        requires_approval=True,
        allowed_values=frozenset({"deny", "retrieval_only", "retrieval_and_training"}),
    ),
    _definition(
        "motion",
        "defaultIntensity",
        SettingKind.ENUM,
        default="auto",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        allowed_values=frozenset({"auto", "standard", "minimal", "off"}),
    ),
    _definition(
        "imports",
        "defaultTemplateModule",
        SettingKind.ENUM,
        default="genes",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        allowed_values=frozenset({"genes"}),
    ),
    _definition(
        "imports",
        "defaultTemplateFormat",
        SettingKind.ENUM,
        default="tsv",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        allowed_values=frozenset({"tsv", "csv", "xlsx"}),
    ),
    _definition(
        "page_layout",
        "defaultTheme",
        SettingKind.ENUM,
        default="scientific-light",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        allowed_values=frozenset(
            {
                "scientific-light",
                "scientific-dark",
                "high-contrast",
                "compact-data",
                "print",
            }
        ),
    ),
    # Backward-compatible registered keys used by existing operators/tests.
    _definition(
        "blast",
        "max_sequences",
        SettingKind.INTEGER,
        default=100,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        minimum=1,
        maximum=10_000,
    ),
    _definition(
        "blast",
        "default_db",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=128,
    ),
    _definition(
        "features",
        "registration",
        SettingKind.BOOLEAN,
        default=False,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
    ),
    _definition(
        "cdn",
        "url",
        SettingKind.URL,
        default="https://cdn.example.com/",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=False,
        redaction=SettingRedaction.NONE,
        requires_approval=True,
        allowed_url_hosts=frozenset(
            {
                "cdn.example.com",
                "cdn-new.example.com",
                "cdnjs.cloudflare.com",
                "cdn.jsdelivr.net",
                "unpkg.com",
            }
        ),
        max_length=2_048,
    ),
)

SETTINGS_REGISTRY: Final[dict[str, SettingDefinition]] = {
    definition.full_key: definition for definition in _DEFINITIONS
}

_TRUE_VALUES: Final = frozenset({"1", "true", "yes", "on", "enabled"})
_FALSE_VALUES: Final = frozenset({"0", "false", "no", "off", "disabled"})
_EMAIL_RE: Final = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def get_setting_definition(section: str, key: str) -> SettingDefinition:
    full_key = f"{section}.{key}"
    try:
        return SETTINGS_REGISTRY[full_key]
    except KeyError as exc:
        raise SettingValidationError(f"Unknown setting '{full_key}'") from exc


def _validate_string(definition: SettingDefinition, value: object) -> str:
    if not isinstance(value, str):
        raise SettingValidationError(f"Setting '{definition.full_key}' must be a string")
    if len(value) > definition.max_length:
        raise SettingValidationError(
            f"Setting '{definition.full_key}' exceeds {definition.max_length} characters"
        )
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        raise SettingValidationError(f"Setting '{definition.full_key}' contains control characters")
    return value


def validate_setting_update(section: str, key: str, value: object) -> str:
    """Validate one registered value and return its canonical storage form."""
    definition = get_setting_definition(section, key)

    if definition.kind is SettingKind.SECRET:
        raise SettingValidationError(
            f"Setting '{definition.full_key}' is a deployment secret and cannot be stored here"
        )

    if definition.kind is SettingKind.BOOLEAN:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in _TRUE_VALUES:
                return "true"
            if normalized in _FALSE_VALUES:
                return "false"
        raise SettingValidationError(f"Setting '{definition.full_key}' must be a boolean")

    if definition.kind is SettingKind.INTEGER:
        if isinstance(value, bool):
            raise SettingValidationError(f"Setting '{definition.full_key}' must be an integer")
        try:
            parsed = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise SettingValidationError(
                f"Setting '{definition.full_key}' must be an integer"
            ) from exc
        if isinstance(value, float) and not value.is_integer():
            raise SettingValidationError(f"Setting '{definition.full_key}' must be an integer")
        if definition.minimum is not None and parsed < definition.minimum:
            raise SettingValidationError(
                f"Setting '{definition.full_key}' must be >= {definition.minimum}"
            )
        if definition.maximum is not None and parsed > definition.maximum:
            raise SettingValidationError(
                f"Setting '{definition.full_key}' must be <= {definition.maximum}"
            )
        return str(parsed)

    string_value = _validate_string(definition, value)
    if definition.kind is SettingKind.ENUM:
        if string_value not in definition.allowed_values:
            raise SettingValidationError(
                f"Setting '{definition.full_key}' must be one of: "
                + ", ".join(sorted(definition.allowed_values))
            )
    elif definition.kind is SettingKind.EMAIL:
        if not _EMAIL_RE.fullmatch(string_value):
            raise SettingValidationError(
                f"Setting '{definition.full_key}' must be a valid email address"
            )
    elif definition.kind is SettingKind.URL:
        parsed_url = urlsplit(string_value)
        if (
            parsed_url.scheme != "https"
            or parsed_url.hostname not in definition.allowed_url_hosts
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.fragment
        ):
            raise SettingValidationError(
                f"Setting '{definition.full_key}' URL must use HTTPS and a host from its allowlist"
            )
    return string_value


def registered_keys_for_section(section: str) -> frozenset[str]:
    return frozenset(
        definition.key
        for definition in SETTINGS_REGISTRY.values()
        if definition.section == section and definition.kind is not SettingKind.SECRET
    )


def public_setting_value(section: str, key: str, value: str) -> str | int | bool:
    """Convert a canonical storage string into its declared public type."""
    definition = get_setting_definition(section, key)
    if definition.kind is SettingKind.BOOLEAN:
        return value == "true"
    if definition.kind is SettingKind.INTEGER:
        return int(value)
    return value


__all__ = [
    "SETTINGS_REGISTRY",
    "SettingDefault",
    "SettingDefinition",
    "SettingKind",
    "SettingPermission",
    "SettingRedaction",
    "SettingScope",
    "SettingValidationError",
    "get_setting_definition",
    "public_setting_value",
    "registered_keys_for_section",
    "validate_setting_update",
]
