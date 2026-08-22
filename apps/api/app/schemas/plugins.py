"""Admin-only plugin inventory and state mutation schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from ..core.plugins import (
    PluginApiCompatibility,
    PluginHealthcheck,
    PluginManifest,
    PluginResourceLimits,
    PluginRoute,
)
from .features import PluginCapabilityResponse


class PluginManifestMetadata(BaseModel):
    """Non-sensitive signed declarations; no signature or configuration values."""

    manifest_version: int
    key: str
    version: str
    api_compatibility: PluginApiCompatibility
    license: str
    config_schema: dict[str, Any]
    routes: list[PluginRoute]
    task_queues: list[str]
    resource_limits: PluginResourceLimits
    healthcheck: PluginHealthcheck
    assemblies: list[str]
    uninstall_semantics: str

    @classmethod
    def from_manifest(cls, manifest: PluginManifest) -> PluginManifestMetadata:
        return cls.model_validate(
            manifest.model_dump(
                include={
                    "manifest_version",
                    "key",
                    "version",
                    "api_compatibility",
                    "license",
                    "config_schema",
                    "routes",
                    "task_queues",
                    "resource_limits",
                    "healthcheck",
                    "assemblies",
                    "uninstall_semantics",
                }
            )
        )


class AdminPluginResponse(BaseModel):
    key: str
    status: PluginCapabilityResponse
    manifest: PluginManifestMetadata | None = None


class AdminPluginsResponse(BaseModel):
    plugins: dict[str, AdminPluginResponse]


class PluginStateUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


__all__ = [
    "AdminPluginResponse",
    "AdminPluginsResponse",
    "PluginManifestMetadata",
    "PluginStateUpdateRequest",
]
