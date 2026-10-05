"""S3 / MinIO utility functions for the API layer.

Provides:
- Pre-signed URL generation
- File size / existence checks
- Streaming reads (async generator)
- Path parsing

Mirrors ``apps/worker/src/soymutdb_worker/utils/s3.py`` but reads
configuration from ``app.core.config.settings`` instead of environment
variables, and provides async generators for the FastAPI layer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import boto3
from botocore.client import BaseClient

from ..core.config import get_settings

_settings = get_settings()


def get_s3_client() -> BaseClient:
    """Return a configured S3 (or MinIO) client.

    Credentials and endpoint are read from ``app.core.config.settings``,
    which pulls from ``SOYMUTDB_*`` environment variables.
    """
    return boto3.client(
        "s3",
        endpoint_url=_settings.s3_endpoint,
        aws_access_key_id=_settings.s3_access_key,
        aws_secret_access_key=_settings.s3_secret_key,
        region_name=_settings.s3_region,
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


def is_s3_path(path: str) -> bool:
    """Return ``True`` if *path* looks like an S3 path."""
    return path.startswith("s3://")


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
    """Generate a pre-signed URL for downloading a private file.

    The URL is valid for *expires_in* seconds (default 1 hour).
    """
    s3 = get_s3_client()
    bucket, key = parse_s3_path(s3_path)
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )


# ---------------------------------------------------------------------------
# Streaming read (async generator for FastAPI)
# ---------------------------------------------------------------------------


async def stream_file(s3_path: str, chunk_size: int = 8192) -> AsyncIterator[bytes]:
    """Async generator that yields bytes from an S3 object.

    Suitable for :class:`fastapi.responses.StreamingResponse`.
    """
    s3 = get_s3_client()
    bucket, key = parse_s3_path(s3_path)
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    try:
        for chunk in body.iter_chunks(chunk_size=chunk_size):
            yield chunk
    finally:
        body.close()


# ---------------------------------------------------------------------------
# Object management
# ---------------------------------------------------------------------------


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
