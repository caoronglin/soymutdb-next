"""Generic HTTP client for publication adapters (stdlib only).

Uses ``urllib.request`` so the worker image does not gain an ``httpx``/
``requests`` dependency.  A test double can monkeypatch ``request_json`` /
``post_json`` to simulate remote targets.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from typing import Any


class AdapterHttpError(RuntimeError):
    def __init__(self, status: int, body: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def _do(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = {**(headers or {}), "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise AdapterHttpError(exc.code, detail, f"{method} {url} failed ({exc.code})") from exc
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}


def _encode_multipart(
    fields: dict[str, str],
    files: list[tuple[str, str, bytes, str]],
    boundary: str,
) -> bytes:
    """Encode a ``multipart/form-data`` body.

    ``files`` entries are ``(field_name, filename, content, content_type)``. The
    file *content* is what makes this usable by a direct-upload API: a body that
    carried only paths would describe files the remote host cannot read.
    """
    out = bytearray()
    for name, value in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += value.encode("utf-8") + b"\r\n"
    for field_name, filename, content, content_type in files:
        out += f"--{boundary}\r\n".encode()
        out += (
            f'Content-Disposition: form-data; name="{field_name}"; '
            f'filename="{filename}"\r\n'
        ).encode()
        out += f"Content-Type: {content_type}\r\n\r\n".encode()
        out += content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out)


def post_multipart(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    fields: dict[str, str] | None = None,
    files: list[tuple[str, str, bytes, str]] | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    """POST a ``multipart/form-data`` body and decode the JSON response."""
    boundary = f"----soymutdb{uuid.uuid4().hex}"
    payload = _encode_multipart(fields or {}, files or [], boundary)
    request_headers = {
        **(headers or {}),
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(payload)),
    }
    req = urllib.request.Request(url, data=payload, method="POST", headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise AdapterHttpError(
            exc.code, detail, f"POST {url} failed ({exc.code})"
        ) from exc
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}


def request_json(
    url: str, *, headers: dict[str, str] | None = None, timeout: int = 60
) -> dict[str, Any]:
    return _do("GET", url, headers=headers, timeout=timeout)


def post_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    return _do("POST", url, headers=headers, body=body, timeout=timeout)


__all__ = [
    "AdapterHttpError",
    "post_json",
    "post_multipart",
    "request_json",
]
