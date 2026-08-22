"""Pydantic contracts for direct-to-object-storage data publishing."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ImportType = Literal[
    "vcf",
    "gff3",
    "fasta",
    "blast_db",
    "seed_data",
    "expression_csv",
    "homolog_csv",
    "module_tsv",
]

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

_CODE_CONTENT_TYPES = frozenset(
    {
        "application/javascript",
        "application/x-httpd-php",
        "application/x-msdownload",
        "application/x-sh",
        "text/html",
        "text/javascript",
        "text/x-python",
        "text/x-shellscript",
    }
)


def _reject_code_filename(value: str) -> str:
    if value.strip().lower().endswith(_CODE_FILE_SUFFIXES):
        raise ValueError("code files cannot be uploaded through Import Studio")
    return value


class MultipartStartRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=256)
    type: ImportType
    part_count: int = Field(ge=1, le=10_000)
    content_type: str = "application/octet-stream"
    data_set_id: int | None = Field(default=None, ge=1)

    @field_validator("filename")
    @classmethod
    def reject_code_filename(cls, value: str) -> str:
        return _reject_code_filename(value)

    @field_validator("content_type")
    @classmethod
    def reject_code_content_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized in _CODE_CONTENT_TYPES:
            raise ValueError("code files cannot be uploaded through Import Studio")
        return normalized


class MultipartPart(BaseModel):
    part_number: int = Field(ge=1, le=10_000)
    etag: str = Field(min_length=1, max_length=1024)


class MultipartCompleteRequest(BaseModel):
    object_key: str
    parts: list[MultipartPart] = Field(min_length=1)
    # Modern browser clients do not compute a whole-file digest in memory.
    # The API streams the completed object and returns its authoritative digest.
    # Retained as an optional legacy cross-check for older clients.
    sha256: Annotated[str | None, Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")]


class MultipartSessionResponse(BaseModel):
    upload_id: str
    object_key: str
    parts: list[dict[str, object]]


class ImportCreateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=256)
    type: ImportType
    file_path: str | None = None
    object_key: str | None = None
    data_set_id: int | None = Field(default=None, ge=1)
    release_id: int | None = Field(default=None, ge=1)
    assembly: str | None = Field(default=None, max_length=128)
    module_key: str | None = Field(default=None, max_length=80)
    schema_version: int | None = Field(default=None, ge=1)
    checksum: str | None = Field(default=None, max_length=256)
    import_draft_id: uuid.UUID | None = None
    idempotency_key: str = Field(min_length=1, max_length=256)

    @field_validator("filename")
    @classmethod
    def reject_code_filename(cls, value: str) -> str:
        return _reject_code_filename(value)

    @model_validator(mode="after")
    def require_module_release(self) -> ImportCreateRequest:
        if self.type == "module_tsv" and self.release_id is None:
            raise ValueError("release_id is required for module_tsv imports")
        return self


class ImportInspectionRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=256)
    content_base64: str = Field(min_length=1, max_length=512 * 1024)

    @field_validator("filename")
    @classmethod
    def reject_code_filename(cls, value: str) -> str:
        return _reject_code_filename(value)


class ImportInspectionErrorResponse(BaseModel):
    code: str
    row: int | None = None
    message: str


class ImportInspectionValidationResponse(BaseModel):
    ok: bool
    error_count: int = Field(ge=0)
    errors: list[ImportInspectionErrorResponse] = Field(default_factory=list)


class ImportInspectionResponse(BaseModel):
    schema_version: Literal[1] = 1
    module_key: str
    filename: str
    format: str
    encoding: str | None = None
    delimiter: str | None = None
    sheet_name: str | None = None
    headers: list[str] = Field(default_factory=list)
    row_count: int = Field(ge=0)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation: ImportInspectionValidationResponse


class ReleaseActionRequest(BaseModel):
    confirm: Literal[True]
    reason: str = Field(min_length=1, max_length=2000)


class ReleaseReadyRequest(BaseModel):
    manifest: dict[str, object]
    readiness: dict[str, bool]


class ReleaseCreateRequest(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    assembly: str | None = Field(default=None, max_length=128)
    data_set_ids: list[int] = Field(min_length=1)
