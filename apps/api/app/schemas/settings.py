"""Typed administrator settings contract schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PublicSettingKind = Literal["string", "integer", "boolean", "enum", "email", "url"]
PublicSettingPermission = Literal["administrator"]
PublicSettingScope = Literal["global"]
PublicSettingRedaction = Literal["none", "omit"]
type SettingValue = str | int | bool


class SettingFieldSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: PublicSettingKind
    default: SettingValue | None
    permission: PublicSettingPermission
    scope: PublicSettingScope
    hot_reload: bool
    redaction: PublicSettingRedaction
    requires_approval: bool
    allowed_values: list[str] = Field(default_factory=list)
    allowed_url_hosts: list[str] = Field(default_factory=list)
    minimum: int | None = None
    maximum: int | None = None
    max_length: int


class SettingsSectionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: dict[str, SettingFieldSchema]


class SettingsSchemaResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    sections: dict[str, SettingsSectionSchema]


class SettingsValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    values: dict[str, SettingValue] = Field(min_length=1)


class SettingsValidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str
    valid: Literal[True] = True
    values: dict[str, SettingValue]


class SettingsPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    values: dict[str, SettingValue] = Field(min_length=1)


class SettingsDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str
    version: int = Field(ge=0)
    values: dict[str, SettingValue]


class SettingsHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    action: Literal["patch", "put_compat", "rollback"]
    values: dict[str, SettingValue]
    changes: dict[str, SettingValue | None]
    actor_id: uuid.UUID | None = None
    created_at: datetime
    rollback_from_version: int | None = Field(default=None, ge=1)
    reason: str | None = None


class SettingsHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str
    current_version: int = Field(ge=0)
    items: list[SettingsHistoryItem]


class SettingsRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    target_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=512)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        return value


__all__ = [
    "PublicSettingKind",
    "PublicSettingPermission",
    "PublicSettingRedaction",
    "PublicSettingScope",
    "SettingFieldSchema",
    "SettingValue",
    "SettingsDocumentResponse",
    "SettingsHistoryItem",
    "SettingsHistoryResponse",
    "SettingsPatchRequest",
    "SettingsRollbackRequest",
    "SettingsSchemaResponse",
    "SettingsSectionSchema",
    "SettingsValidateRequest",
    "SettingsValidateResponse",
]
