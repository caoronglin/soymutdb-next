"""Canonical, deployment-signed manifest for the read-only OLS4 adapter.

The manifest deliberately contains no upstream credentials or mutable runtime
values. Deploy tooling sets the lifecycle flags, signs the canonical payload
with the deployment key, and supplies that envelope through the existing
``SOYMUTDB_PLUGIN_MANIFESTS_JSON`` boundary.
"""

from __future__ import annotations

from ..core.plugins import PluginManifest, SignedPluginManifest, sign_plugin_manifest

OLS4_PLUGIN_KEY = "ols4"
OLS4_PLUGIN_VERSION = "1.0.0"
OLS4_UPSTREAM_ORIGIN = "https://www.ebi.ac.uk/ols4"


def official_ols4_manifest(
    *,
    enabled: bool = False,
    configured: bool = False,
    healthy: bool = False,
    health_reason: str | None = None,
) -> PluginManifest:
    """Return the canonical metadata that deployment must sign for OLS4."""
    return PluginManifest(
        key=OLS4_PLUGIN_KEY,
        version=OLS4_PLUGIN_VERSION,
        api_compatibility={"minimum": "2.0.0", "maximum_exclusive": "3.0.0"},
        license="Apache-2.0",
        config_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        routes=(
            {"method": "GET", "path": "/api/v1/ontology/search"},
            {"method": "GET", "path": "/api/v1/ontology/term"},
            {"method": "GET", "path": "/api/v1/ontology/graph"},
        ),
        task_queues=(),
        resource_limits={
            "max_concurrency": 16,
            "memory_mb": 256,
            "timeout_seconds": 5,
        },
        healthcheck={
            "path": "/api/v1/health/ready",
            "interval_seconds": 30,
            "timeout_seconds": 5,
        },
        enabled=enabled,
        configured=configured,
        healthy=healthy,
        public_url=None,
        public_url_allowlist=(),
        assemblies=(),
        uninstall_semantics="disable_only",
        health_reason=health_reason,
    )


def sign_official_ols4_manifest(
    manifest: PluginManifest,
    signing_key: str,
) -> SignedPluginManifest:
    """Sign only the canonical OLS4 declaration through the shared signer."""
    if manifest.key != OLS4_PLUGIN_KEY:
        raise ValueError("manifest must use the ols4 plugin key")
    return sign_plugin_manifest(manifest, signing_key)


__all__ = [
    "OLS4_PLUGIN_KEY",
    "OLS4_PLUGIN_VERSION",
    "OLS4_UPSTREAM_ORIGIN",
    "official_ols4_manifest",
    "sign_official_ols4_manifest",
]
