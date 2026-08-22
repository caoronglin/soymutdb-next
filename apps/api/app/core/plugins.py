"""Signed, versioned deployment manifests and fail-closed plugin status.

Plugins are server-owned integration points.  Administrators cannot upload or
execute plugin code through the API: deployment supplies signed manifests and
the API only exposes their verified, non-secret status projection.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any, Final, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import get_settings
from .exceptions import (
    NotFoundError,
    PluginDisabledError,
    PluginUnavailableError,
)


@dataclass(frozen=True)
class PluginDefinition:
    key: str
    description: str


BUILTIN_PLUGINS: Final[dict[str, PluginDefinition]] = {
    "jbrowse": PluginDefinition("jbrowse", "JBrowse genome browser integration."),
    "blast": PluginDefinition("blast", "BLAST sequence-search integration."),
    "analyses": PluginDefinition("analyses", "Managed analysis workflows."),
    "mcp": PluginDefinition("mcp", "Model Context Protocol adapter."),
    "ols4": PluginDefinition("ols4", "Read-only EMBL-EBI OLS4 ontology integration."),
}

_SEMVER_PATTERN = r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$"
_SPDX_LICENSES: Final = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "GPL-2.0-only",
        "GPL-3.0-only",
        "ISC",
        "LGPL-2.1-only",
        "LGPL-3.0-only",
        "MIT",
        "MPL-2.0",
    }
)
PluginQueueName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")]


class PluginApiCompatibility(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum: str = Field(pattern=_SEMVER_PATTERN)
    maximum_exclusive: str = Field(pattern=_SEMVER_PATTERN)

    @model_validator(mode="after")
    def validate_range(self) -> PluginApiCompatibility:
        def release_tuple(version: str) -> tuple[int, int, int]:
            return tuple(int(part) for part in version.split("-", 1)[0].split("."))  # type: ignore[return-value]

        if release_tuple(self.minimum) >= release_tuple(self.maximum_exclusive):
            raise ValueError("minimum must be lower than maximum_exclusive")
        return self


class PluginRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(pattern=r"^/api/v\d+(?:/[A-Za-z0-9_.{}:-]+)*$", max_length=256)


class PluginResourceLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_concurrency: int = Field(ge=1, le=128)
    memory_mb: int = Field(ge=64, le=65_536)
    timeout_seconds: int = Field(ge=1, le=3_600)


class PluginHealthcheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(pattern=r"^/api/v\d+(?:/[A-Za-z0-9_.{}:-]+)*$", max_length=256)
    interval_seconds: int = Field(ge=5, le=3_600)
    timeout_seconds: int = Field(ge=1, le=60)

    @model_validator(mode="after")
    def timeout_is_bounded_by_interval(self) -> PluginHealthcheck:
        if self.timeout_seconds >= self.interval_seconds:
            raise ValueError("timeout_seconds must be lower than interval_seconds")
        return self


def _contains_configuration_value(schema: object) -> bool:
    if isinstance(schema, dict):
        if any(key in schema for key in ("const", "default", "examples")):
            return True
        return any(_contains_configuration_value(value) for value in schema.values())
    if isinstance(schema, list):
        return any(_contains_configuration_value(value) for value in schema)
    return False


def _https_origin(value: str) -> str | None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"https://{parsed.hostname.lower()}{port}"


class PluginManifest(BaseModel):
    """Immutable schema-v1 deployment declaration for one plugin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_version: Literal[1] = 1
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    version: str = Field(min_length=1, max_length=64)
    api_compatibility: PluginApiCompatibility
    license: str = Field(min_length=1, max_length=64)
    config_schema: dict[str, Any]
    routes: tuple[PluginRoute, ...]
    task_queues: tuple[PluginQueueName, ...]
    resource_limits: PluginResourceLimits
    healthcheck: PluginHealthcheck
    enabled: bool = False
    configured: bool = False
    healthy: bool = False
    public_url: str | None = Field(default=None, max_length=2_048)
    public_url_allowlist: tuple[str, ...] = ()
    assemblies: tuple[str, ...]
    uninstall_semantics: Literal[
        "disable_only", "retain_data", "deployment_purge_required"
    ]
    health_reason: str | None = Field(default=None, max_length=512)

    @field_validator("license")
    @classmethod
    def validate_license(cls, value: str) -> str:
        if value in _SPDX_LICENSES:
            return value
        if value.startswith("LicenseRef-") and value.removeprefix("LicenseRef-").replace(
            "-", ""
        ).isalnum():
            return value
        raise ValueError("license must be a supported SPDX identifier or LicenseRef")

    @field_validator("config_schema")
    @classmethod
    def validate_config_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("type") != "object":
            raise ValueError("config_schema must declare an object")
        if _contains_configuration_value(value):
            raise ValueError("config_schema must not contain configuration values")
        return value

    @model_validator(mode="after")
    def validate_public_url_policy(self) -> PluginManifest:
        allowed_origins: set[str] = set()
        for candidate in self.public_url_allowlist:
            origin = _https_origin(candidate)
            parsed = urlsplit(candidate)
            if origin is None or parsed.path not in {"", "/"}:
                raise ValueError("public_url_allowlist entries must be HTTPS origins")
            allowed_origins.add(origin)

        if self.public_url is not None:
            origin = _https_origin(self.public_url)
            if origin is None or origin not in allowed_origins:
                raise ValueError("public_url must use HTTPS and match the manifest allowlist")
        if len(set(self.assemblies)) != len(self.assemblies):
            raise ValueError("assemblies must not contain duplicates")
        if len(set(self.task_queues)) != len(self.task_queues):
            raise ValueError("task_queues must not contain duplicates")
        route_keys = {(route.method, route.path) for route in self.routes}
        if len(route_keys) != len(self.routes):
            raise ValueError("routes must not contain duplicates")
        return self


class SignedPluginManifest(BaseModel):
    """Manifest envelope whose signature covers canonical manifest JSON."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: PluginManifest
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PluginState:
    version: str | None
    installed: bool
    enabled: bool
    configured: bool
    healthy: bool
    public_url: str | None
    assemblies: tuple[str, ...]
    reason: str | None


def _manifest_payload(manifest: PluginManifest) -> bytes:
    return json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def sign_plugin_manifest(manifest: PluginManifest, signing_key: str) -> SignedPluginManifest:
    """Create a signed envelope (used by deployment tooling and tests)."""
    if not signing_key:
        raise ValueError("signing_key must not be empty")
    signature = hmac.new(
        signing_key.encode("utf-8"), _manifest_payload(manifest), hashlib.sha256
    ).hexdigest()
    return SignedPluginManifest(manifest=manifest, signature=signature)


class PluginRegistry:
    """Resolve verified deployment manifests into public and guard states."""

    def __init__(
        self,
        *,
        signing_key: str | None,
        signed_manifests: list[SignedPluginManifest],
    ) -> None:
        verified: dict[str, PluginManifest] = {}
        duplicates: set[str] = set()
        if signing_key:
            for envelope in signed_manifests:
                manifest = envelope.manifest
                if manifest.key not in BUILTIN_PLUGINS:
                    continue
                expected = hmac.new(
                    signing_key.encode("utf-8"),
                    _manifest_payload(manifest),
                    hashlib.sha256,
                ).hexdigest()
                if not hmac.compare_digest(envelope.signature, expected):
                    continue
                if manifest.key in verified:
                    duplicates.add(manifest.key)
                else:
                    verified[manifest.key] = manifest
        for duplicate in duplicates:
            verified.pop(duplicate, None)
        self._verified = verified

    def verified_manifest(self, key: str) -> PluginManifest | None:
        if key not in BUILTIN_PLUGINS:
            raise NotFoundError(f"Plugin '{key}' not found")
        return self._verified.get(key)

    def status(self, key: str, *, enabled_override: bool | None = None) -> PluginState:
        manifest = self.verified_manifest(key)
        if manifest is None:
            return PluginState(
                version=None,
                installed=False,
                enabled=False,
                configured=False,
                healthy=False,
                public_url=None,
                assemblies=(),
                reason="not_installed",
            )
        enabled = manifest.enabled if enabled_override is None else enabled_override
        if not enabled:
            reason = "plugin_disabled"
        elif not manifest.configured:
            reason = "not_configured"
        elif not manifest.healthy:
            reason = manifest.health_reason or "unhealthy"
        else:
            reason = None
        return PluginState(
            version=manifest.version,
            installed=True,
            enabled=enabled,
            configured=manifest.configured,
            healthy=manifest.healthy,
            public_url=manifest.public_url,
            assemblies=manifest.assemblies,
            reason=reason,
        )

    def snapshot(
        self, *, enabled_overrides: dict[str, bool] | None = None
    ) -> dict[str, PluginState]:
        overrides = enabled_overrides or {}
        return {
            key: self.status(key, enabled_override=overrides.get(key))
            for key in BUILTIN_PLUGINS
        }

    def require_available(
        self, key: str, *, enabled_override: bool | None = None
    ) -> PluginState:
        state = self.status(key, enabled_override=enabled_override)
        if not state.installed:
            raise NotFoundError(f"Plugin '{key}' not found")
        if not state.enabled:
            raise PluginDisabledError(
                f"Plugin '{key}' is disabled",
                details={"plugin": key, "reason": "plugin_disabled"},
            )
        if not state.configured:
            raise PluginUnavailableError(
                f"Plugin '{key}' is not configured",
                details={"plugin": key, "reason": "not_configured"},
            )
        if not state.healthy:
            raise PluginUnavailableError(
                f"Plugin '{key}' is unavailable",
                details={"plugin": key, "reason": state.reason or "unhealthy"},
            )
        return state


def _deployment_manifests(raw_json: str) -> list[SignedPluginManifest]:
    try:
        raw = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(raw, list):
        return []
    manifests: list[SignedPluginManifest] = []
    for item in raw:
        try:
            manifests.append(SignedPluginManifest.model_validate(item))
        except ValueError:
            # One malformed declaration must not install anything implicitly.
            continue
    return manifests


@lru_cache
def get_plugin_registry() -> PluginRegistry:
    settings = get_settings()
    return PluginRegistry(
        signing_key=settings.plugin_manifest_signing_key,
        signed_manifests=_deployment_manifests(settings.plugin_manifests_json),
    )


__all__ = [
    "BUILTIN_PLUGINS",
    "PluginDefinition",
    "PluginApiCompatibility",
    "PluginHealthcheck",
    "PluginManifest",
    "PluginRegistry",
    "PluginResourceLimits",
    "PluginRoute",
    "PluginState",
    "SignedPluginManifest",
    "get_plugin_registry",
    "sign_plugin_manifest",
]
