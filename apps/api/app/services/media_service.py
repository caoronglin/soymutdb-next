"""Media asset lifecycle, verification and query services."""

from __future__ import annotations

import hashlib
import struct
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.exceptions import ConflictError, NotFoundError, ServiceUnavailableError, ValidationError
from ..models.content import NewsArticle
from ..models.media import MediaAsset, MediaAssetStatus
from ..schemas.media import MediaAssetCompleteRequest, MediaAssetUpdateRequest
from ..utils.s3 import get_s3_client
from .presign import validate_uploads_key

settings = get_settings()
MAX_MEDIA_BYTES = 10 * 1024 * 1024


def _read_u24_le(value: bytes) -> int:
    return int.from_bytes(value, byteorder="little", signed=False)


def sniff_image_metadata(data: bytes) -> tuple[str, int | None, int | None]:
    """Return the trusted MIME type and dimensions from image magic bytes.

    This intentionally uses a small dependency-free parser. It is not an image
    decoder; it only accepts the formats allowed by the presign contract and
    rejects files whose bytes do not match the declared type.
    """

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise ValueError("PNG header is incomplete")
        width, height = struct.unpack(">II", data[16:24])
        if not width or not height:
            raise ValueError("image dimensions must be positive")
        return "image/png", width, height

    if data.startswith(b"\xff\xd8"):
        position = 2
        sof_markers = (
            set(range(0xC0, 0xC4))
            | set(range(0xC5, 0xC8))
            | set(range(0xC9, 0xCC))
            | set(range(0xCD, 0xD0))
        )
        while position + 4 <= len(data):
            if data[position] != 0xFF:
                position += 1
                continue
            while position < len(data) and data[position] == 0xFF:
                position += 1
            if position >= len(data):
                break
            marker = data[position]
            position += 1
            if marker in {0xD8, 0xD9}:
                continue
            if position + 2 > len(data):
                break
            segment_length = int.from_bytes(data[position:position + 2], "big")
            if segment_length < 2 or position + segment_length > len(data):
                break
            if marker in sof_markers and segment_length >= 7:
                height = int.from_bytes(data[position + 3:position + 5], "big")
                width = int.from_bytes(data[position + 5:position + 7], "big")
                if width and height:
                    return "image/jpeg", width, height
            position += segment_length
        raise ValueError("JPEG frame header is missing")

    if len(data) >= 20 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        riff_size = int.from_bytes(data[4:8], "little")
        if riff_size < 12 or riff_size + 8 > len(data):
            raise ValueError("WebP container is incomplete")
        chunk = data[12:16]
        chunk_size = int.from_bytes(data[16:20], "little")
        chunk_end = 20 + chunk_size
        if chunk_end > len(data):
            raise ValueError("WebP frame chunk is incomplete")
        chunk_data = data[20:chunk_end]
        width = height = None
        if chunk == b"VP8X" and chunk_size >= 10:
            width = 1 + _read_u24_le(chunk_data[4:7])
            height = 1 + _read_u24_le(chunk_data[7:10])
        elif chunk == b"VP8 " and chunk_size >= 10:
            # Lossy WebP stores a start code before the 14-bit dimensions.
            if chunk_data[3:6] == b"\x9d\x01\x2a":
                width = int.from_bytes(chunk_data[6:8], "little") & 0x3FFF
                height = int.from_bytes(chunk_data[8:10], "little") & 0x3FFF
        elif chunk == b"VP8L" and chunk_size >= 5:
            # Lossless WebP packs a 14-bit width and height after 0x2f.
            if chunk_data[0] == 0x2F:
                width = 1 + ((chunk_data[2] & 0x3F) << 8 | chunk_data[1])
                height = 1 + (
                    ((chunk_data[4] & 0x0F) << 10)
                    | (chunk_data[3] << 2)
                    | (chunk_data[2] >> 6)
                )
        if width and height:
            return "image/webp", width, height
        raise ValueError("WebP frame header is missing")

    raise ValueError("file bytes are not a supported PNG, JPEG or WebP image")


def validate_public_media_url(url: str | None) -> str | None:
    """Reject non-web schemes and storage-internal URLs for legacy covers."""

    if url is None:
        return None
    from urllib.parse import urlsplit

    value = url.strip()
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValidationError("cover_url must be a valid absolute HTTP(S) URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not hostname:
        raise ValidationError("cover_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValidationError("cover_url must not contain credentials")
    if parsed.scheme == "http":
        configured = urlsplit(settings.s3_public_url)
        configured_port = configured.port or (443 if configured.scheme == "https" else 80)
        actual_port = port or 80
        if configured.scheme != "http" or (hostname, actual_port) != (
            configured.hostname,
            configured_port,
        ):
            raise ValidationError("HTTP cover_url must use the configured public media origin")
    return value


def _validate_asset_key(payload: MediaAssetCompleteRequest) -> None:
    key = validate_uploads_key(payload.object_key)
    expected_prefix = f"uploads/{payload.purpose}/"
    if not key.startswith(expected_prefix):
        raise ValidationError("object_key does not belong to the requested media purpose")


def verify_uploaded_image(payload: MediaAssetCompleteRequest) -> dict[str, Any]:
    """Read the uploaded object and verify size, digest, MIME and dimensions."""

    _validate_asset_key(payload)
    try:
        client = get_s3_client()
        head = client.head_object(Bucket=settings.s3_public_bucket, Key=payload.object_key)
        actual_size = int(head.get("ContentLength", -1))
        if actual_size != payload.size:
            raise ValidationError("uploaded object size does not match the request")
        if actual_size > MAX_MEDIA_BYTES:
            raise ValidationError("uploaded object exceeds the media size limit")
        response = client.get_object(Bucket=settings.s3_public_bucket, Key=payload.object_key)
        body = response["Body"]
        try:
            data = body.read(MAX_MEDIA_BYTES + 1)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
    except ValidationError:
        raise
    except (BotoCoreError, ClientError, KeyError, OSError) as exc:
        raise ServiceUnavailableError("uploaded object could not be verified") from exc

    if len(data) != payload.size or len(data) > MAX_MEDIA_BYTES:
        raise ValidationError("uploaded object size does not match the request")
    checksum = hashlib.sha256(data).hexdigest()
    if checksum != payload.checksum_sha256:
        raise ValidationError("uploaded object checksum does not match the request")
    try:
        detected_type, width, height = sniff_image_metadata(data)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if detected_type != payload.content_type:
        raise ValidationError("uploaded object MIME type does not match the request")
    return {
        "size_bytes": len(data),
        "checksum_sha256": checksum,
        "content_type": detected_type,
        "width": width,
        "height": height,
    }


async def list_media_assets(
    db: AsyncSession,
    *,
    search: str | None = None,
    purpose: str | None = None,
    status: MediaAssetStatus = MediaAssetStatus.READY,
    page: int = 1,
    page_size: int = 24,
) -> tuple[list[tuple[MediaAsset, int]], int]:
    """List assets with usage counts in one grouped query."""

    filters = [MediaAsset.status == status.value]
    if purpose:
        filters.append(MediaAsset.purpose == purpose)
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(
                MediaAsset.original_filename.ilike(pattern),
                MediaAsset.alt_text.ilike(pattern),
                MediaAsset.caption.ilike(pattern),
            )
        )

    total = int(await db.scalar(select(func.count(MediaAsset.id)).where(*filters)) or 0)
    usage_join = or_(
        NewsArticle.cover_asset_id == MediaAsset.id,
        NewsArticle.content_en.contains(MediaAsset.public_url),
        NewsArticle.content_zh.contains(MediaAsset.public_url),
        NewsArticle.content_en.contains(MediaAsset.object_key),
        NewsArticle.content_zh.contains(MediaAsset.object_key),
    )
    rows = await db.execute(
        select(MediaAsset, func.count(NewsArticle.id).label("usage_count"))
        .outerjoin(NewsArticle, usage_join)
        .where(*filters)
        .group_by(MediaAsset.id)
        .order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [(asset, int(count)) for asset, count in rows.all()], total


async def get_media_asset(db: AsyncSession, asset_id: UUID) -> MediaAsset:
    asset = await db.scalar(select(MediaAsset).where(MediaAsset.id == asset_id))
    if asset is None:
        raise NotFoundError(f"Media asset {asset_id} not found")
    return asset


async def get_media_asset_usage_count(db: AsyncSession, asset_id: UUID) -> int:
    """Return how many news records reference an asset in covers or rich HTML."""
    asset = await db.scalar(select(MediaAsset).where(MediaAsset.id == asset_id))
    if asset is None:
        return 0
    usage_filter = or_(
        NewsArticle.cover_asset_id == asset.id,
        NewsArticle.content_en.contains(asset.public_url),
        NewsArticle.content_zh.contains(asset.public_url),
        NewsArticle.content_en.contains(asset.object_key),
        NewsArticle.content_zh.contains(asset.object_key),
    )
    return int(await db.scalar(select(func.count(NewsArticle.id)).where(usage_filter)) or 0)


async def complete_media_asset(
    db: AsyncSession,
    payload: MediaAssetCompleteRequest,
    uploaded_by: UUID,
) -> MediaAsset:
    """Verify a presigned object and register it idempotently."""

    verified = verify_uploaded_image(payload)
    existing = await db.scalar(
        select(MediaAsset).where(MediaAsset.object_key == payload.object_key)
    )
    if existing is not None:
        if existing.checksum_sha256 != payload.checksum_sha256:
            raise ConflictError("object_key is already registered with a different checksum")
        if existing.status == MediaAssetStatus.ARCHIVED.value:
            raise ConflictError("archived media assets cannot be reactivated")
        return existing

    asset = MediaAsset(
        object_key=payload.object_key,
        public_url=f"{settings.s3_public_url.rstrip('/')}/{payload.object_key.lstrip('/')}",
        original_filename=payload.filename,
        purpose=payload.purpose,
        content_type=verified["content_type"],
        size_bytes=verified["size_bytes"],
        checksum_sha256=verified["checksum_sha256"],
        width=verified["width"],
        height=verified["height"],
        status=MediaAssetStatus.READY.value,
        uploaded_by=uploaded_by,
        verified_at=datetime.now(UTC),
    )
    db.add(asset)
    try:
        await db.commit()
    except IntegrityError:
        # Two browser tabs may complete the same presigned object at once. The
        # unique object key makes the second insert fail; re-read and return the
        # winner so completion remains idempotent without hiding other errors.
        await db.rollback()
        existing = await db.scalar(
            select(MediaAsset).where(MediaAsset.object_key == payload.object_key)
        )
        if existing is not None:
            if existing.checksum_sha256 != payload.checksum_sha256:
                raise ConflictError("object_key is already registered with a different checksum")
            if existing.status == MediaAssetStatus.ARCHIVED.value:
                raise ConflictError("archived media assets cannot be reactivated")
            return existing
        raise
    await db.refresh(asset)
    return asset


async def update_media_asset(
    db: AsyncSession,
    asset_id: UUID,
    payload: MediaAssetUpdateRequest,
) -> MediaAsset:
    asset = await get_media_asset(db, asset_id)
    if asset.status == MediaAssetStatus.ARCHIVED.value:
        raise ConflictError("archived media assets cannot be edited")
    provided = payload.model_fields_set
    if "alt_text" in provided:
        asset.alt_text = payload.alt_text
    if "caption" in provided:
        asset.caption = payload.caption
    if "credit" in provided:
        asset.credit = payload.credit
    if "is_decorative" in provided and payload.is_decorative is not None:
        asset.is_decorative = payload.is_decorative
    if not asset.is_decorative and not (asset.alt_text or "").strip():
        raise ValidationError("alt_text is required for non-decorative media")
    await db.commit()
    await db.refresh(asset)
    return asset


async def archive_media_asset(db: AsyncSession, asset_id: UUID) -> None:
    asset = await get_media_asset(db, asset_id)
    if asset.status == MediaAssetStatus.ARCHIVED.value:
        return
    usage_count = await get_media_asset_usage_count(db, asset.id)
    if usage_count:
        raise ConflictError("media asset is still used by news content")
    asset.status = MediaAssetStatus.ARCHIVED.value
    asset.archived_at = datetime.now(UTC)
    await db.commit()

    # Database state changes are authoritative. A best-effort delete keeps the
    # request resilient while a scheduled GC can retry storage cleanup later.
    try:
        get_s3_client().delete_object(Bucket=settings.s3_public_bucket, Key=asset.object_key)
    except (BotoCoreError, ClientError, OSError):
        pass


__all__ = [
    "archive_media_asset",
    "complete_media_asset",
    "get_media_asset",
    "get_media_asset_usage_count",
    "list_media_assets",
    "sniff_image_metadata",
    "update_media_asset",
    "validate_public_media_url",
    "verify_uploaded_image",
]
