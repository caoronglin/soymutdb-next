"""Reproducible gzip bodies for pre-rendered gene artifacts.

_upload_gzipped writes .json.gz / .html.gz objects whose content digest is
what downstream caches key on.  The default gzip header mtime is the wall
clock at compression time, so two rebuilds of byte-identical content produced
different objects and defeated digest reuse.  Pinning mtime makes the
compression step a pure function of its input.

These tests pin the reproducibility property plus the wire-format contract that
must survive the change: the body is still valid gzip, still round-trips to the
original bytes, and still carries the same ContentType / ContentEncoding /
object key passed by the caller.
"""

from __future__ import annotations

import gzip
import hashlib

from soymutdb_worker.tasks.static_pages import _upload_gzipped


class RecordingS3Client:
    """Minimal stand-in that captures the put_object call for assertions."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def put_object(self, **kwargs) -> None:
        self.calls.append(kwargs)


def test_same_input_yields_identical_body() -> None:
    payload = b'<html><body>Glyma.01G000100</body></html>' * 64
    client = RecordingS3Client()

    _upload_gzipped(
        client, "static-assets", "7/1/genes/Glyma.01G000100.html.gz", payload, "text/html"
    )
    _upload_gzipped(
        client, "static-assets", "7/1/genes/Glyma.01G000100.html.gz", payload, "text/html"
    )

    first, second = client.calls
    assert first["Body"] == second["Body"]
    # The digest is what downstream caches key on; it must not drift per build.
    assert hashlib.sha256(first["Body"]).hexdigest() == hashlib.sha256(second["Body"]).hexdigest()
    # And the pinned header mtime really is zero, not merely stable.
    assert first["Body"][4:8] == b"\x00\x00\x00\x00"


def test_body_round_trips_and_preserves_headers_and_key() -> None:
    payload = b'{"accession": "Glyma.01G000100", "assembly_id": 1}'
    client = RecordingS3Client()

    _upload_gzipped(
        client, "static-assets", "7/1/genes/Glyma.01G000100.json.gz", payload, "application/json"
    )

    (call,) = client.calls
    assert gzip.decompress(call["Body"]) == payload
    assert call["Bucket"] == "static-assets"
    assert call["Key"] == "7/1/genes/Glyma.01G000100.json.gz"
    assert call["ContentType"] == "application/json"
    assert call["ContentEncoding"] == "gzip"


def test_distinct_inputs_still_produce_distinct_bodies() -> None:
    client = RecordingS3Client()

    _upload_gzipped(client, "b", "k.json.gz", b"first", "application/json")
    _upload_gzipped(client, "b", "k.json.gz", b"second", "application/json")

    assert client.calls[0]["Body"] != client.calls[1]["Body"]
