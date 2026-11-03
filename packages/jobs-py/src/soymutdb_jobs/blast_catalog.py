"""Public BLAST source attribution shared by API discovery and index manifests.

This validates metadata without fetching URLs or performing DNS lookups. It is
not an HTTP fetch policy and cannot prove a domain resolves to a public address.
"""
from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit


def public_source_url(value: object) -> str | None:
    """Omit private paths, credential URLs and known private authorities."""
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or bool(parsed.query)
            or bool(parsed.fragment)
            or "\\" in value
            or "." not in host
            or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid"))
        ):
            return None
        _ = parsed.port
        try:
            address = ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            return None
        return value
    except ValueError:
        return None
