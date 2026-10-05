"""S3 utility functions for workers.

Provides:
- Streaming reads via HTTP Range requests
- Multipart upload for large files
- Pre-signed URL generation
- File existence / size checks
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import boto3
from botocore.client import BaseClient

from soymutdb_worker.config import get_setting

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def get_s3_client() -> BaseClient:
    """Return a configured S3 (or MinIO) client."""
    return boto3.client(
        "s3",
        endpoint_url=get_setting("S3_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=get_setting("S3_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=get_setting("S3_SECRET_KEY", "minioadmin"),
        region_name=get_setting("S3_REGION", "us-east-1"),
    )


# ---------------------------------------------------------------------------
# Path parsing
# ---------------------------------------------------------------------------


def parse_s3_path(s3_path: str) -> tuple[str, str]:
    """Parse an S3 path into ``(bucket, key)``.

    Accepts both ``s3://bucket/key`` and ``bucket/key`` forms.
    """
    if s3_path.startswith("s3://"):
        s3_path = s3_path[5:]
    parts = s3_path.split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""
    return bucket, key


# ---------------------------------------------------------------------------
# Streaming read
# ---------------------------------------------------------------------------


@contextmanager
def stream_s3_file(s3_path: str, chunk_size: int = 8192) -> Iterator[Any]:
    """Stream a file from S3 as a readable body object.

    Usage::

        with stream_s3_file("s3://bucket/key") as body:
            for chunk in body.iter_chunks(chunk_size):
                ...
    """
    s3 = get_s3_client()
    bucket, key = parse_s3_path(s3_path)
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    try:
        yield body
    finally:
        body.close()


def iter_s3_chunks(s3_path: str, chunk_size: int = 8192) -> Iterator[bytes]:
    """Yield chunks from an S3 object as bytes."""
    with stream_s3_file(s3_path, chunk_size=chunk_size) as body:
        # `yield from` is exactly equivalent here: the loop body was a bare
        # `yield chunk`, with no try/finally, filtering or send/throw handling.
        yield from body.iter_chunks(chunk_size=chunk_size)


# ---------------------------------------------------------------------------
# Download / upload
# ---------------------------------------------------------------------------


@contextmanager
def download_file(s3_path: str, local_path: str | None = None) -> Iterator[str]:
    """Download a file from S3 to a local path.

    If *local_path* is ``None`` a temporary file is created and removed
    after the context exits.
    """
    s3 = get_s3_client()
    bucket, key = parse_s3_path(s3_path)

    if local_path:
        path = Path(local_path)
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / Path(key).name

    try:
        s3.download_file(bucket, key, str(path))
        yield str(path)
    finally:
        if not local_path:
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()
            except OSError:
                pass


def upload_file(
    local_path: str,
    s3_path: str,
    *,
    metadata: dict[str, str] | None = None,
) -> None:
    """Upload a local file to S3 (simple put for files < 5 GB).

    ``metadata`` (string values only, e.g. ``{"checksum": …, "size": …}``)
    is attached to the stored object's metadata.
    """
    s3 = get_s3_client()
    bucket, key = parse_s3_path(s3_path)
    if metadata:
        s3.upload_file(local_path, bucket, key, ExtraArgs={"Metadata": metadata})
    else:
        s3.upload_file(local_path, bucket, key)


def upload_fileobj(fileobj: Any, s3_path: str) -> None:
    """Upload a file-like object to S3."""
    s3 = get_s3_client()
    bucket, key = parse_s3_path(s3_path)
    s3.upload_fileobj(fileobj, bucket, key)


# ---------------------------------------------------------------------------
# Multipart upload (for large files > 5 GB)
# ---------------------------------------------------------------------------

_MULTIPART_PART_SIZE = 8 * 1024 * 1024  # 8 MiB per part


def upload_large_file(local_path: str, s3_path: str) -> None:
    """Upload a large file using multipart upload.

    Suitable for files larger than 5 GB.  Uses 8 MiB parts.
    """
    s3 = get_s3_client()
    bucket, key = parse_s3_path(s3_path)

    file_size = Path(local_path).stat().st_size
    if file_size < _MULTIPART_PART_SIZE * 2:
        upload_file(local_path, s3_path)
        return

    upload_id = create_multipart_upload(s3_path)
    parts: list[dict[str, Any]] = []

    try:
        part_number = 1
        with open(local_path, "rb") as f:
            while True:
                data = f.read(_MULTIPART_PART_SIZE)
                if not data:
                    break
                response = s3.upload_part(
                    Bucket=bucket,
                    Key=key,
                    PartNumber=part_number,
                    UploadId=upload_id,
                    Body=data,
                )
                parts.append(
                    {"PartNumber": part_number, "ETag": response["ETag"]}
                )
                part_number += 1

        complete_multipart_upload(s3_path, upload_id, parts)
    except Exception:
        s3.abort_multipart_upload(
            Bucket=bucket, Key=key, UploadId=upload_id
        )
        raise


def create_multipart_upload(s3_path: str) -> str:
    """Initiate a multipart upload and return the ``UploadId``."""
    s3 = get_s3_client()
    bucket, key = parse_s3_path(s3_path)
    response = s3.create_multipart_upload(Bucket=bucket, Key=key)
    return response["UploadId"]


def complete_multipart_upload(
    s3_path: str,
    upload_id: str,
    parts: list[dict[str, Any]],
) -> None:
    """Complete a multipart upload."""
    s3 = get_s3_client()
    bucket, key = parse_s3_path(s3_path)
    s3.complete_multipart_upload(
        Bucket=bucket,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )


# ---------------------------------------------------------------------------
# Metadata / presigned URLs
# ---------------------------------------------------------------------------


def file_exists(s3_path: str) -> bool:
    """Return ``True`` if the S3 object exists."""
    s3 = get_s3_client()
    bucket, key = parse_s3_path(s3_path)
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def get_file_size(s3_path: str) -> int:
    """Return the size of an S3 object in bytes."""
    s3 = get_s3_client()
    bucket, key = parse_s3_path(s3_path)
    response = s3.head_object(Bucket=bucket, Key=key)
    return int(response.get("ContentLength", 0))


def generate_presigned_url(s3_path: str, expires_in: int = 3600) -> str:
    """Generate a pre-signed URL for downloading a private file."""
    s3 = get_s3_client()
    bucket, key = parse_s3_path(s3_path)
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )


def delete_object(s3_path: str) -> None:
    """Delete a single object from S3."""
    s3 = get_s3_client()
    bucket, key = parse_s3_path(s3_path)
    s3.delete_object(Bucket=bucket, Key=key)


def list_objects(
    s3_prefix: str,
    max_keys: int = 1000,
) -> list[dict[str, Any]]:
    """List objects under an S3 prefix."""
    s3 = get_s3_client()
    bucket, prefix = parse_s3_path(s3_prefix)
    response = s3.list_objects_v2(
        Bucket=bucket, Prefix=prefix, MaxKeys=max_keys
    )
    return response.get("Contents", [])
