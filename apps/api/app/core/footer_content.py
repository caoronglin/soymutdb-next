"""Domain schema and validation for the editable public-site footer.

The versioned settings registry remains the write/persistence owner. This module
owns only the footer-specific JSON shape, defaults, canonicalization, and safety
checks so the generic settings registry does not accumulate domain logic.
"""

from __future__ import annotations

import json
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

MAX_FOOTER_NAVIGATION_BYTES = 32 * 1024
MAX_FOOTER_GROUPS = 6
MAX_FOOTER_LINKS = 32
MAX_FOOTER_LABEL_LENGTH = 80
MAX_FOOTER_DESTINATION_LENGTH = 2048

_SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9 ().-]{0,30}$")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")


def _reject_duplicate_object_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _validate_label(value: str) -> str:
    if not value.strip():
        raise ValueError("navigation labels and titles must not be blank")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("navigation labels and titles cannot contain control characters")
    return value


class FooterContentValidationError(ValueError):
    """A footer setting is malformed or outside its bounded contract."""


def _validate_destination(target: str, href: str) -> None:
    if (
        not href
        or href != href.strip()
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in href
        )
        or "\\" in href
        or _INVALID_PERCENT_ESCAPE.search(href)
    ):
        raise ValueError("destination contains whitespace, controls, or a backslash")

    try:
        parsed = urlsplit(href)
        hostname = parsed.hostname
        # Accessing .port also rejects malformed numeric ports.
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("destination is malformed") from exc

    if target == "internal":
        if (
            not href.startswith("/")
            or href.startswith("//")
            or parsed.scheme
            or parsed.netloc
        ):
            raise ValueError("internal destinations must be origin-relative paths")
        return

    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("external destinations must be HTTPS URLs without credentials")


class FooterNavigationLink(BaseModel):
    """One editable, bilingual footer destination."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, pattern=_SLUG_PATTERN)
    label_en: str = Field(min_length=1, max_length=MAX_FOOTER_LABEL_LENGTH)
    label_zh: str = Field(min_length=1, max_length=MAX_FOOTER_LABEL_LENGTH)
    target: Literal["internal", "external"]
    href: str = Field(min_length=1, max_length=MAX_FOOTER_DESTINATION_LENGTH)
    enabled: bool
    order: int = Field(ge=0)

    @model_validator(mode="after")
    def labels_are_plain_text(self) -> FooterNavigationLink:
        _validate_label(self.label_en)
        _validate_label(self.label_zh)
        return self

    @model_validator(mode="after")
    def destination_matches_target(self) -> FooterNavigationLink:
        try:
            _validate_destination(self.target, self.href)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return self


class FooterNavigationGroup(BaseModel):
    """A bilingual group of footer links."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, pattern=_SLUG_PATTERN)
    title_en: str = Field(min_length=1, max_length=MAX_FOOTER_LABEL_LENGTH)
    title_zh: str = Field(min_length=1, max_length=MAX_FOOTER_LABEL_LENGTH)
    enabled: bool
    order: int = Field(ge=0)
    links: list[FooterNavigationLink] = Field(max_length=MAX_FOOTER_LINKS)

    @model_validator(mode="after")
    def titles_are_plain_text(self) -> FooterNavigationGroup:
        _validate_label(self.title_en)
        _validate_label(self.title_zh)
        return self

    @model_validator(mode="after")
    def links_have_unique_ids(self) -> FooterNavigationGroup:
        link_ids = [link.id for link in self.links]
        if len(link_ids) != len(set(link_ids)):
            raise ValueError("link IDs must be unique within a group")
        return self


class FooterNavigationDocument(BaseModel):
    """Versioned persisted footer navigation configuration."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    groups: list[FooterNavigationGroup] = Field(max_length=MAX_FOOTER_GROUPS)

    @model_validator(mode="after")
    def document_has_unique_bounded_groups(self) -> FooterNavigationDocument:
        group_ids = [group.id for group in self.groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("group IDs must be unique")
        if sum(len(group.links) for group in self.groups) > MAX_FOOTER_LINKS:
            raise ValueError(f"footer navigation supports at most {MAX_FOOTER_LINKS} links")
        return self


def _sort_navigation(document: FooterNavigationDocument) -> FooterNavigationDocument:
    groups = [
        group.model_copy(
            update={"links": sorted(group.links, key=lambda link: (link.order, link.id))}
        )
        for group in document.groups
    ]
    return document.model_copy(
        update={"groups": sorted(groups, key=lambda group: (group.order, group.id))}
    )


def _serialize_navigation(document: FooterNavigationDocument) -> str:
    ordered = _sort_navigation(document)
    return json.dumps(
        ordered.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def parse_footer_navigation(value: str) -> FooterNavigationDocument:
    """Parse and validate stored JSON, returning stable ordered groups."""
    if not isinstance(value, str):
        raise FooterContentValidationError("footer navigation must be a JSON string")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise FooterContentValidationError("footer navigation is not valid UTF-8") from exc
    if len(encoded) > MAX_FOOTER_NAVIGATION_BYTES:
        raise FooterContentValidationError(
            f"footer navigation exceeds {MAX_FOOTER_NAVIGATION_BYTES} bytes"
        )
    try:
        payload = json.loads(value, object_pairs_hook=_reject_duplicate_object_keys)
        document = FooterNavigationDocument.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        raise FooterContentValidationError("footer navigation is invalid") from exc
    return _sort_navigation(document)


def canonicalize_footer_navigation(value: str) -> str:
    """Validate and serialize the navigation JSON into a stable bounded form."""
    canonical = _serialize_navigation(parse_footer_navigation(value))
    if len(canonical.encode("utf-8")) > MAX_FOOTER_NAVIGATION_BYTES:
        raise FooterContentValidationError(
            f"footer navigation exceeds {MAX_FOOTER_NAVIGATION_BYTES} bytes"
        )
    return canonical


def visible_footer_navigation(
    document: FooterNavigationDocument,
) -> list[FooterNavigationGroup]:
    """Return only enabled groups and links, preserving deterministic order."""
    visible_groups: list[FooterNavigationGroup] = []
    for group in _sort_navigation(document).groups:
        if not group.enabled:
            continue
        links = [link for link in group.links if link.enabled]
        if links:
            visible_groups.append(
                group.model_copy(update={"links": links})
            )
    return visible_groups


def _default_link(
    link_id: str,
    label_en: str,
    label_zh: str,
    href: str,
    order: int,
) -> FooterNavigationLink:
    return FooterNavigationLink(
        id=link_id,
        label_en=label_en,
        label_zh=label_zh,
        target="internal",
        href=href,
        enabled=True,
        order=order,
    )


def _default_group(
    group_id: str,
    title_en: str,
    title_zh: str,
    links: list[FooterNavigationLink],
    order: int,
) -> FooterNavigationGroup:
    return FooterNavigationGroup(
        id=group_id,
        title_en=title_en,
        title_zh=title_zh,
        enabled=True,
        order=order,
        links=links,
    )


DEFAULT_FOOTER_NAVIGATION = FooterNavigationDocument(
    schema_version=1,
    groups=[
        _default_group(
            "explore",
            "Explore",
            "浏览",
            [
                _default_link("genes", "Genes", "基因", "/genes", 0),
                _default_link("variants", "Variants", "变异", "/variants", 1),
                _default_link("mutants", "Mutant Lines", "突变系", "/mutants", 2),
                _default_link("browser", "Genome Browser", "基因组浏览器", "/browser", 3),
                _default_link("sra", "SRA Browser", "SRA 浏览器", "/sra", 4),
                _default_link("compare", "Compare", "变异比较", "/compare", 5),
                _default_link("analytics", "Analytics", "数据分析", "/analytics", 6),
            ],
            0,
        ),
        _default_group(
            "tools",
            "Tools",
            "工具",
            [
                _default_link("blast", "BLAST", "BLAST", "/blast", 0),
                _default_link("seqfetch", "Sequence Fetch", "序列获取", "/tools/seqfetch", 2),
                _default_link(
                    "enrichment",
                    "GO / KEGG Enrichment",
                    "GO / KEGG 富集",
                    "/tools/enrichment",
                    3,
                ),
                _default_link(
                    "exppattern",
                    "Expression Pattern",
                    "表达模式",
                    "/tools/exppattern",
                    4,
                ),
                _default_link("all-tools", "All tools", "全部工具", "/tools", 5),
            ],
            1,
        ),
        _default_group(
            "downloads",
            "Downloads",
            "下载",
            [_default_link("downloads", "Downloads", "下载", "/downloads", 0)],
            2,
        ),
        _default_group(
            "resources",
            "Resources",
            "资源",
            [
                _default_link("guide", "Guide", "操作指南", "/guide", 0),
                _default_link("help", "Help", "帮助", "/help", 1),
                _default_link("news", "News", "新闻", "/news", 2),
                _default_link("publications", "Publications", "文献", "/publications", 3),
                _default_link("seed-request", "Seed Request", "种子申请", "/seed-request", 4),
                _default_link("about", "About", "关于我们", "/about", 5),
            ],
            3,
        ),
    ],
)
DEFAULT_FOOTER_NAVIGATION_JSON = _serialize_navigation(DEFAULT_FOOTER_NAVIGATION)


def validate_footer_setting(key: str, value: str) -> str:
    """Apply the additional contract for registered footer-only string keys."""
    if key == "navigation_json":
        return canonicalize_footer_navigation(value)
    if key == "contact_email_value" and value and not _EMAIL_PATTERN.fullmatch(value):
        raise FooterContentValidationError("contact email must be a valid email address")
    if key == "contact_phone_value" and value and not _PHONE_PATTERN.fullmatch(value):
        raise FooterContentValidationError("contact phone contains unsupported characters")
    return value


__all__ = [
    "DEFAULT_FOOTER_NAVIGATION",
    "DEFAULT_FOOTER_NAVIGATION_JSON",
    "FooterContentValidationError",
    "FooterNavigationDocument",
    "FooterNavigationGroup",
    "FooterNavigationLink",
    "MAX_FOOTER_DESTINATION_LENGTH",
    "MAX_FOOTER_GROUPS",
    "MAX_FOOTER_LABEL_LENGTH",
    "MAX_FOOTER_LINKS",
    "MAX_FOOTER_NAVIGATION_BYTES",
    "canonicalize_footer_navigation",
    "parse_footer_navigation",
    "validate_footer_setting",
    "visible_footer_navigation",
]
