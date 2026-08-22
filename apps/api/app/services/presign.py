"""MinIO / S3 pre-signed URL generation for the analyses feature + admin uploads.

Reuses the API's existing boto3 client configuration (``app.utils.s3``,
driven by ``SOYMUTDB_S3_*`` settings) and adds:

- Constrained POST uploads plus legacy PUT and GET pre-signed URL generation.
- Object-key construction and strict prefix validation so clients can never
  reference objects outside ``analyses/`` (or outside their own job).
- A generic ``uploads/`` namespace for admin uploads (news covers, images,
  attachments) stored in the PUBLIC bucket: ``build_uploads_key`` /
  ``validate_uploads_key`` + ``generate_public_url`` (public-facing URL that
  can be stored directly in DB columns such as ``news_articles.cover_url``).

The analysis upload flow is stateless: the API hands out a pre-signed POST
action and object key; the job row is created only after HEAD verification.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import uuid
from dataclasses import dataclass

from botocore.exceptions import BotoCoreError, ClientError

from ..core.config import get_settings
from ..core.exceptions import ServiceUnavailableError
from ..utils.s3 import get_s3_client

settings = get_settings()

#: Hard ceiling for a single analysis input file (bytes).
MAX_UPLOAD_SIZE: int = 500 * 1024 * 1024
#: Pre-signed URL lifetime for uploads (seconds).
UPLOAD_EXPIRES_IN: int = 3600
#: Pre-signed URL lifetime for downloads (seconds).
DOWNLOAD_EXPIRES_IN: int = 600
#: Positive read size used to derive an object checksum after multipart completion.
#: Keeping this bounded is important for multi-million-row module uploads.
MULTIPART_CHECKSUM_CHUNK_SIZE: int = 1024 * 1024

#: Object-key namespace for analysis inputs; every key must start with this
#: exact segment (a trailing slash boundary is enforced, so ``analyses-evil``
#: does not match).
ANALYSES_PREFIX: str = "analyses"

#: Object-key namespace for admin uploads (public resources: news covers,
#: images, attachments).  Stored in the PUBLIC bucket so the returned
#: ``public_url`` can be persisted directly (e.g. ``cover_url``).
UPLOADS_PREFIX: str = "uploads"
DATA_PREFIX: str = "data"

#: Sanitized filename charset – keeps generated keys predictable and free of
#: control characters / whitespace / separators.
_FILENAME_RE = re.compile(r"[^A-Za-z0-9._+-]+")


@dataclass(frozen=True)
class MultipartSession:
    upload_id: str
    object_key: str


@dataclass(frozen=True)
class CompletedPart:
    part_number: int
    etag: str


@dataclass(frozen=True)
class CompletedObject:
    object_key: str
    upload_id: str
    parts: tuple[CompletedPart, ...]
    sha256: str


@dataclass(frozen=True)
class PresignedPost:
    url: str
    fields: dict[str, str]


def build_data_object_key(data_set_id: int, filename: str) -> str:
    return f"{DATA_PREFIX}/{data_set_id}/{uuid.uuid4()}-{sanitize_filename(filename)}"


def validate_data_key(object_key: str, data_set_id: int | None = None) -> str:
    _validate_key_shape(object_key)
    if not object_key.startswith(f"{DATA_PREFIX}/"):
        raise ValueError("object_key must live under 'data/'")
    if data_set_id is not None and not object_key.startswith(f"{DATA_PREFIX}/{data_set_id}/"):
        raise ValueError("object_key does not belong to this data set")
    return object_key


def initiate_multipart_upload(
    *, data_set_id: int, filename: str, content_type: str, bucket: str | None = None
) -> MultipartSession:
    object_key = build_data_object_key(data_set_id, filename)
    validate_data_key(object_key, data_set_id)
    result = get_s3_client().create_multipart_upload(
        Bucket=bucket or settings.s3_analyses_bucket, Key=object_key, ContentType=content_type
    )
    return MultipartSession(upload_id=result["UploadId"], object_key=object_key)


def sign_multipart_part(
    *, object_key: str, upload_id: str, part_number: int, bucket: str | None = None
) -> str:
    validate_data_key(object_key)
    if not 1 <= part_number <= 10_000:
        raise ValueError("part_number must be between 1 and 10000")
    return get_s3_client().generate_presigned_url(
        "upload_part",
        Params={
            "Bucket": bucket or settings.s3_analyses_bucket,
            "Key": object_key,
            "UploadId": upload_id,
            "PartNumber": part_number,
        },
        ExpiresIn=UPLOAD_EXPIRES_IN,
    )


def complete_multipart_upload(
    *, object_key: str, upload_id: str, parts: list[CompletedPart],
    sha256: str | None = None, bucket: str | None = None
) -> CompletedObject:
    validate_data_key(object_key)
    if sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise ValueError("sha256 must be a 64-character hexadecimal digest")
    if not parts or any(not p.etag or not 1 <= p.part_number <= 10_000 for p in parts):
        raise ValueError("parts must contain valid part numbers and ETags")
    target_bucket = bucket or settings.s3_analyses_bucket
    client = get_s3_client()
    try:
        client.complete_multipart_upload(
            Bucket=target_bucket, Key=object_key, UploadId=upload_id,
            MultipartUpload={
                "Parts": [
                    {"PartNumber": p.part_number, "ETag": p.etag} for p in parts
                ]
            },
        )
    except Exception:
        client.abort_multipart_upload(
            Bucket=target_bucket,
            Key=object_key,
            UploadId=upload_id,
        )
        raise

    try:
        computed_sha256 = _stream_object_sha256(client, target_bucket, object_key)
    except Exception:
        _delete_completed_object(client, target_bucket, object_key)
        raise

    # Old clients may still send a digest. Keep that contract as a cross-check,
    # but make the persisted value server-derived so modern clients do not need
    # an unbounded browser-side WebCrypto buffer.
    if sha256 is not None and sha256.lower() != computed_sha256:
        _delete_completed_object(client, target_bucket, object_key)
        raise ValueError("server-derived checksum does not match the declared sha256")
    return CompletedObject(object_key, upload_id, tuple(parts), computed_sha256)


def _stream_object_sha256(client, bucket: str, object_key: str) -> str:
    """Return an object's SHA-256 using bounded positive reads only."""
    response = client.get_object(Bucket=bucket, Key=object_key)
    body = response.get("Body")
    if body is None or not hasattr(body, "read"):
        raise ValueError("completed object could not be read for checksum verification")
    digest = hashlib.sha256()
    try:
        while True:
            chunk = body.read(MULTIPART_CHECKSUM_CHUNK_SIZE)
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                raise ValueError("completed object returned a non-bytes stream chunk")
            digest.update(chunk)
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()
    return digest.hexdigest()


def _delete_completed_object(client, bucket: str, object_key: str) -> None:
    """Best-effort cleanup after an integrity failure; callers always fail closed."""
    try:
        client.delete_object(Bucket=bucket, Key=object_key)
    except Exception:
        # The caller still raises, so cleanup failure can never turn into a
        # successful import. Storage lifecycle rules handle a rare leftover.
        pass


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


def generate_upload_post(
    object_key: str,
    *,
    size: int,
    content_type: str,
    checksum_sha256: str,
    bucket: str | None = None,
    expires_in: int = UPLOAD_EXPIRES_IN,
) -> PresignedPost:
    """Create an exact-size, exact-MIME pre-signed POST policy.

    The declared values are copied into signed object metadata so submitters
    and workers can independently compare them with ``HEAD`` results.  S3 is
    also instructed to persist a SHA-256 checksum for the uploaded object.
    """
    if not 1 <= size <= MAX_UPLOAD_SIZE:
        raise ValueError(f"size must be between 1 and {MAX_UPLOAD_SIZE} bytes")
    normalized_type = content_type.strip().lower()
    if not normalized_type:
        raise ValueError("content_type must not be empty")
    try:
        checksum_bytes = bytes.fromhex(checksum_sha256)
    except ValueError as exc:
        raise ValueError("checksum_sha256 must be a 64-character hex digest") from exc
    if len(checksum_bytes) != 32:
        raise ValueError("checksum_sha256 must be a 64-character hex digest")
    checksum_hex = checksum_sha256.lower()
    checksum_base64 = base64.b64encode(checksum_bytes).decode("ascii")
    fields = {
        "Content-Type": normalized_type,
        "x-amz-meta-declared-size": str(size),
        "x-amz-meta-declared-content-type": normalized_type,
        "x-amz-meta-declared-sha256": checksum_hex,
        "x-amz-checksum-algorithm": "SHA256",
        "x-amz-checksum-sha256": checksum_base64,
    }
    result = get_s3_client().generate_presigned_post(
        Bucket=bucket or settings.s3_analyses_bucket,
        Key=object_key,
        Fields=fields,
        Conditions=[
            ["content-length-range", size, size],
            *({name: value} for name, value in fields.items()),
        ],
        ExpiresIn=expires_in,
    )
    return PresignedPost(url=result["url"], fields=result["fields"])


def validate_uploaded_analysis_object(
    object_key: str,
    *,
    bucket: str | None = None,
    max_size: int = MAX_UPLOAD_SIZE,
) -> dict[str, object]:
    """Fail closed unless an uploaded object matches its signed declaration."""
    try:
        response = get_s3_client().head_object(
            Bucket=bucket or settings.s3_analyses_bucket,
            Key=object_key,
            ChecksumMode="ENABLED",
        )
    except ClientError as exc:
        error = exc.response.get("Error") or {}
        error_code = str(error.get("Code") or "").lower()
        response_metadata = exc.response.get("ResponseMetadata") or {}
        http_status = response_metadata.get("HTTPStatusCode")
        if http_status == 404 or error_code in {"404", "nosuchkey", "notfound"}:
            raise ValueError("uploaded object was not found") from exc
        raise ServiceUnavailableError(
            "Object storage is temporarily unavailable"
        ) from exc
    except BotoCoreError as exc:
        raise ServiceUnavailableError(
            "Object storage is temporarily unavailable"
        ) from exc
    size = response.get("ContentLength")
    if not isinstance(size, int) or size <= 0:
        raise ValueError("uploaded object has no valid ContentLength")
    if size > max_size:
        raise ValueError(f"uploaded object exceeds the {max_size}-byte limit")
    metadata = response.get("Metadata")
    if not isinstance(metadata, dict):
        raise ValueError("uploaded object is missing signed declaration metadata")
    try:
        declared_size = int(metadata["declared-size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("uploaded object is missing a valid declared size") from exc
    if declared_size != size:
        raise ValueError("uploaded object ContentLength does not match declared size")
    content_type = str(response.get("ContentType") or "").strip().lower()
    declared_type = str(metadata.get("declared-content-type") or "").strip().lower()
    if not content_type or content_type != declared_type:
        raise ValueError("uploaded object ContentType does not match declared content type")
    checksum = response.get("ChecksumSHA256")
    try:
        decoded_checksum = base64.b64decode(str(checksum), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("uploaded object is missing a valid SHA-256 checksum") from exc
    if len(decoded_checksum) != 32:
        raise ValueError("uploaded object is missing a valid SHA-256 checksum")
    try:
        declared_checksum = bytes.fromhex(str(metadata["declared-sha256"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("uploaded object is missing a valid declared SHA-256") from exc
    if len(declared_checksum) != 32:
        raise ValueError("uploaded object is missing a valid declared SHA-256")
    if decoded_checksum != declared_checksum:
        raise ValueError("uploaded object checksum does not match its signed declaration")
    return response


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


def build_upload_key(
    user_id: str | uuid.UUID,
    upload_session_id: str | uuid.UUID,
    filename: str,
) -> str:
    """Build the object key for a new upload.

    Shape: ``analyses/{user_id}/{upload_session_id}/input/`` plus an opaque
    filename.  The upload session is independent of the analysis job created
    later; the user segment binds the stateless upload to its owner.
    """
    name = sanitize_filename(filename)
    return (
        f"{ANALYSES_PREFIX}/{user_id}/{upload_session_id}/input/"
        f"{uuid.uuid4()}-{name}"
    )


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


def validate_analysis_input_key(
    object_key: str, user_id: str | uuid.UUID
) -> str:
    """Validate a stateless analysis upload object key.

    The accepted shape is exactly
    ``analyses/{user_uuid}/{upload_session_uuid}/input/{filename}``, and the
    embedded owner must match *user_id*.
    """
    validate_analyses_key(object_key)
    segments = object_key.split("/")
    if len(segments) != 5 or segments[3] != "input" or not segments[4]:
        raise ValueError(
            "object_key must use the shape "
            "'analyses/{user UUID}/{upload session UUID}/input/{filename}'"
        )
    try:
        owner_id = uuid.UUID(segments[1])
        upload_session_id = uuid.UUID(segments[2])
    except ValueError as exc:
        raise ValueError(
            "object_key must contain canonical user and upload session UUIDs"
        ) from exc
    if str(owner_id) != segments[1].lower():
        raise ValueError("object_key must contain a canonical user UUID")
    if str(upload_session_id) != segments[2].lower():
        raise ValueError("object_key must contain a canonical UUID upload session")
    if owner_id != uuid.UUID(str(user_id)):
        raise ValueError("object_key does not belong to this user")
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
    "DATA_PREFIX",
    "build_upload_key",
    "build_uploads_key",
    "generate_download_url",
    "generate_public_url",
    "generate_upload_url",
    "generate_upload_post",
    "sanitize_filename",
    "validate_analyses_key",
    "validate_analysis_input_key",
    "validate_uploaded_analysis_object",
    "validate_job_object_key",
    "validate_uploads_key",
    "build_data_object_key",
    "validate_data_key",
    "initiate_multipart_upload",
    "sign_multipart_part",
    "complete_multipart_upload",
    "CompletedPart",
    "CompletedObject",
    "MultipartSession",
    "PresignedPost",
]
