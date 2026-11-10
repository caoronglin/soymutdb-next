"""Focused validation tests for the editable footer contract."""

from __future__ import annotations

import json

import pytest

from app.core.footer_content import (
    DEFAULT_FOOTER_NAVIGATION,
    DEFAULT_FOOTER_NAVIGATION_JSON,
    MAX_FOOTER_NAVIGATION_BYTES,
    FooterContentValidationError,
    canonicalize_footer_navigation,
    parse_footer_navigation,
    validate_footer_setting,
    visible_footer_navigation,
)


def _link(
    link_id: str = "genes",
    *,
    target: str = "internal",
    href: str = "/genes",
    order: int = 0,
    label_en: str = "Genes",
    label_zh: str = "基因",
) -> dict[str, object]:
    return {
        "id": link_id,
        "label_en": label_en,
        "label_zh": label_zh,
        "target": target,
        "href": href,
        "enabled": True,
        "order": order,
    }


def _group(
    group_id: str = "explore",
    *,
    order: int = 0,
    links: list[dict[str, object]] | None = None,
    title_en: str = "Explore",
    title_zh: str = "浏览",
) -> dict[str, object]:
    return {
        "id": group_id,
        "title_en": title_en,
        "title_zh": title_zh,
        "enabled": True,
        "order": order,
        "links": links if links is not None else [_link()],
    }


def _json(*groups: dict[str, object], schema_version: object = 1) -> str:
    return json.dumps({"schema_version": schema_version, "groups": list(groups)})


def test_default_navigation_matches_the_active_header_snapshot() -> None:
    groups = DEFAULT_FOOTER_NAVIGATION.groups
    assert [group.id for group in groups] == ["explore", "tools", "downloads", "resources"]
    # 19, not 20: the default footer no longer advertises `/analyses`, because
    # the public portal stopped shipping that route.
    assert len([link for group in groups for link in group.links]) == 19
    assert all(link.target == "internal" for group in groups for link in group.links)
    assert any(link.href == "/tools/seqfetch" for group in groups for link in group.links)
    assert parse_footer_navigation(DEFAULT_FOOTER_NAVIGATION_JSON) == DEFAULT_FOOTER_NAVIGATION


def test_navigation_canonicalization_sorts_by_order_then_stable_id() -> None:
    value = _json(
        _group(
            "z-tools",
            order=1,
            links=[_link("z-link", order=2), _link("a-link", order=2)],
        ),
        _group("a-explore", order=1),
    )

    canonical = canonicalize_footer_navigation(value)
    parsed = parse_footer_navigation(canonical)

    assert [group.id for group in parsed.groups] == ["a-explore", "z-tools"]
    assert [link.id for link in parsed.groups[1].links] == ["a-link", "z-link"]
    assert canonicalize_footer_navigation(canonical) == canonical


def test_public_navigation_omits_disabled_groups_and_links() -> None:
    hidden_group = {**_group("hidden", order=1), "enabled": False}
    visible_group = _group(
        "visible",
        order=0,
        links=[
            {**_link("disabled", order=0), "enabled": False},
            _link("visible-link", order=1),
        ],
    )

    visible = visible_footer_navigation(
        parse_footer_navigation(_json(visible_group, hidden_group))
    )

    assert [group.id for group in visible] == ["visible"]
    assert [link.id for link in visible[0].links] == ["visible-link"]


@pytest.mark.parametrize(
    "value",
    [
        _json(_group(), schema_version=2),
        json.dumps({"schema_version": 1, "groups": [], "unexpected": True}),
        _json(_group("duplicate"), _group("duplicate", order=1)),
        _json(
            _group(
                links=[_link("duplicate"), _link("duplicate", order=1)],
            )
        ),
        json.dumps(
            {
                "schema_version": 1,
                "groups": [
                    {
                        **_group(),
                        "links": [{**_link(), "unexpected": "value"}],
                    }
                ],
            }
        ),
        '{"schema_version":1,"schema_version":1,"groups":[]}',
    ],
)
def test_navigation_rejects_invalid_versions_unknown_fields_and_duplicate_ids(value: str) -> None:
    with pytest.raises(FooterContentValidationError):
        parse_footer_navigation(value)


def test_navigation_rejects_group_link_label_and_serialized_size_overflows() -> None:
    too_many_groups = [_group(f"group-{index}", order=index) for index in range(7)]
    too_many_links = [
        _link(f"link-{index}", order=index)
        for index in range(33)
    ]

    with pytest.raises(FooterContentValidationError):
        parse_footer_navigation(_json(*too_many_groups))
    with pytest.raises(FooterContentValidationError):
        parse_footer_navigation(_json(_group(links=too_many_links)))
    with pytest.raises(FooterContentValidationError):
        parse_footer_navigation(_json(_group(links=[_link(label_en="x" * 81)])))
    with pytest.raises(FooterContentValidationError):
        parse_footer_navigation(_json(_group(links=[_link(href="/" + "x" * 2048)])))
    with pytest.raises(FooterContentValidationError):
        parse_footer_navigation(" " * (MAX_FOOTER_NAVIGATION_BYTES + 1))


def test_serialized_navigation_limit_counts_utf8_bytes() -> None:
    links = []
    for index in range(32):
        if index < 10:
            links.append(
                _link(f"link-{index}", href="/" + "x" * 2047, order=index)
            )
        else:
            links.append(
                _link(
                    f"link-{index}",
                    order=index,
                    label_en="链" * 80,
                    label_zh="路" * 80,
                )
            )
    value = json.dumps(
        {"schema_version": 1, "groups": [_group(links=links)]},
        ensure_ascii=False,
    )

    assert len(value) < MAX_FOOTER_NAVIGATION_BYTES
    assert len(value.encode("utf-8")) > MAX_FOOTER_NAVIGATION_BYTES
    with pytest.raises(FooterContentValidationError):
        parse_footer_navigation(value)


@pytest.mark.parametrize(
    ("target", "href"),
    [
        ("internal", "//evil.example/path"),
        ("internal", "/\\\\evil.example/path"),
        ("internal", "/bad%escape"),
        ("external", "http://example.com"),
        ("external", "javascript:alert(1)"),
        ("external", "data:text/html,unsafe"),
        ("external", "//example.com/path"),
        ("external", "https://user:pass@example.com/path"),
        ("external", "https://example.com/%GG"),
        ("external", "https://[invalid"),
    ],
)
def test_navigation_rejects_unsafe_or_malformed_destinations(target: str, href: str) -> None:
    with pytest.raises(FooterContentValidationError):
        parse_footer_navigation(_json(_group(links=[_link(target=target, href=href)])))


def test_optional_email_and_phone_values_are_validated_without_rewriting_display_text() -> None:
    assert validate_footer_setting("contact_email_value", "") == ""
    assert validate_footer_setting("contact_email_value", "help@example.org") == "help@example.org"
    phone = "+86 (025)-84391957"
    assert validate_footer_setting("contact_phone_value", phone) == phone

    with pytest.raises(FooterContentValidationError):
        validate_footer_setting("contact_email_value", "not-an-email")
    with pytest.raises(FooterContentValidationError):
        validate_footer_setting("contact_phone_value", "025-84391957<script>")
