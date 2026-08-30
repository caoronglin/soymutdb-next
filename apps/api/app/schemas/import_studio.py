"""Pydantic contracts for the import-studio editing chain."""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..services.import_studio_service import validate_import_shape

_CODE_FILE_SUFFIXES = (
    ".py",
    ".pyc",
    ".js",
    ".mjs",
    ".cjs",
    ".jsx",
    ".ts",
    ".tsx",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".bat",
    ".cmd",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".jar",
    ".war",
    ".whl",
    ".html",
    ".htm",
)

_SAFE_SOURCE_RE = re.compile(r"^[^\x00-\x1f<>{}|\\]{1,1024}$")


def _reject_code_filename(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.endswith(_CODE_FILE_SUFFIXES):
        raise ValueError("code files cannot be uploaded through Import Studio")
    if normalized.endswith(".xls"):
        raise ValueError(
            "legacy .xls files are not accepted; convert to .xlsx, .csv, or .tsv"
        )
    return value


def _reject_dangerous_source(value: str) -> str:
    if not _SAFE_SOURCE_RE.fullmatch(value):
        raise ValueError("source contains unsupported control/HTML characters")
    return value


class DatasetVersionCreateRequest(BaseModel):
    dataset_id: int = Field(ge=1)
    filename: str = Field(min_length=1, max_length=256)
    object_key: str = Field(min_length=1, max_length=1024)
    checksum_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    source: str = Field(min_length=1, max_length=1024)
    license: str | None = Field(default=None, max_length=256)
    mime_type: str = Field(default="application/octet-stream", max_length=128)
    row_count: int = Field(default=0, ge=0, le=2_000_000)
    column_count: int = Field(default=0, ge=0, le=50)
    source_objects: list[dict[str, Any]] = Field(default_factory=list, max_length=64)

    @field_validator("filename")
    @classmethod
    def reject_code_filename(cls, value: str) -> str:
        return _reject_code_filename(value)

    @field_validator("source")
    @classmethod
    def reject_dangerous_source(cls, value: str) -> str:
        return _reject_dangerous_source(value)


class ImportDraftCreateRequest(BaseModel):
    dataset_version_id: uuid.UUID
    module_key: str | None = Field(default=None, min_length=1, max_length=80)
    row_count: int = Field(ge=0, le=2_000_000)
    column_count: int = Field(ge=0, le=256)

    @model_validator(mode="after")
    def enforce_limits(self) -> ImportDraftCreateRequest:
        try:
            validate_import_shape(
                row_count=self.row_count,
                column_count=self.column_count,
                module_key=self.module_key,
            )
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        return self


class FieldMappingItem(BaseModel):
    source_field: str = Field(min_length=1, max_length=256)
    target_field: str = Field(min_length=1, max_length=256)
    position: int = Field(ge=0, le=49)
    transform: dict[str, Any] = Field(default_factory=dict, max_length=32)


class FieldMappingUpdateRequest(BaseModel):
    mappings: list[FieldMappingItem] = Field(default_factory=list, max_length=50)


class DataPatchItem(BaseModel):
    row_key: str = Field(min_length=1, max_length=512)
    column_name: str = Field(min_length=1, max_length=256)
    old_value: Any = None
    new_value: Any = None
    patch_type: Literal["set", "clear", "format"] = "set"


class DataPatchCreateRequest(BaseModel):
    patches: list[DataPatchItem] = Field(default_factory=list, max_length=10_000)


class ImportValidationRequest(BaseModel):
    row_count: int = Field(ge=0, le=2_000_000)
    column_count: int = Field(ge=0, le=50)
    field_mapping: list[FieldMappingItem] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def enforce_generic_page_limits(self) -> ImportValidationRequest:
        try:
            validate_import_shape(
                row_count=self.row_count,
                column_count=self.column_count,
                module_key=None,
            )
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        return self


class ImportCommitRequest(BaseModel):
    page_id: uuid.UUID | None = None
    source_id: str = Field(default="dataset", min_length=1, max_length=128)
    kind: str = Field(default="dataset", min_length=1, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict, max_length=32)
    confirm: Literal[True] = True


class DatasetVersionResponse(BaseModel):
    id: uuid.UUID
    dataset_id: int
    version: int
    filename: str
    object_key: str
    checksum_sha256: str
    source: str
    license: str | None = None
    mime_type: str
    row_count: int
    column_count: int
    source_objects: list[dict[str, Any]]
    manifest: dict[str, Any] | None = None
    status: str
    created_at: Any | None = None
    updated_at: Any | None = None


class ImportDraftResponse(BaseModel):
    id: uuid.UUID
    dataset_version_id: uuid.UUID
    module_key: str | None = None
    filename: str
    object_key: str
    checksum_sha256: str
    source: str
    license: str | None = None
    mime_type: str
    row_count: int
    column_count: int
    field_mapping: list[dict[str, Any]]
    validation: dict[str, Any]
    status: str
    committed_at: Any | None = None
    created_at: Any | None = None
    updated_at: Any | None = None


class ImportDraftListItemResponse(BaseModel):
    id: uuid.UUID
    dataset_version_id: uuid.UUID
    module_key: str | None = None
    filename: str
    row_count: int
    column_count: int
    status: str
    updated_at: Any | None = None


class PublicationManifestResponse(BaseModel):
    id: uuid.UUID
    import_draft_id: uuid.UUID
    checksum_sha256: str
    manifest: dict[str, Any]
    published_at: Any | None = None


__all__ = [
    "DataPatchCreateRequest",
    "DataPatchItem",
    "DatasetVersionCreateRequest",
    "DatasetVersionResponse",
    "FieldMappingItem",
    "FieldMappingUpdateRequest",
    "ImportCommitRequest",
    "ImportDraftCreateRequest",
    "ImportDraftResponse",
    "ImportDraftListItemResponse",
    "ImportValidationRequest",
    "PublicationManifestResponse",
]
