"""Tests for S3 utility functions (``app.utils.s3``).

Covers: path parsing, exists/size checks, presigned URLs, streaming.
Uses ``unittest.mock`` to patch ``boto3.client`` — no real S3 required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Path parsing
# ---------------------------------------------------------------------------


class TestParseS3Path:
    """Tests for :func:`app.utils.s3.parse_s3_path`."""

    def test_parse_s3_path_full(self):
        """``s3://bucket/key`` returns ``(bucket, key)``."""
        from app.utils.s3 import parse_s3_path

        bucket, key = parse_s3_path("s3://my-bucket/path/to/file.txt")
        assert bucket == "my-bucket"
        assert key == "path/to/file.txt"

    def test_parse_s3_path_no_scheme(self):
        """``bucket/key`` (without scheme) is also accepted."""
        from app.utils.s3 import parse_s3_path

        bucket, key = parse_s3_path("my-bucket/path/to/file.txt")
        assert bucket == "my-bucket"
        assert key == "path/to/file.txt"

    def test_parse_s3_path_root_key(self):
        """S3 path with just a bucket name returns empty key."""
        from app.utils.s3 import parse_s3_path

        bucket, key = parse_s3_path("s3://my-bucket")
        assert bucket == "my-bucket"
        assert key == ""

    def test_parse_s3_path_nested(self):
        """Deeply nested keys are handled correctly."""
        from app.utils.s3 import parse_s3_path

        bucket, key = parse_s3_path("s3://bucket/a/b/c/d/file.txt")
        assert bucket == "bucket"
        assert key == "a/b/c/d/file.txt"


class TestIsS3Path:
    """Tests for :func:`app.utils.s3.is_s3_path`."""

    def test_is_s3_path_true(self):
        """``s3://...`` paths return True."""
        from app.utils.s3 import is_s3_path

        assert is_s3_path("s3://bucket/key") is True

    def test_is_s3_path_false_https(self):
        """``https://...`` paths return False."""
        from app.utils.s3 import is_s3_path

        assert is_s3_path("https://example.com/file") is False

    def test_is_s3_path_false_local(self):
        """Local file paths return False."""
        from app.utils.s3 import is_s3_path

        assert is_s3_path("/local/path/file.txt") is False

    def test_is_s3_path_empty(self):
        """Empty string returns False."""
        from app.utils.s3 import is_s3_path

        assert is_s3_path("") is False


# ---------------------------------------------------------------------------
# File existence and size
# ---------------------------------------------------------------------------


class TestFileExists:
    """Tests for :func:`app.utils.s3.file_exists`."""

    @patch("app.utils.s3.get_s3_client")
    def test_file_exists_true(self, mock_get_client):
        """Existing object returns True."""
        s3_client = MagicMock()
        mock_get_client.return_value = s3_client

        from app.utils.s3 import file_exists

        result = file_exists("s3://bucket/path/to/file.txt")
        assert result is True
        s3_client.head_object.assert_called_once_with(
            Bucket="bucket", Key="path/to/file.txt"
        )

    @patch("app.utils.s3.get_s3_client")
    def test_file_exists_false(self, mock_get_client):
        """Non-existing object returns False."""
        s3_client = MagicMock()
        s3_client.head_object.side_effect = Exception("Not found")
        mock_get_client.return_value = s3_client

        from app.utils.s3 import file_exists

        result = file_exists("s3://bucket/missing.txt")
        assert result is False


class TestGetFileSize:
    """Tests for :func:`app.utils.s3.get_file_size`."""

    @patch("app.utils.s3.get_s3_client")
    def test_get_file_size(self, mock_get_client):
        """File size is returned from head_object ContentLength."""
        s3_client = MagicMock()
        s3_client.head_object.return_value = {"ContentLength": 1024, "ETag": '"abc"'}
        mock_get_client.return_value = s3_client

        from app.utils.s3 import get_file_size

        size = get_file_size("s3://bucket/file.txt")
        assert size == 1024
        s3_client.head_object.assert_called_once_with(
            Bucket="bucket", Key="file.txt"
        )

    @patch("app.utils.s3.get_s3_client")
    def test_get_file_size_missing_key(self, mock_get_client):
        """Missing ContentLength defaults to 0."""
        s3_client = MagicMock()
        s3_client.head_object.return_value = {}  # no ContentLength key
        mock_get_client.return_value = s3_client

        from app.utils.s3 import get_file_size

        size = get_file_size("s3://bucket/file.txt")
        assert size == 0


# ---------------------------------------------------------------------------
# Pre-signed URLs
# ---------------------------------------------------------------------------


class TestGeneratePresignedUrl:
    """Tests for :func:`app.utils.s3.generate_presigned_url`."""

    @patch("app.utils.s3.get_s3_client")
    def test_generate_presigned_url_default_expiry(self, mock_get_client):
        """Pre-signed URL with default expiry (3600s)."""
        s3_client = MagicMock()
        s3_client.generate_presigned_url.return_value = (
            "https://s3.amazonaws.com/bucket/key?AWSAccessKeyId=..."
        )
        mock_get_client.return_value = s3_client

        from app.utils.s3 import generate_presigned_url

        url = generate_presigned_url("s3://bucket/file.txt")
        assert url.startswith("https://")
        s3_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "bucket", "Key": "file.txt"},
            ExpiresIn=3600,
        )

    @patch("app.utils.s3.get_s3_client")
    def test_generate_presigned_url_custom_expiry(self, mock_get_client):
        """Pre-signed URL with custom expiry."""
        s3_client = MagicMock()
        s3_client.generate_presigned_url.return_value = "https://example.com/presigned"
        mock_get_client.return_value = s3_client

        from app.utils.s3 import generate_presigned_url

        url = generate_presigned_url("s3://bucket/file.txt", expires_in=60)
        assert url == "https://example.com/presigned"
        s3_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "bucket", "Key": "file.txt"},
            ExpiresIn=60,
        )


# ---------------------------------------------------------------------------
# Streaming read
# ---------------------------------------------------------------------------


class TestStreamFile:
    """Tests for :func:`app.utils.s3.stream_file`."""

    @patch("app.utils.s3.get_s3_client")
    async def test_stream_file_yields_chunks(self, mock_get_client):
        """Stream returns bytes chunks from S3 object."""
        s3_client = MagicMock()
        body = MagicMock()
        body.iter_chunks.return_value = [b"chunk1", b"chunk2", b"chunk3"]
        s3_client.get_object.return_value = {"Body": body}
        mock_get_client.return_value = s3_client

        from app.utils.s3 import stream_file

        chunks = []
        async for chunk in stream_file("s3://bucket/file.txt"):
            chunks.append(chunk)

        assert chunks == [b"chunk1", b"chunk2", b"chunk3"]
        s3_client.get_object.assert_called_once_with(
            Bucket="bucket", Key="file.txt"
        )
        body.iter_chunks.assert_called_once_with(chunk_size=8192)

    @patch("app.utils.s3.get_s3_client")
    async def test_stream_file_custom_chunk_size(self, mock_get_client):
        """Custom chunk_size is passed to iter_chunks."""
        s3_client = MagicMock()
        body = MagicMock()
        body.iter_chunks.return_value = [b"data"]
        s3_client.get_object.return_value = {"Body": body}
        mock_get_client.return_value = s3_client

        from app.utils.s3 import stream_file

        async for _ in stream_file("s3://bucket/file.txt", chunk_size=4096):
            pass

        body.iter_chunks.assert_called_once_with(chunk_size=4096)

    @patch("app.utils.s3.get_s3_client")
    async def test_stream_file_closes_body_after_yield(self, mock_get_client):
        """Body is closed after iteration completes."""
        s3_client = MagicMock()
        body = MagicMock()
        body.iter_chunks.return_value = [b"data"]
        s3_client.get_object.return_value = {"Body": body}
        mock_get_client.return_value = s3_client

        from app.utils.s3 import stream_file

        async for _ in stream_file("s3://bucket/file.txt"):
            pass

        body.close.assert_called_once()


# ---------------------------------------------------------------------------
# Object management
# ---------------------------------------------------------------------------


class TestDeleteObject:
    """Tests for :func:`app.utils.s3.delete_object`."""

    @patch("app.utils.s3.get_s3_client")
    def test_delete_object(self, mock_get_client):
        """delete_object calls S3 delete with correct bucket/key."""
        s3_client = MagicMock()
        mock_get_client.return_value = s3_client

        from app.utils.s3 import delete_object

        delete_object("s3://bucket/file.txt")
        s3_client.delete_object.assert_called_once_with(
            Bucket="bucket", Key="file.txt"
        )


class TestListObjects:
    """Tests for :func:`app.utils.s3.list_objects`."""

    @patch("app.utils.s3.get_s3_client")
    def test_list_objects(self, mock_get_client):
        """list_objects returns contents from S3."""
        s3_client = MagicMock()
        s3_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "file1.txt", "Size": 100},
                {"Key": "file2.txt", "Size": 200},
            ]
        }
        mock_get_client.return_value = s3_client

        from app.utils.s3 import list_objects

        objects = list_objects("s3://bucket/prefix/")
        assert len(objects) == 2
        assert objects[0]["Key"] == "file1.txt"
        s3_client.list_objects_v2.assert_called_once_with(
            Bucket="bucket", Prefix="prefix/", MaxKeys=1000
        )

    @patch("app.utils.s3.get_s3_client")
    def test_list_objects_custom_max_keys(self, mock_get_client):
        """Custom max_keys is passed to S3."""
        s3_client = MagicMock()
        s3_client.list_objects_v2.return_value = {"Contents": []}
        mock_get_client.return_value = s3_client

        from app.utils.s3 import list_objects

        list_objects("s3://bucket/prefix/", max_keys=100)
        s3_client.list_objects_v2.assert_called_once_with(
            Bucket="bucket", Prefix="prefix/", MaxKeys=100
        )

    @patch("app.utils.s3.get_s3_client")
    def test_list_objects_empty(self, mock_get_client):
        """Bucket with no objects returns empty list."""
        s3_client = MagicMock()
        s3_client.list_objects_v2.return_value = {}  # no "Contents"
        mock_get_client.return_value = s3_client

        from app.utils.s3 import list_objects

        objects = list_objects("s3://bucket/empty/")
        assert objects == []
