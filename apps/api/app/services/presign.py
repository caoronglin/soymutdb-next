"""MinIO / S3 pre-signed URL generation for the analyses feature + admin uploads.

Reuses the API's existing boto3 client configuration (``app.utils.s3``,
driven by ``SOYMUTDB_S3_*`` settings) and adds:

- PUT (upload) and GET (download) pre-signed URL generation.
- Object-key construction and strict prefix validation so clients can never
  reference objects outside ``analyses/`` (or outside their own job).
- A generic ``uploads/`` namespace for admin uploads (news covers, images,
  attachments) stored in the PUBLIC bucket: ``build_uploads_key`` /
  ``validate_uploads_key`` + ``generate_public_url`` (public-facing URL that
  can be stored directly in DB columns such as ``news_articles.cover_url``).

The upload flow is stateless: the API hands out a pre-signed PUT URL and the
object key; the job row (and outbox dispatch) is created only at submit time.
"""

from __future__ import annotations

import re
import uuid

from ..core.config import get_settings
from ..utils.s3 import get_s3_client

settings = get_settings()

#: Hard ceiling for a single analysis input file (bytes).
MAX_UPLOAD_SIZE: int = 500 * 1024 * 1024
#: Pre-signed URL lifetime for uploads (seconds).
UPLOAD_EXPIRES_IN: int = 3600
#: Pre-signed URL lifetime for downloads (seconds).
DOWNLOAD_EXPIRES_IN: int = 600

#: Object-key namespace for analysis inputs; every key must start with this
#: exact segment (a trailing slash boundary is enforced, so ``analyses-evil``
#: does not match).
ANALYSES_PREFIX: str = "analyses"

#: Object-key namespace for admin uploads (public resources: news covers,
#: images, attachments).  Stored in the PUBLIC bucket so the returned
#: ``public_url`` can be persisted directly (e.g. ``cover_url``).
UPLOADS_PREFIX: str = "uploads"

#: Sanitized filename charset – keeps generated keys predictable and free of
#: control characters / whitespace / separators.
_FILENAME_RE = re.compile(r"[^A-Za-z0-9._+-]+")


def generate_upload_url(
    object_key: str,
    *,
    bucket: str | None = None,
    expires_in: int = UPLOAD_EXPIRES_IN,
) -> str:
    """Return a pre-signed PUT URL for *object_key*.

    The caller must have validated the key with
    :func:`validate_analyses_key` / :func:`build_upload_key`.
    """
    return _presign("put_object", object_key, bucket=bucket, expires_in=expires_in)


def generate_download_url(
    object_key: str,
    *,
    bucket: str | None = None,
    expires_in: int = DOWNLOAD_EXPIRES_IN,
) -> str:
    """Return a pre-signed GET URL for *object_key*."""
    return _presign("get_object", object_key, bucket=bucket, expires_in=expires_in)


def _presign(
    method: str,
    object_key: str,
    *,
    bucket: str | None,
    expires_in: int,
) -> str:
    s3 = get_s3_client()
    return s3.generate_presigned_url(
        method,
        Params={
            "Bucket": bucket or settings.s3_analyses_bucket,
            "Key": object_key,
        },
        ExpiresIn=expires_in,
    )


# ---------------------------------------------------------------------------
# Object-key construction / validation
# ---------------------------------------------------------------------------


def build_upload_key(job_id: str | uuid.UUID, filename: str) -> str:
    """Build the object key for a new upload.

    Shape: ``analyses/{job_id}/input/{uuid}-{sanitized-filename}``.  The
    random prefix guarantees key uniqueness and makes the filename opaque.
    """
    name = sanitize_filename(filename)
    return f"{ANALYSES_PREFIX}/{job_id}/input/{uuid.uuid4()}-{name}"


def sanitize_filename(filename: str) -> str:
    """Reduce a client filename to a safe basename (no separators / traversal)."""
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not basename or basename in {".", ".."}:
        raise ValueError("filename must not be empty or a path segment")
    sanitized = _FILENAME_RE.sub("-", basename).strip(".-")
    if not sanitized:
        raise ValueError("filename contains no usable characters")
    return sanitized


def validate_analyses_key(object_key: str) -> str:
    """Validate an object key against the ``analyses/`` namespace.

    Rejects keys outside ``analyses/`` (including look-alike prefixes such as
    ``analyses-evil/...``), absolute paths, empty segments and traversal
    segments (``.`` / ``..``).  Returns the key unchanged on success, raises
    :class:`ValueError` otherwise.
    """
    _validate_key_shape(object_key)
    if not object_key.startswith(f"{ANALYSES_PREFIX}/"):
        raise ValueError(
            f"object_key must live under '{ANALYSES_PREFIX}/'"
        )
    return object_key


def validate_job_object_key(object_key: str, job_id: str | uuid.UUID) -> str:
    """Validate that *object_key* belongs to *job_id*.

    Applies the ``analyses/`` namespace check and additionally requires the
    ``analyses/{job_id}/`` prefix, so a download can never reference another
    job's objects.
    """
    validate_analyses_key(object_key)
    job_prefix = f"{ANALYSES_PREFIX}/{job_id}/"
    if not object_key.startswith(job_prefix):
        raise ValueError(
            f"object_key must be under '{job_prefix}' for this job"
        )
    return object_key


# ---------------------------------------------------------------------------
# Generic admin uploads namespace (public bucket)
# ---------------------------------------------------------------------------


def build_uploads_key(purpose: str, filename: str) -> str:
    """Build the object key for a new admin upload.

    Shape: ``uploads/{purpose}/{uuid}-{sanitized-filename}``.  The random
    prefix guarantees key uniqueness and makes the filename opaque.  The
    *purpose* segment must be a single safe word (e.g. ``news``); it is
    sanitised the same way as the filename.
    """
    safe_purpose = sanitize_filename(purpose).lower()
    name = sanitize_filename(filename)
    return f"{UPLOADS_PREFIX}/{safe_purpose}/{uuid.uuid4()}-{name}"


def validate_uploads_key(object_key: str) -> str:
    """Validate an object key against the ``uploads/`` namespace.

    Rejects keys outside ``uploads/`` (including look-alike prefixes such as
    ``uploads-evil/...``), absolute paths, empty segments and traversal
    segments (``.`` / ``..``).  Returns the key unchanged on success, raises
    :class:`ValueError` otherwise.
    """
    _validate_key_shape(object_key)
    if not object_key.startswith(f"{UPLOADS_PREFIX}/"):
        raise ValueError(
            f"object_key must live under '{UPLOADS_PREFIX}/'"
        )
    return object_key


def generate_public_url(object_key: str, *, bucket: str | None = None) -> str:
    """Return the public-facing URL for *object_key* in the public bucket.

    ``{s3_public_url}/{object_key}`` — the URL served by the public static
    gateway (nginx / MinIO proxy) configured via ``SOYMUTDB_S3_PUBLIC_URL``.
    Suitable for persisting into columns like ``news_articles.cover_url``.
    """
    return f"{settings.s3_public_url.rstrip('/')}/{object_key.lstrip('/')}"


def _validate_key_shape(object_key: str) -> None:
    if not object_key or object_key.startswith("/"):
        raise ValueError("object_key must not be empty or absolute")
    if "//" in object_key:
        raise ValueError("object_key must not contain empty segments")
    segments = object_key.split("/")
    if any(seg in {"", ".", ".."} for seg in segments):
        raise ValueError("object_key must not contain traversal segments")


__all__ = [
    "ANALYSES_PREFIX",
    "DOWNLOAD_EXPIRES_IN",
    "MAX_UPLOAD_SIZE",
    "UPLOAD_EXPIRES_IN",
    "UPLOADS_PREFIX",
    "build_upload_key",
    "build_uploads_key",
    "generate_download_url",
    "generate_public_url",
    "generate_upload_url",
    "sanitize_filename",
    "validate_analyses_key",
    "validate_job_object_key",
    "validate_uploads_key",
]
