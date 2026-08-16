"""Generic HTTP client for publication adapters (stdlib only).

Uses ``urllib.request`` so the worker image does not gain an ``httpx``/
``requests`` dependency.  A test double can monkeypatch ``request_json`` /
``post_json`` to simulate remote targets.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
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


__all__ = ["AdapterHttpError", "post_json", "request_json"]
