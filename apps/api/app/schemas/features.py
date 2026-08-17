"""Feature capability API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PublicCapabilitiesResponse(BaseModel):
    version: int = 1
    features: dict[str, bool] = Field(default_factory=dict)


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
