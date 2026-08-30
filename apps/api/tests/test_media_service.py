from __future__ import annotations

import pytest

from app.core.exceptions import ValidationError
from app.schemas.media import MediaAssetCompleteRequest, MediaAssetUpdateRequest
from app.services.media_service import sniff_image_metadata, validate_public_media_url


def test_png_metadata_is_trusted_from_header() -> None:
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + (640).to_bytes(4, "big")
        + (360).to_bytes(4, "big")
    )
    assert sniff_image_metadata(payload) == ("image/png", 640, 360)


def test_webp_extended_metadata_is_trusted_from_header() -> None:
    payload = (
        b"RIFF"
        + (22).to_bytes(4, "little")
        + b"WEBP"
        + b"VP8X"
        + (10).to_bytes(4, "little")
        + b"\x00\x00\x00\x00"
        + (639).to_bytes(3, "little")
        + (359).to_bytes(3, "little")
    )
    assert sniff_image_metadata(payload) == ("image/webp", 640, 360)


def test_upload_completion_contract_normalizes_and_scopes_key() -> None:
    request = MediaAssetCompleteRequest(
        object_key="uploads/news/asset-image.png",
        filename="folder/asset-image.png",
        purpose="NEWS",
        size=12,
        content_type="IMAGE/PNG",
        checksum_sha256="A" * 64,
    )
    assert request.purpose == "news"
    assert request.content_type == "image/png"
    assert request.checksum_sha256 == "a" * 64
    assert request.filename == "asset-image.png"


def test_upload_completion_rejects_cross_purpose_key() -> None:
    with pytest.raises(ValueError):
        MediaAssetCompleteRequest(
            object_key="uploads/editor/asset.png",
            filename="asset.png",
            purpose="news",
            size=12,
            content_type="image/png",
            checksum_sha256="a" * 64,
        )


@pytest.mark.parametrize("filename", ["asset.svg", "asset.exe", "asset"])
def test_upload_completion_rejects_unsupported_filename_extension(filename: str) -> None:
    with pytest.raises(ValueError):
        MediaAssetCompleteRequest(
            object_key="uploads/news/asset.png",
            filename=filename,
            purpose="news",
            size=12,
            content_type="image/png",
            checksum_sha256="a" * 64,
        )


def test_media_update_is_partial() -> None:
    assert MediaAssetUpdateRequest(alt_text="A diagram").is_decorative is None


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "data:image/png;base64,abc",
    "s3://bucket/uploads/news/a.png",
    "https://user:pass@example.com/a.png",
    "https://[::1",
])
def test_legacy_cover_url_rejects_unsafe_values(url: str) -> None:
    with pytest.raises(ValidationError):
        validate_public_media_url(url)


def test_legacy_https_cover_url_is_kept_for_compatibility() -> None:
    url = "https://cdn.example/images/a.png"
    assert validate_public_media_url(url) == url
