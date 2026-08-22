"""Validation for user-scoped, stateless analysis-upload object keys."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boto3.exceptions import (
    RetriesExceededError,
    S3TransferFailedError,
    S3UploadFailedError,
)
from botocore.exceptions import BotoCoreError, ClientError

ANALYSIS_INPUT_INTEGRITY_ERROR = "analysis input failed integrity verification"
ANALYSIS_STORAGE_ERROR = "analysis object storage operation failed"
ANALYSIS_STORAGE_EXCEPTIONS = (
    ClientError,
    BotoCoreError,
    RetriesExceededError,
    S3TransferFailedError,
    S3UploadFailedError,
)
_HASH_CHUNK_SIZE = 1024 * 1024


class AnalysisInputIntegrityError(ValueError):
    """A downloaded analysis input differs from its validated declaration."""


class AnalysisStorageError(RuntimeError):
    """Object storage could not safely complete an analysis operation."""


@dataclass(frozen=True)
class AnalysisInputDeclaration:
    """Size and SHA-256 captured from a successfully validated remote HEAD."""

    size: int
    sha256: bytes


def validate_analysis_input_key(key: str, user_id: str) -> str:
    """Return a valid user-owned analysis input key.

    The strict shape is
    ``analyses/{user UUID}/{upload-session UUID}/input/{name}``.  Upload
    sessions remain independent of the job UUID, while the user segment must
    match the trusted owner carried by the dispatch payload.
    """
    if not isinstance(key, str) or not key or key.startswith("/"):
        raise ValueError("input object must be a non-empty relative key")
    segments = key.split("/")
    if (
        len(segments) != 5
        or segments[0] != "analyses"
        or segments[3] != "input"
        or not segments[4]
    ):
        raise ValueError(
            "input object must use the shape "
            "'analyses/{user UUID}/{upload session UUID}/input/{filename}'"
        )
    try:
        expected_user_id = uuid.UUID(user_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("analysis payload user_id must be a UUID") from exc
    try:
        key_user_id = uuid.UUID(segments[1])
        upload_session_id = uuid.UUID(segments[2])
    except ValueError as exc:
        raise ValueError(
            "input object must contain canonical user and upload session UUIDs"
        ) from exc
    if str(key_user_id) != segments[1].lower():
        raise ValueError("input object must contain a canonical user UUID")
    if str(upload_session_id) != segments[2].lower():
        raise ValueError("input object must contain a canonical UUID upload session")
    if key_user_id != expected_user_id:
        raise ValueError("input object does not belong to the payload user")
    return key


def head_analysis_input(s3: Any, *, bucket: str, object_key: str) -> dict[str, Any]:
    """Return HEAD metadata without exposing object-storage error details."""
    try:
        return s3.head_object(
            Bucket=bucket,
            Key=object_key,
            ChecksumMode="ENABLED",
        )
    except ANALYSIS_STORAGE_EXCEPTIONS as exc:
        raise AnalysisStorageError(ANALYSIS_STORAGE_ERROR) from exc


def download_validated_analysis_input(
    s3: Any,
    *,
    bucket: str,
    object_key: str,
    local_path: Path,
    declaration: AnalysisInputDeclaration,
) -> None:
    """Download one object and verify its local bytes against the prior HEAD."""
    try:
        s3.download_file(bucket, object_key, str(local_path))
    except ANALYSIS_STORAGE_EXCEPTIONS as exc:
        raise AnalysisStorageError(ANALYSIS_STORAGE_ERROR) from exc

    digest = hashlib.sha256()
    actual_size = 0
    try:
        with local_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(_HASH_CHUNK_SIZE), b""):
                actual_size += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise AnalysisInputIntegrityError(ANALYSIS_INPUT_INTEGRITY_ERROR) from exc

    if actual_size != declaration.size or not hmac.compare_digest(
        digest.digest(), declaration.sha256
    ):
        raise AnalysisInputIntegrityError(ANALYSIS_INPUT_INTEGRITY_ERROR)


__all__ = [
    "ANALYSIS_INPUT_INTEGRITY_ERROR",
    "ANALYSIS_STORAGE_ERROR",
    "ANALYSIS_STORAGE_EXCEPTIONS",
    "AnalysisInputDeclaration",
    "AnalysisInputIntegrityError",
    "AnalysisStorageError",
    "download_validated_analysis_input",
    "head_analysis_input",
    "validate_analysis_input_key",
]
