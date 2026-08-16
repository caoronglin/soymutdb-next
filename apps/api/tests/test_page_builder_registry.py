"""Tests for the safe component registry (Page Builder).

No database required — these exercise :func:`app.page_builder.registry.validate_definition`
and :func:`app.page_builder.registry.validate_route` directly.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ValidationError
from app.page_builder.registry import (
    COMPONENT_REGISTRY,
    validate_definition,
    validate_route,
)

# ---------------------------------------------------------------------------
# Component allowlist
# ---------------------------------------------------------------------------


def test_registry_contains_the_approved_component_types():
    # The plan enumerates these specific types (the "16" figure is a typo; the
    # concrete allowlist below has 17 entries).
    expected = {
        "navigation",
        "news_list",
        "media_carousel",
        "rich_text",
        "tool_entries",
        "assembly_select",
        "gene_search_form",
        "location_search_form",
        "data_table",
        "button",
        "link",
        "notice",
        "divider",
        "tabs",
        "columns",
        "jbrowse_launcher",
        "blast_launcher",
    }
    assert set(COMPONENT_REGISTRY) == expected


def test_every_entry_has_a_pydantic_config_model():
    from pydantic import BaseModel

    for key, entry in COMPONENT_REGISTRY.items():
        assert entry.renderer_key == key
        assert issubclass(entry.config_model, BaseModel)
        # config schema must be serializable for the Admin property panel
        assert isinstance(entry.config_schema, dict)


def test_reject_unknown_component_type():
    with pytest.raises(ValidationError) as exc:
        validate_definition({"root": {"type": "totally_made_up", "props": {}}})
    assert "unknown component type" in str(exc.value).lower()


def test_reject_unknown_props():
    with pytest.raises(ValidationError):
        validate_definition(
            {
                "root": {
                    "type": "rich_text",
                    "props": {"content": "", "on_this_unknown": 1},
                }
            }
        )


def test_reject_javascript_url():
    with pytest.raises(ValidationError):
        validate_definition(
            {
                "root": {
                    "type": "link",
                    "props": {"label": "x", "href": "javascript:alert(1)"},
                }
            }
        )


def test_reject_data_image_svg_uri():
    with pytest.raises(ValidationError):
        validate_definition(
            {
                "root": {
                    "type": "link",
                    "props": {"label": "x", "href": "data:image/svg+xml,<svg/>"},
                }
            }
        )


def test_reject_inline_event_handler():
    # An inline handler smuggled into a plain string prop (a label) is rejected.
    with pytest.raises(ValidationError):
        validate_definition(
            {
                "root": {
                    "type": "button",
                    "props": {"label": '<img onerror="steal()">'},
                }
            }
        )


def test_reject_raw_script_tag():
    # A raw <script> in a plain string prop is rejected outright.
    with pytest.raises(ValidationError):
        validate_definition(
            {
                "root": {
                    "type": "button",
                    "props": {"label": "<script>alert(1)</script>"},
                }
            }
        )


def test_reject_arbitrary_action_name():
    with pytest.raises(ValidationError):
        validate_definition(
            {
                "root": {
                    "type": "button",
                    "props": {"label": "Run", "action": "rm -rf /"},
                }
            }
        )


def test_reject_unapproved_renderer_or_template_path():
    # There is no ``renderer`` or ``template`` prop on any component; trying to
    # smuggle one in must fail fast.
    with pytest.raises(ValidationError):
        validate_definition(
            {
                "root": {
                    "type": "rich_text",
                    "props": {"content": "", "template_path": "/etc/passwd"},
                }
            }
        )


def test_accept_valid_internal_and_http_links():
    out = validate_definition(
        {
            "root": {
                "type": "link",
                "props": {"label": "Docs", "href": "/docs"},
            }
        }
    )
    assert out["root"]["props"]["href"] == "/docs"

    out2 = validate_definition(
        {
            "root": {
                "type": "link",
                "props": {"label": "NCBI", "href": "https://example.com"},
            }
        }
    )
    assert out2["root"]["props"]["href"] == "https://example.com"


def test_rich_text_is_sanitized():
    # rich_text content is passed through the server sanitizer: the <script>
    # tag is stripped (its body is not executed).  Allowed markup survives.
    out = validate_definition(
        {
            "root": {
                "type": "rich_text",
                "props": {
                    "content": '<p>hi<script>alert(1)</script></p><strong>bold</strong>'
                },
            }
        }
    )
    content = out["root"]["props"]["content"]
    assert "<script" not in content
    assert "<p>" in content
    assert "<strong>bold</strong>" in content


def test_approved_actions_and_launchers_pass():
    out = validate_definition(
        {
            "root": {
                "type": "columns",
                "props": {"columns": 2},
                "children": [
                    {
                        "type": "jbrowse_launcher",
                        "props": {"assembly": "Gm01", "track": "genes"},
                    },
                    {
                        "type": "blast_launcher",
                        "props": {"program": "blastn"},
                    },
                ],
            }
        }
    )
    assert out["root"]["type"] == "columns"
    assert len(out["root"]["children"]) == 2


# ---------------------------------------------------------------------------
# Route validation
# ---------------------------------------------------------------------------


def test_reserved_routes_are_rejected():
    for route in ("/blast", "/browser", "/admin", "/api", "/admin/pages", "/blast/configure"):
        with pytest.raises(ValidationError):
            validate_route(route)


def test_valid_route_accepted():
    assert validate_route("/about-us") == "/about-us"
    assert validate_route("/search/genes") == "/search/genes"
    assert validate_route("/latest-news") == "/latest-news"


@pytest.mark.parametrize(
    "bad",
    ["about", "", "UPPER", "/About", "/with space", "/a//b", "/./x", "/-x"],
)
def test_invalid_route_patterns_rejected(bad):
    with pytest.raises(ValidationError):
        validate_route(bad)
