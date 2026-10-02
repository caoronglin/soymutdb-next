"""Typed, server-owned runtime setting registry contracts."""

from __future__ import annotations

from dataclasses import MISSING, fields
from inspect import Parameter, signature

import pytest


def test_registry_definitions_require_complete_operational_metadata() -> None:
    from app.core.settings_registry import (
        SETTINGS_REGISTRY,
        SettingDefinition,
        SettingKind,
        SettingPermission,
        SettingRedaction,
        SettingScope,
        _definition,
        validate_setting_update,
    )

    metadata_names = {
        "default",
        "permission",
        "scope",
        "hot_reload",
        "redaction",
        "requires_approval",
    }
    definition_fields = {field.name: field for field in fields(SettingDefinition)}
    helper_parameters = signature(_definition).parameters

    assert metadata_names <= definition_fields.keys()
    for name in metadata_names:
        assert definition_fields[name].default is MISSING
        assert definition_fields[name].default_factory is MISSING
        assert helper_parameters[name].default is Parameter.empty

    for definition in SETTINGS_REGISTRY.values():
        assert isinstance(definition.permission, SettingPermission)
        assert isinstance(definition.scope, SettingScope)
        assert isinstance(definition.hot_reload, bool)
        assert isinstance(definition.redaction, SettingRedaction)
        assert isinstance(definition.requires_approval, bool)
        if definition.kind is SettingKind.SECRET:
            assert definition.default is None
            assert definition.redaction is SettingRedaction.OMIT
        else:
            assert definition.redaction is SettingRedaction.NONE
            validate_setting_update(
                definition.section,
                definition.key,
                definition.default,
            )


def test_registry_contains_only_bounded_safe_product_defaults() -> None:
    from app.core.settings_registry import (
        SETTINGS_REGISTRY,
        SettingKind,
        SettingRedaction,
    )

    expected_enum_defaults = {
        "navigation.defaultSource": (
            "published",
            frozenset({"published", "immutable_fallback"}),
        ),
        "seo.defaultIndexingPolicy": (
            "noindex",
            frozenset({"noindex", "published_only"}),
        ),
        "geo.defaultCrawlerPolicy": (
            "deny",
            frozenset({"deny", "retrieval_only", "retrieval_and_training"}),
        ),
        "motion.defaultIntensity": (
            "auto",
            frozenset({"auto", "standard", "minimal", "off"}),
        ),
        "imports.defaultTemplateModule": ("genes", frozenset({"genes"})),
        "imports.defaultTemplateFormat": (
            "tsv",
            frozenset({"tsv", "csv", "xlsx"}),
        ),
        "page_layout.defaultTheme": (
            "scientific-light",
            frozenset(
                {
                    "scientific-light",
                    "scientific-dark",
                    "high-contrast",
                    "compact-data",
                    "print",
                }
            ),
        ),
    }

    for full_key, (default, allowed_values) in expected_enum_defaults.items():
        definition = SETTINGS_REGISTRY[full_key]
        assert definition.kind is SettingKind.ENUM
        assert definition.default == default
        assert definition.allowed_values == allowed_values
        assert definition.redaction is SettingRedaction.NONE

    for definition in SETTINGS_REGISTRY.values():
        if definition.kind is SettingKind.SECRET:
            continue
        normalized_key = definition.full_key.lower()
        # These are bounded, public BLAST form labels ("Reference sequence
        # type"), not connection settings. Variant-prefixed copies are safe
        # for the same reason.
        if normalized_key.endswith(("blast.database", "blast.databaseplaceholder")):
            continue
        assert not any(
            forbidden in normalized_key
            for forbidden in ("database", "dsn", "jwt", "token", "digest", "topology")
        )


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("navigation", "defaultSource", "remote_url"),
        ("seo", "defaultIndexingPolicy", "index_everything"),
        ("geo", "defaultCrawlerPolicy", "arbitrary_agent_rules"),
        ("motion", "defaultIntensity", "cinematic"),
        ("imports", "defaultTemplateModule", "../../custom"),
        ("imports", "defaultTemplateFormat", "executable"),
        ("page_layout", "defaultTheme", "custom-template"),
    ],
)
def test_safe_product_defaults_reject_unregistered_values(
    section: str,
    key: str,
    value: str,
) -> None:
    from app.core.settings_registry import SettingValidationError, validate_setting_update

    with pytest.raises(SettingValidationError, match="must be one of"):
        validate_setting_update(section, key, value)


def test_registry_serializes_known_values_to_canonical_storage_strings() -> None:
    from app.core.settings_registry import SettingValidationError, validate_setting_update

    assert validate_setting_update("data", "maxExportRecords", 2500) == "2500"
    assert validate_setting_update("data", "enableClickhouse", "OFF") == "false"
    assert validate_setting_update("general", "defaultLanguage", "zh") == "zh"
    assert validate_setting_update("general", "primaryColor", "#ABCDEF") == "#abcdef"

    with pytest.raises(SettingValidationError, match="hexadecimal color"):
        validate_setting_update("general", "primaryColor", "#12ab")


def test_registry_rejects_unknown_keys() -> None:
    from app.core.settings_registry import SettingValidationError, validate_setting_update

    with pytest.raises(SettingValidationError, match="Unknown setting"):
        validate_setting_update("general", "arbitraryRuntimeCode", "enabled")


def test_registry_rejects_plaintext_secret_settings() -> None:
    from app.core.settings_registry import SettingValidationError, validate_setting_update

    with pytest.raises(SettingValidationError, match="deployment secret"):
        validate_setting_update("email", "smtpPassword", "plain-text-secret")


def test_registry_rejects_urls_outside_the_definition_allowlist() -> None:
    from app.core.settings_registry import SettingValidationError, validate_setting_update

    assert (
        validate_setting_update("cdn", "url", "https://cdn.example.com/assets/")
        == "https://cdn.example.com/assets/"
    )
    with pytest.raises(SettingValidationError, match="allowlist"):
        validate_setting_update("cdn", "url", "https://evil.example/assets/")


@pytest.mark.parametrize("value", [True, "0", "enabled", "false"])
def test_registry_boolean_parser_accepts_only_explicit_boolean_vocabulary(value: object) -> None:
    from app.core.settings_registry import validate_setting_update

    assert validate_setting_update("features", "registration", value) in {"true", "false"}


def test_registry_rejects_ambiguous_boolean_values() -> None:
    from app.core.settings_registry import SettingValidationError, validate_setting_update

    with pytest.raises(SettingValidationError, match="boolean"):
        validate_setting_update("features", "registration", "sometimes")


def test_site_variant_settings_are_isolated_and_share_validation() -> None:
    from app.core.settings_registry import (
        SETTINGS_REGISTRY,
        SettingValidationError,
        validate_setting_update,
    )

    external = SETTINGS_REGISTRY["content_external.hero.title"]
    internal = SETTINGS_REGISTRY["content_internal.hero.title"]
    assert external.section == "content_external"
    assert internal.section == "content_internal"
    assert external.default != internal.default
    assert (
        validate_setting_update("content_external", "hero.title", "Public")
        == "Public"
    )
    assert (
        validate_setting_update("content_internal", "hero.title", "Private")
        == "Private"
    )

    with pytest.raises(SettingValidationError, match="Unknown setting"):
        validate_setting_update("content_internal", "not_registered", "value")


def test_footer_settings_are_registered_per_variant_and_use_domain_validation() -> None:
    from app.core.footer_content import DEFAULT_FOOTER_NAVIGATION_JSON
    from app.core.settings_registry import (
        SETTINGS_REGISTRY,
        SettingValidationError,
        registered_keys_for_section,
        validate_setting_update,
    )

    expected = {
        "contact_person_en",
        "contact_person_zh",
        "contact_phone_value",
        "contact_email_value",
        "address_en",
        "address_zh",
        "copyright_en",
        "copyright_zh",
        "navigation_json",
    }
    for section in ("footer_external", "footer_internal"):
        assert expected <= registered_keys_for_section(section)
        assert SETTINGS_REGISTRY[f"{section}.navigation_json"].default == (
            DEFAULT_FOOTER_NAVIGATION_JSON
        )
        assert validate_setting_update(section, "contact_phone_value", "") == ""
        assert validate_setting_update(section, "contact_email_value", "help@example.org") == (
            "help@example.org"
        )
        with pytest.raises(SettingValidationError, match="valid email"):
            validate_setting_update(section, "contact_email_value", "invalid")
        with pytest.raises(SettingValidationError, match="navigation is invalid"):
            validate_setting_update(section, "navigation_json", '{"schema_version":2,"groups":[]}')
