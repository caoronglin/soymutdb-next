"""Pydantic contracts for direct-to-object-storage data publishing."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class MultipartStartRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=256)
    type: str = Field(min_length=1, max_length=32)
    part_count: int = Field(ge=1, le=10_000)
    content_type: str = "application/octet-stream"
    data_set_id: int | None = Field(default=None, ge=1)


class MultipartPart(BaseModel):
    part_number: int = Field(ge=1, le=10_000)
    etag: str = Field(min_length=1, max_length=1024)


class MultipartCompleteRequest(BaseModel):
    object_key: str
    parts: list[MultipartPart] = Field(min_length=1)
    sha256: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$")]


class MultipartSessionResponse(BaseModel):
    upload_id: str
    object_key: str
    parts: list[dict[str, object]]


class ImportCreateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=256)
    type: str = Field(min_length=1, max_length=32)
    file_path: str | None = None
    object_key: str | None = None
    data_set_id: int | None = Field(default=None, ge=1)
    release_id: int | None = Field(default=None, ge=1)
    assembly: str | None = Field(default=None, max_length=128)
    module_key: str | None = Field(default=None, max_length=80)
    schema_version: int | None = Field(default=None, ge=1)
    checksum: str | None = Field(default=None, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=256)


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
