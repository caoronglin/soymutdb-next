"""Versioned plugin manifests, fail-closed status, and public projection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import NotFoundError


def _manifest_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "manifest_version": 1,
        "key": "jbrowse",
        "version": "2.17.0",
        "api_compatibility": {
            "minimum": "2.0.0",
            "maximum_exclusive": "3.0.0",
        },
        "license": "MPL-2.0",
        "config_schema": {
            "type": "object",
            "properties": {
                "base_url": {"type": "string", "format": "uri"},
            },
            "additionalProperties": False,
        },
        "routes": [
            {"method": "GET", "path": "/api/v1/tracks/jbrowse-config"},
        ],
        "task_queues": [],
        "resource_limits": {
            "max_concurrency": 8,
            "memory_mb": 1024,
            "timeout_seconds": 30,
        },
        "healthcheck": {
            "path": "/api/v1/health/ready",
            "interval_seconds": 30,
            "timeout_seconds": 5,
        },
        "enabled": True,
        "configured": True,
        "healthy": True,
        "public_url": "https://genome.example.org/browser/",
        "public_url_allowlist": ["https://genome.example.org"],
        "assemblies": ["GmWm82.a2.v1"],
        "uninstall_semantics": "disable_only",
    }
    values.update(overrides)
    return values


def _manifest(**overrides: object):
    from app.core.plugins import PluginManifest

    values = _manifest_values(**overrides)
    return PluginManifest(**values)


def _registry(manifest=None, *, secret: str = "deployment-signing-secret"):
    from app.core.plugins import PluginRegistry, sign_plugin_manifest

    signed = [] if manifest is None else [sign_plugin_manifest(manifest, secret)]
    return PluginRegistry(signing_key=secret, signed_manifests=signed)


def test_builtin_plugins_fail_closed_without_signed_deployment_manifests() -> None:
    from app.core.plugins import BUILTIN_PLUGINS, PluginRegistry

    assert set(BUILTIN_PLUGINS) == {"jbrowse", "blast", "analyses", "mcp", "ols4"}
    states = PluginRegistry(signing_key=None, signed_manifests=[]).snapshot()
    assert set(states) == set(BUILTIN_PLUGINS)
    assert all(state.installed is False for state in states.values())
    assert all(state.version is None for state in states.values())
    assert all(state.reason == "not_installed" for state in states.values())


def test_only_a_valid_signed_versioned_manifest_marks_plugin_installed() -> None:
    from app.core.plugins import PluginRegistry, sign_plugin_manifest

    manifest = _manifest()
    signed = sign_plugin_manifest(manifest, "right-secret")
    tampered = signed.model_copy(update={"signature": "0" * 64})

    valid = PluginRegistry(
        signing_key="right-secret", signed_manifests=[signed]
    ).status("jbrowse")
    invalid = PluginRegistry(
        signing_key="right-secret", signed_manifests=[tampered]
    ).status("jbrowse")

    assert valid.installed is True
    assert valid.version == "2.17.0"
    assert valid.public_url == "https://genome.example.org/browser/"
    assert invalid.installed is False


def test_manifest_rejects_non_allowlisted_public_url() -> None:
    with pytest.raises(PydanticValidationError, match="allowlist"):
        _manifest(public_url="https://attacker.example/browser/")


@pytest.mark.parametrize(
    "field",
    [
        "api_compatibility",
        "license",
        "config_schema",
        "routes",
        "task_queues",
        "resource_limits",
        "healthcheck",
        "assemblies",
        "uninstall_semantics",
    ],
)
def test_manifest_requires_complete_operational_metadata(field: str) -> None:
    from app.core.plugins import PluginManifest

    values = _manifest_values()
    del values[field]
    with pytest.raises(PydanticValidationError, match=field):
        PluginManifest(**values)


@pytest.mark.parametrize("license_id", ["", "not-a-license", "MIT OR unknown"])
def test_manifest_rejects_invalid_license_identifier(license_id: str) -> None:
    with pytest.raises(PydanticValidationError, match="license"):
        _manifest(license=license_id)


@pytest.mark.parametrize(
    "resource_limits",
    [
        {"max_concurrency": 0, "memory_mb": 1024, "timeout_seconds": 30},
        {"max_concurrency": 1, "memory_mb": 1, "timeout_seconds": 30},
        {"max_concurrency": 1, "memory_mb": 1024, "timeout_seconds": 0},
    ],
)
def test_manifest_rejects_invalid_resource_limits(
    resource_limits: dict[str, int],
) -> None:
    with pytest.raises(PydanticValidationError):
        _manifest(resource_limits=resource_limits)


def test_manifest_nested_metadata_forbids_extra_fields() -> None:
    with pytest.raises(PydanticValidationError, match="unexpected"):
        _manifest(
            resource_limits={
                "max_concurrency": 1,
                "memory_mb": 128,
                "timeout_seconds": 10,
                "unexpected": "command",
            }
        )


def test_unknown_or_not_installed_plugin_is_404() -> None:
    registry = _registry()

    with pytest.raises(NotFoundError):
        registry.require_available("unknown")
    with pytest.raises(NotFoundError):
        registry.require_available("jbrowse")


def test_disabled_plugin_is_404_with_stable_plugin_disabled_code() -> None:
    from app.core.exceptions import PluginDisabledError

    registry = _registry(_manifest(enabled=False))
    with pytest.raises(PluginDisabledError) as raised:
        registry.require_available("jbrowse")

    assert raised.value.status_code == 404
    assert raised.value.error_code == "plugin_disabled"
    assert raised.value.details["reason"] == "plugin_disabled"


@pytest.mark.parametrize(
    ("configured", "healthy", "health_reason", "reason"),
    [
        (False, False, None, "not_configured"),
        (True, False, "upstream_timeout", "upstream_timeout"),
    ],
)
def test_unconfigured_or_unhealthy_plugin_is_503(
    configured: bool,
    healthy: bool,
    health_reason: str | None,
    reason: str,
) -> None:
    from app.core.exceptions import PluginUnavailableError

    registry = _registry(
        _manifest(
            configured=configured,
            healthy=healthy,
            health_reason=health_reason,
        )
    )
    with pytest.raises(PluginUnavailableError) as raised:
        registry.require_available("jbrowse")

    assert raised.value.status_code == 503
    assert raised.value.error_code == "plugin_unavailable"
    assert raised.value.details["reason"] == reason


def test_healthy_plugin_guard_returns_the_verified_state() -> None:
    state = _registry(_manifest()).require_available("jbrowse")
    assert state.installed is True
    assert state.enabled is True
    assert state.configured is True
    assert state.healthy is True
    assert state.assemblies == ("GmWm82.a2.v1",)


def test_official_ols4_manifest_only_installs_when_its_signature_verifies() -> None:
    from app.core.plugins import PluginRegistry
    from app.plugins.ols4 import official_ols4_manifest, sign_official_ols4_manifest

    signing_key = "ols4-deployment-signing-secret"
    manifest = official_ols4_manifest(enabled=True, configured=True, healthy=True)
    signed = sign_official_ols4_manifest(manifest, signing_key)
    tampered = signed.model_copy(update={"signature": "0" * 64})

    trusted = PluginRegistry(
        signing_key=signing_key,
        signed_manifests=[signed],
    ).require_available("ols4")
    untrusted = PluginRegistry(
        signing_key=signing_key,
        signed_manifests=[tampered],
    ).status("ols4")

    assert trusted.version == manifest.version
    assert trusted.public_url is None
    assert untrusted.installed is False
    assert untrusted.reason == "not_installed"


def test_official_ols4_manifest_declares_only_bounded_read_capabilities() -> None:
    from app.plugins.ols4 import official_ols4_manifest

    manifest = official_ols4_manifest()

    assert manifest.key == "ols4"
    assert manifest.task_queues == ()
    assert manifest.resource_limits.max_concurrency == 16
    assert manifest.resource_limits.memory_mb == 256
    assert manifest.resource_limits.timeout_seconds == 5
    assert {(route.method, route.path) for route in manifest.routes} == {
        ("GET", "/api/v1/ontology/search"),
        ("GET", "/api/v1/ontology/term"),
        ("GET", "/api/v1/ontology/graph"),
    }


class _FeatureDb:
    async def execute(self, _statement):
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: [])
        )


@pytest.mark.asyncio
async def test_capabilities_preserves_features_and_adds_plugins_and_databases(
    monkeypatch,
) -> None:
    from app.api.v1 import capabilities

    registry = _registry(_manifest())
    monkeypatch.setattr(capabilities, "get_plugin_registry", lambda: registry)

    response = await capabilities.get_capabilities(_FeatureDb())
    body = response.model_dump(mode="json")

    assert body["version"] == 2
    assert "features" in body
    assert body["plugins"]["jbrowse"] == {
        "version": "2.17.0",
        "installed": True,
        "enabled": True,
        "configured": True,
        "healthy": True,
        "public_url": "https://genome.example.org/browser/",
        "assemblies": ["GmWm82.a2.v1"],
        "reason": None,
    }
    assert body["databases"] == {
        "authoritative": "postgresql",
        "analytics": "clickhouse",
    }


def test_capabilities_response_model_keeps_plugins_backward_compatible_default() -> None:
    from app.schemas.features import PublicCapabilitiesResponse

    response = PublicCapabilitiesResponse(features={"page_builder": True})
    assert response.version == 2
    assert response.plugins == {}
    assert response.databases.authoritative == "postgresql"
