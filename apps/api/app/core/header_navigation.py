"""Domain schema and validation for the editable public-site header navigation.

Mirrors the footer contract: the settings registry owns persistence and the
versioned write path, while this module owns the bounded bilingual document,
defaults, canonicalization, and feature-gating rules.

Each link may reference a server-owned feature flag (``feature``). A link whose
flag is disabled, missing, or unknown is never served, so turning a feature off
in Admin removes its navigation entry as well as its API surface.
"""

from __future__ import annotations

import json
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .features import FEATURES

MAX_HEADER_NAVIGATION_BYTES = 64 * 1024
MAX_HEADER_GROUPS = 8
MAX_HEADER_LINKS = 48
MAX_HEADER_LABEL_LENGTH = 80
MAX_HEADER_DESTINATION_LENGTH = 2048

_SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_FEATURE_PATTERN = r"^[a-z][a-z0-9_.-]*$"
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


class HeaderContentValidationError(ValueError):
    """A header navigation setting is malformed or outside its contract."""


class HeaderNavigationLink(BaseModel):
    """One editable, bilingual primary-navigation destination."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, pattern=_SLUG_PATTERN)
    label_en: str = Field(min_length=1, max_length=MAX_HEADER_LABEL_LENGTH)
    label_zh: str = Field(min_length=1, max_length=MAX_HEADER_LABEL_LENGTH)
    target: Literal["internal", "external"]
    href: str = Field(min_length=1, max_length=MAX_HEADER_DESTINATION_LENGTH)
    enabled: bool
    order: int = Field(ge=0)
    #: Optional server-owned feature flag gating this entry.
    feature: str | None = Field(default=None, pattern=_FEATURE_PATTERN)

    @model_validator(mode="after")
    def labels_are_plain_text(self) -> HeaderNavigationLink:
        _validate_label(self.label_en)
        _validate_label(self.label_zh)
        try:
            _validate_destination(self.target, self.href)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return self


class HeaderNavigationGroup(BaseModel):
    """A bilingual group rendered as one dropdown (or direct link)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, pattern=_SLUG_PATTERN)
    title_en: str = Field(min_length=1, max_length=MAX_HEADER_LABEL_LENGTH)
    title_zh: str = Field(min_length=1, max_length=MAX_HEADER_LABEL_LENGTH)
    enabled: bool
    order: int = Field(ge=0)
    links: list[HeaderNavigationLink] = Field(max_length=MAX_HEADER_LINKS)

    @model_validator(mode="after")
    def titles_are_plain_text(self) -> HeaderNavigationGroup:
        _validate_label(self.title_en)
        _validate_label(self.title_zh)
        return self

    @model_validator(mode="after")
    def links_have_unique_ids(self) -> HeaderNavigationGroup:
        link_ids = [link.id for link in self.links]
        if len(link_ids) != len(set(link_ids)):
            raise ValueError("link IDs must be unique within a group")
        return self


class HeaderNavigationDocument(BaseModel):
    """Versioned persisted header navigation configuration."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    groups: list[HeaderNavigationGroup] = Field(max_length=MAX_HEADER_GROUPS)

    @model_validator(mode="after")
    def document_has_unique_bounded_groups(self) -> HeaderNavigationDocument:
        group_ids = [group.id for group in self.groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("group IDs must be unique")
        if sum(len(group.links) for group in self.groups) > MAX_HEADER_LINKS:
            raise ValueError(f"header navigation supports at most {MAX_HEADER_LINKS} links")
        return self


def _sort_navigation(document: HeaderNavigationDocument) -> HeaderNavigationDocument:
    groups = [
        group.model_copy(
            update={"links": sorted(group.links, key=lambda link: (link.order, link.id))}
        )
        for group in document.groups
    ]
    return document.model_copy(
        update={"groups": sorted(groups, key=lambda group: (group.order, group.id))}
    )


def _serialize_navigation(document: HeaderNavigationDocument) -> str:
    ordered = _sort_navigation(document)
    return json.dumps(
        ordered.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def parse_header_navigation(value: str) -> HeaderNavigationDocument:
    """Parse and validate stored JSON, returning stable ordered groups."""
    if not isinstance(value, str):
        raise HeaderContentValidationError("header navigation must be a JSON string")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise HeaderContentValidationError("header navigation is not valid UTF-8") from exc
    if len(encoded) > MAX_HEADER_NAVIGATION_BYTES:
        raise HeaderContentValidationError(
            f"header navigation exceeds {MAX_HEADER_NAVIGATION_BYTES} bytes"
        )
    try:
        payload = json.loads(value, object_pairs_hook=_reject_duplicate_object_keys)
        document = HeaderNavigationDocument.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        raise HeaderContentValidationError("header navigation is invalid") from exc
    return _sort_navigation(document)


def canonicalize_header_navigation(value: str) -> str:
    """Validate and serialize the navigation JSON into a stable bounded form."""
    canonical = _serialize_navigation(parse_header_navigation(value))
    if len(canonical.encode("utf-8")) > MAX_HEADER_NAVIGATION_BYTES:
        raise HeaderContentValidationError(
            f"header navigation exceeds {MAX_HEADER_NAVIGATION_BYTES} bytes"
        )
    return canonical


def visible_header_navigation(
    document: HeaderNavigationDocument,
    enabled_features: set[str] | frozenset[str] | None = None,
) -> list[HeaderNavigationGroup]:
    """Return enabled groups and links whose feature gate is open.

    A link without a ``feature`` is always served. A link referencing an
    unknown or disabled flag is dropped rather than shown broken.
    """
    features = FEATURES.keys() if enabled_features is None else enabled_features
    visible_groups: list[HeaderNavigationGroup] = []
    for group in _sort_navigation(document).groups:
        if not group.enabled:
            continue
        links = [
            link
            for link in group.links
            if link.enabled and (link.feature is None or link.feature in features)
        ]
        if links:
            visible_groups.append(group.model_copy(update={"links": links}))
    return visible_groups


def _default_link(
    link_id: str,
    label_en: str,
    label_zh: str,
    href: str,
    order: int,
) -> HeaderNavigationLink:
    return HeaderNavigationLink(
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
    links: list[HeaderNavigationLink],
    order: int,
) -> HeaderNavigationGroup:
    return HeaderNavigationGroup(
        id=group_id,
        title_en=title_en,
        title_zh=title_zh,
        enabled=True,
        order=order,
        links=links,
    )


DEFAULT_HEADER_NAVIGATION = HeaderNavigationDocument(
    schema_version=1,
    groups=[
        _default_group(
            "search",
            "Search",
            "检索",
            [
                _default_link("genes", "Genes", "基因", "/search/genes", 0),
                _default_link("location", "Physical Location", "物理位置", "/search/location", 1),
                _default_link("jbrowse", "Genome Browser", "基因组浏览器", "/search/gbrowse", 2),
                _default_link("blast", "BLAST", "BLAST", "/blast", 3),
            ],
            0,
        ),
        _default_group(
            "tools",
            "Tools",
            "工具",
            [
                _default_link("blast-tool", "BLAST", "BLAST", "/blast", 0),
                _default_link("comparative", "Comparative", "比较基因组", "/comparative", 1),
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
                    5,
                ),
                _default_link("expression", "Expression", "表达谱", "/expression", 6),
                _default_link("phenotypes", "Phenotypes", "表型", "/phenotypes", 7),
                _default_link("all-tools", "All tools", "全部工具", "/tools", 8),
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
DEFAULT_HEADER_NAVIGATION_JSON = _serialize_navigation(DEFAULT_HEADER_NAVIGATION)


def validate_header_setting(key: str, value: str) -> str:
    """Apply the additional contract for registered header-only string keys."""
    if key == "navigation_json":
        return canonicalize_header_navigation(value)
    return value


__all__ = [
    "DEFAULT_HEADER_NAVIGATION",
    "DEFAULT_HEADER_NAVIGATION_JSON",
    "HeaderContentValidationError",
    "HeaderNavigationDocument",
    "HeaderNavigationGroup",
    "HeaderNavigationLink",
    "MAX_HEADER_DESTINATION_LENGTH",
    "MAX_HEADER_GROUPS",
    "MAX_HEADER_LABEL_LENGTH",
    "MAX_HEADER_LINKS",
    "MAX_HEADER_NAVIGATION_BYTES",
    "canonicalize_header_navigation",
    "parse_header_navigation",
    "validate_header_setting",
    "visible_header_navigation",
]
