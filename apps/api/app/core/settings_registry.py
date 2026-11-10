"""Typed, server-owned registry for mutable runtime settings.

``system_settings`` is deliberately only a storage mechanism.  This module is
the authority for which values administrators may write and how those values
are validated before persistence.  Credentials remain deployment secrets and
are never accepted by the runtime settings API.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final
from urllib.parse import urlsplit

from .footer_content import (
    DEFAULT_FOOTER_NAVIGATION_JSON,
    MAX_FOOTER_NAVIGATION_BYTES,
    FooterContentValidationError,
    validate_footer_setting,
)
from .header_navigation import (
    DEFAULT_HEADER_NAVIGATION_JSON,
    MAX_HEADER_NAVIGATION_BYTES,
    HeaderContentValidationError,
    validate_header_setting,
)
from .site_variant import SITE_VARIANT_BASE_SECTIONS, SITE_VARIANTS, SiteVariant, variant_section


class SettingKind(StrEnum):
    STRING = "string"
    COLOR = "color"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ENUM = "enum"
    EMAIL = "email"
    URL = "url"
    UUID = "uuid"
    SECRET = "secret"


class SettingPermission(StrEnum):
    ADMINISTRATOR = "administrator"


class SettingScope(StrEnum):
    GLOBAL = "global"


class SettingRedaction(StrEnum):
    NONE = "none"
    OMIT = "omit"


#: Spelled without ``type`` on purpose. The value is serialised straight into
#: ``SettingFieldSchema.default`` (see ``/admin/settings/schema``), so it must
#: stay byte-identical to that field's inline union
#: (``str | int | bool | None``). A PEP 695 ``type`` alias is a referenceable
#: object: pydantic hoists it into ``components/schemas`` and emits ``$ref``, and
#: the OpenAPI normaliser then deletes the component -- which is how 8 dangling
#: ``$ref``s reached the generated client. Two spellings of one union in the same
#: response is the drift this exists to prevent.
SettingDefault = str | int | bool | None


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
    # Named instead of `**kwargs: object`: the pass-through form erases every
    # option's type, so each of the nine constructions above reported an
    # argument-type error against the dataclass it was building.
    allowed_values: frozenset[str] = frozenset(),
    allowed_url_hosts: frozenset[str] = frozenset(),
    minimum: int | None = None,
    maximum: int | None = None,
    max_length: int = 10_000,
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
        allowed_values=allowed_values,
        allowed_url_hosts=allowed_url_hosts,
        minimum=minimum,
        maximum=maximum,
        max_length=max_length,
    )


# Annotated as an open tuple: this constant is extended in three later
# reassignments, and letting the checker infer a fixed-length tuple made every
# extension a spurious type error whose message printed all 175 elements.
_DEFINITIONS: tuple[SettingDefinition, ...] = (
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
        "databaseKind",
        SettingKind.ENUM,
        default="genome",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        allowed_values=frozenset({"genome", "gene_ontology", "transcription_factor"}),
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
        "general",
        "primaryColor",
        SettingKind.COLOR,
        default="#2f6f4f",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=7,
    ),
    # Footer contact block — editable by admins at runtime and served to
    # the public site footer via GET /site/footer.
    _definition(
        "footer",
        "contact_person",
        default="联系人: 周玲",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "footer",
        "contact_phone",
        default="电话: 025-84391957",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "footer",
        "contact_email",
        default="电子邮件: zlingxiaoyao@163.com",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "footer",
        "copyright",
        default="© {{year}} SoyMutDB. All rights reserved.",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "footer",
        "address",
        default="地址: 南京市玄武区钟灵街50号 邮编210014",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    # New bilingual footer fields and the bounded grouped navigation document.
    _definition(
        "footer",
        "contact_person_en",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "footer",
        "contact_person_zh",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "footer",
        "contact_phone_value",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=32,
    ),
    _definition(
        "footer",
        "contact_email_value",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=254,
    ),
    _definition(
        "footer",
        "address_en",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "footer",
        "address_zh",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "footer",
        "copyright_en",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "footer",
        "copyright_zh",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "footer",
        "navigation_json",
        default=DEFAULT_FOOTER_NAVIGATION_JSON,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=MAX_FOOTER_NAVIGATION_BYTES,
    ),
    _definition(
        "header",
        "navigation_json",
        default=DEFAULT_HEADER_NAVIGATION_JSON,
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=MAX_HEADER_NAVIGATION_BYTES,
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
    # Homepage welcome block.  It is registered here as well as the legacy
    # public endpoint so both generated sites can be edited independently.
    _definition(
        "home",
        "welcome_en",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=200_000,
    ),
    _definition(
        "home",
        "welcome_zh",
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
    # ---------------------------------------------------------------------
    # Site content (content.*) — editable frontend text + image URLs.
    #
    # Every key here is returned by the public GET /api/v1/site/content
    # endpoint (short key, e.g. "hero.title") together with the stored value
    # or this registered default when the row does not exist.  Defaults match
    # the current English (default-language) UI strings so a fresh deployment
    # renders identically until an administrator edits them.
    # ---------------------------------------------------------------------
    # Hero block (home page).
    _definition(
        "content",
        "hero.eyebrow",
        default="SOYMUTDB · MULTI-SPECIES",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=240,
    ),
    _definition(
        "content",
        "hero.title",
        default="Explore the Unknown Territories of Multi-Species Mutation",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "hero.subtitle",
        default=(
            "A next-generation multi-species mutation database — from genome to "
            "phenotype in one place."
        ),
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=2_000,
    ),
    _definition(
        "content",
        "hero.image",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=2_048,
    ),
    # Homepage tool directory cards.
    _definition(
        "content",
        "tool.gene.label",
        default="Gene ID Search",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "tool.gene.desc",
        default="Look up mutations by gene ID",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "tool.gene.image",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=2_048,
    ),
    _definition(
        "content",
        "tool.location.label",
        default="Position Search",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "tool.location.desc",
        default="Look up by chromosome and locus",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "tool.location.image",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=2_048,
    ),
    _definition(
        "content",
        "tool.gbrowse.label",
        default="JBrowse 2",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "tool.gbrowse.desc",
        default="Browse the genome in JBrowse 2",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "tool.gbrowse.image",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=2_048,
    ),
    _definition(
        "content",
        "tool.blast.label",
        default="BLAST",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "tool.blast.desc",
        default="Find homologs by sequence alignment",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "tool.blast.image",
        default="",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=2_048,
    ),
    _definition(
        "content",
        "search.genes.title",
        default="Gene ID Search",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "search.genes.subtitle",
        default="Find genes by gene ID in a genome version",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=1_000,
    ),
    _definition(
        "content",
        "search.genes.colAssembly",
        default="Genome version",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.genes.colGbrowse",
        default="JBrowse 2",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.location.title",
        default="Physical Location Search",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "search.location.subtitle",
        default="Find variants and genes in a genomic region",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=1_000,
    ),
    _definition(
        "content",
        "search.location.colGbrowse",
        default="JBrowse 2",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.tabGenes",
        default="Gene ID",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.tabLocation",
        default="Physical Location",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.tabGbrowse",
        default="JBrowse 2",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "tools.seqfetch.title",
        default="Sequence Fetch",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "tools.enrichment.title",
        default="GO / KEGG Enrichment",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "tools.exppattern.title",
        default="Expression Pattern",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    # BLAST form + results table headers.
    _definition(
        "content",
        "blastPublic.subtitle",
        default=(
            "Run one protein search without creating an account. "
            "Keep this tab open while your result is processed."
        ),
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "blast.searchType",
        default="BLAST Type",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "blast.database",
        default="Reference sequence type",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "blast.sequencePlaceholder",
        default="Paste sequence in FASTA format...",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "blast.submit",
        default="BLAST",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=128,
    ),
    _definition(
        "content",
        "blast.eValue",
        default="E-value threshold",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "blast.maxHits",
        default="Max hits",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "blast.hitSequenceId",
        default="Sequence ID",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "blast.hitGeneId",
        default="Gene ID",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "blast.hitCoverage",
        default="Coverage",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "blast.hitEValue",
        default="E-value",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "blast.hitProteinCoords",
        default="Protein coords",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    # Help page headings + FAQ (explicit keys keep the editor simple).
    _definition(
        "content",
        "help.gettingStarted",
        default="Getting Started",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "help.documentation",
        default="Documentation",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "help.contact",
        default="Contact Support",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "help.faq",
        default="Frequently Asked Questions",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "help.faq1.q",
        default="How do I search for a gene?",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=1_000,
    ),
    _definition(
        "content",
        "help.faq1.a",
        default=(
            "Use the search bar at the top of any page, or visit the Genes page to "
            "filter by chromosome, biotype, or keyword. Gene IDs follow the "
            "Glyma.01G000100 format."
        ),
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=4_000,
    ),
    _definition(
        "content",
        "help.faq2.q",
        default="How do I download variant data?",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=1_000,
    ),
    _definition(
        "content",
        "help.faq2.a",
        default=(
            "Visit the Downloads page for the files currently published for a "
            "release. Check each item's format, assembly, release, and provenance "
            "metadata before using it in an analysis."
        ),
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=4_000,
    ),
    _definition(
        "content",
        "help.faq3.q",
        default="Can I request mutant seeds?",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=1_000,
    ),
    _definition(
        "content",
        "help.faq3.a",
        default=(
            "Open the Seed Request page to see whether requests are currently "
            "enabled and to review the eligibility and distribution terms shown "
            "during submission."
        ),
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=4_000,
    ),
    _definition(
        "content",
        "help.faq4.q",
        default="How do I cite SoyMutDB?",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=1_000,
    ),
    _definition(
        "content",
        "help.faq4.a",
        default=(
            "Use the citation and provenance metadata published with the exact "
            "data release you used. A journal citation or DOI is shown only after "
            "it has been verified by the project maintainers."
        ),
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=4_000,
    ),
    _definition(
        "content",
        "help.faq5.q",
        default="What genome assembly is used?",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=1_000,
    ),
    _definition(
        "content",
        "help.faq5.a",
        default=(
            "The assembly is part of the search, record, browser, and download "
            "context. Confirm the displayed assembly before comparing or combining "
            "genomic coordinates."
        ),
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=4_000,
    ),
    _definition(
        "content",
        "help.faq6.q",
        default="How often is the data updated?",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=1_000,
    ),
    _definition(
        "content",
        "help.faq6.a",
        default=(
            "Release versions and publication dates are announced on the News and "
            "Downloads pages. SoyMutDB does not promise a fixed release cadence on "
            "this Help page."
        ),
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=4_000,
    ),
    # Generic UI strings.
    _definition(
        "content",
        "ui.searchButton",
        default="Search",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=128,
    ),
    _definition(
        "content",
        "ui.loading",
        default="Loading...",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=128,
    ),
    _definition(
        "content",
        "ui.errorRetry",
        default="Retry",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=128,
    ),
    _definition(
        "content",
        "ui.noResults",
        default="No results found",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.home",
        default="Home",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.search",
        default="Search",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.tools",
        default="Tools",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.resources",
        default="Resources",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.downloads",
        default="Downloads",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.allTools",
        default="All tools",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.blast",
        default="BLAST",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.comparative",
        default="Comparative",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.expression",
        default="Expression",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.phenotypes",
        default="Phenotypes",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.sra",
        default="SRA Browser",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.guide",
        default="Guide",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.help",
        default="Help",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.news",
        default="News",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.publications",
        default="Publications",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.seedRequest",
        default="Seed Request",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "nav.about",
        default="About",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "genes.title",
        default="Gene Search",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "genes.subtitle",
        default="Browse gene models, annotations and homologs",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=1000,
    ),
    _definition(
        "content",
        "variants.title",
        default="Variant Search",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "variants.subtitle",
        default="Search and explore genomic variant information",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=1000,
    ),
    _definition(
        "content",
        "downloads.title",
        default="Downloads",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=512,
    ),
    _definition(
        "content",
        "downloads.subtitle",
        default="Download genomic data and resources",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=1000,
    ),
    _definition(
        "content",
        "search.genes.assembly",
        default="Genome version",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.genes.assemblyPlaceholder",
        default="Select a genome version",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.genes.geneIdHint",
        default="Multiple gene IDs are supported — one per line.",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.genes.geneIdPlaceholder",
        default="One gene ID per line, e.g. Glyma.01G000100",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.location.assembly",
        default="Genome version",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.location.chromosome",
        default="Chromosome",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.location.start",
        default="Start",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.location.end",
        default="End",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.location.submit",
        default="Search",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
)

# ---------------------------------------------------------------------------
# Portal-consumed content keys registered 2026-10-18.
#
# The portal reads these through `useSiteContent().get("<key>", t(...))`, but
# they were never registered, so Admin could not edit them and the server-side
# override path could never fire for them. Defaults mirror the current English
# UI copy; Chinese still renders from the i18n fallback when no stored override
# exists (the portal fetches only overrides). The site-variant mirror below
# copies these definitions automatically.
# ---------------------------------------------------------------------------
_PORTAL_CONSUMED_CONTENT_DEFINITIONS = (
    _definition(
        "content",
        "downloads.download",
        default="Download",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "downloads.checksum",
        default="Checksum",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "downloads.generatedAt",
        default="Generated",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "downloads.license",
        default="License",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "downloads.fileName",
        default="File Name",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "downloads.fileSize",
        default="Size",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "downloads.format",
        default="Format",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "downloads.lastUpdated",
        default="Last Updated",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "downloads.preview",
        default="Preview",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "downloads.too_large",
        default="Too large for preview",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "hero.subtitle",
        default=(
            "A next-generation multi-species mutation database — "
            "from genome to phenotype in one place."
        ),
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "home.heroTitle",
        default="Explore the unknown frontier of multi-species mutations",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.genes.geneId",
        default="Gene ID",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.location.assemblyPlaceholder",
        default="Select a genome version",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "search.location.formatHint",
        default="Region format: chromosome : start–end",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.allChromosomes",
        default="All Chromosomes",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.allImpacts",
        default="All Impacts",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.allTypes",
        default="All Types",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.assembly",
        default="Genome version",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.chromosome",
        default="Chromosome",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.chromosomeLabel",
        default="Chromosome",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.export",
        default="Export",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.geneSymbol",
        default="Gene Symbol",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.impact",
        default="Impact",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.impactLabel",
        default="Impact",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.noResults",
        default="No matching variants found",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.positionLabel",
        default="Position",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.variantId",
        default="Variant ID",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.variantType",
        default="Variant Type",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
    _definition(
        "content",
        "variants.variantTypeLabel",
        default="Type",
        permission=SettingPermission.ADMINISTRATOR,
        scope=SettingScope.GLOBAL,
        hot_reload=True,
        redaction=SettingRedaction.NONE,
        requires_approval=False,
        max_length=256,
    ),
)
_DEFINITIONS = (*_DEFINITIONS, *_PORTAL_CONSUMED_CONTENT_DEFINITIONS)

# Variant-specific copies preserve the existing settings validation, optimistic
# revisions, and audit trail while keeping every site's values in a separate
# namespace.  The selected variant is explicit at build/request time; the API
# never infers it from the visitor.
_SITE_VARIANT_DEFAULT_OVERRIDES: Final[dict[tuple[str, str], SettingDefault]] = {
    (SiteVariant.INTERNAL.value, "hero.eyebrow"): "SOYMUTDB · INTERNAL RESEARCH",
    (SiteVariant.INTERNAL.value, "hero.title"): "Internal Research Workspace for SoyMutDB",
    (SiteVariant.INTERNAL.value, "hero.subtitle"): (
        "A private workspace for curators and collaborators to review mutation "
        "data, releases, and analysis tools."
    ),
    (SiteVariant.INTERNAL.value, "nav.home"): "Research Workspace",
    (SiteVariant.INTERNAL.value, "nav.about"): "Project Notes",
}

_SITE_VARIANT_DEFINITIONS = tuple(
    replace(
        definition,
        section=variant_section(definition.section, variant),
        default=_SITE_VARIANT_DEFAULT_OVERRIDES.get(
            (variant.value, definition.key), definition.default
        ),
    )
    for definition in _DEFINITIONS
    if definition.section in SITE_VARIANT_BASE_SECTIONS
    for variant in SITE_VARIANTS
)
_DEFINITIONS = (*_DEFINITIONS, *_SITE_VARIANT_DEFINITIONS)

# Branding is stored in explicit variant namespaces so the external and
# internal sites can never fall through to each other's values.
_BRAND_DEFINITIONS = tuple(
    definition
    for variant in ("external", "internal")
    for definition in (
        _definition(
            f"brand_{variant}",
            "name_zh",
            default="SoyMutDB",
            permission=SettingPermission.ADMINISTRATOR,
            scope=SettingScope.GLOBAL,
            hot_reload=True,
            redaction=SettingRedaction.NONE,
            requires_approval=False,
            max_length=120,
        ),
        _definition(
            f"brand_{variant}",
            "name_en",
            default="SoyMutDB",
            permission=SettingPermission.ADMINISTRATOR,
            scope=SettingScope.GLOBAL,
            hot_reload=True,
            redaction=SettingRedaction.NONE,
            requires_approval=False,
            max_length=120,
        ),
        _definition(
            f"brand_{variant}",
            "icon_asset_id",
            SettingKind.UUID,
            default="",
            permission=SettingPermission.ADMINISTRATOR,
            scope=SettingScope.GLOBAL,
            hot_reload=True,
            redaction=SettingRedaction.NONE,
            requires_approval=False,
            max_length=36,
        ),
    )
)
_DEFINITIONS = (*_DEFINITIONS, *_BRAND_DEFINITIONS)

SETTINGS_REGISTRY: Final[dict[str, SettingDefinition]] = {
    definition.full_key: definition for definition in _DEFINITIONS
}

_TRUE_VALUES: Final = frozenset({"1", "true", "yes", "on", "enabled"})
_FALSE_VALUES: Final = frozenset({"0", "false", "no", "off", "disabled"})
_EMAIL_RE: Final = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_HEX_COLOR_RE: Final = re.compile(r"^#[0-9a-fA-F]{6}$")


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
            # `value` is the raw stored payload; the integer branch is the only
            # place that accepts it, and a non-integral object must be a
            # validation error rather than a TypeError escaping to the caller.
            parsed = int(str(value)) if not isinstance(value, (int, float)) else int(value)
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
    if definition.section in {"footer", "footer_external", "footer_internal"}:
        try:
            return validate_footer_setting(key, string_value)
        except FooterContentValidationError as exc:
            raise SettingValidationError(
                f"Setting '{definition.full_key}' is invalid: {exc}"
            ) from exc
    if definition.section in {"header", "header_external", "header_internal"}:
        try:
            return validate_header_setting(key, string_value)
        except HeaderContentValidationError as exc:
            raise SettingValidationError(
                f"Setting '{definition.full_key}' is invalid: {exc}"
            ) from exc
    if section in {"brand_external", "brand_internal"} and key in {"name_zh", "name_en"}:
        string_value = string_value.strip()
        if not string_value or "<" in string_value or ">" in string_value:
            raise SettingValidationError(
                f"Setting '{definition.full_key}' must be non-empty plain text"
            )
    if definition.kind is SettingKind.ENUM:
        if string_value not in definition.allowed_values:
            raise SettingValidationError(
                f"Setting '{definition.full_key}' must be one of: "
                + ", ".join(sorted(definition.allowed_values))
            )
    elif definition.kind is SettingKind.COLOR:
        if not _HEX_COLOR_RE.fullmatch(string_value):
            raise SettingValidationError(
                f"Setting '{definition.full_key}' must be a 6-digit hexadecimal color"
            )
        return string_value.lower()
    elif definition.kind is SettingKind.EMAIL:
        if not _EMAIL_RE.fullmatch(string_value):
            raise SettingValidationError(
                f"Setting '{definition.full_key}' must be a valid email address"
            )
    elif definition.kind is SettingKind.UUID:
        if string_value:
            try:
                string_value = str(uuid.UUID(string_value))
            except ValueError as exc:
                raise SettingValidationError(
                    f"Setting '{definition.full_key}' must be a UUID or empty"
                ) from exc
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
