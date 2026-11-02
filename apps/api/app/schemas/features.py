"""Feature capability API schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PluginCapabilityResponse(BaseModel):
    version: str | None = None
    installed: bool = False
    enabled: bool = False
    configured: bool = False
    healthy: bool = False
    public_url: str | None = None
    assemblies: list[str] = Field(default_factory=list)
    reason: str | None = None


class DatabaseCapabilitiesResponse(BaseModel):
    authoritative: Literal["postgresql"] = "postgresql"
    analytics: Literal["postgresql"] | None = "postgresql"


class PublicCapabilitiesResponse(BaseModel):
    version: int = 2
    features: dict[str, bool] = Field(default_factory=dict)
    plugins: dict[str, PluginCapabilityResponse] = Field(default_factory=dict)
    databases: DatabaseCapabilitiesResponse = Field(
        default_factory=DatabaseCapabilitiesResponse
    )


class FeatureDefinitionResponse(BaseModel):
    key: str
    enabled: bool
    default: bool
    public: bool
    description: str
    disable_behavior: str


class AdminFeaturesResponse(BaseModel):
    version: int = 1
    features: list[FeatureDefinitionResponse] = Field(default_factory=list)


class FeatureUpdateRequest(BaseModel):
    features: dict[str, bool] = Field(default_factory=dict)
