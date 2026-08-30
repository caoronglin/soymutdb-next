"""Privacy and proxy-boundary contracts for analytics collection."""

from __future__ import annotations

from types import SimpleNamespace

from starlette.requests import Request


def _request(*, peer_ip: str, xff: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": "/api/v1/track.gif",
            "query_string": b"",
            "headers": headers,
            "client": (peer_ip, 443),
            "server": ("api.example.test", 443),
        }
    )


def test_client_ip_ignores_spoofed_xff_from_direct_peer(monkeypatch) -> None:
    from app.api.v1 import analytics

    monkeypatch.setattr(
        analytics,
        "get_settings",
        lambda: SimpleNamespace(analytics_trusted_proxy_ips=()),
    )

    assert analytics._client_ip(_request(peer_ip="198.51.100.7", xff="203.0.113.9")) == "198.51.100.7"


def test_client_ip_accepts_first_xff_value_from_configured_proxy(monkeypatch) -> None:
    from app.api.v1 import analytics

    monkeypatch.setattr(
        analytics,
        "get_settings",
        lambda: SimpleNamespace(analytics_trusted_proxy_ips=("10.0.0.5",)),
    )

    assert analytics._client_ip(
        _request(peer_ip="10.0.0.5", xff="203.0.113.9, 10.0.0.4")
    ) == "203.0.113.9"


def test_hash_ip_changes_when_salt_changes() -> None:
    from app.services.analytics_service import hash_ip

    assert hash_ip("203.0.113.9", "a" * 32) != hash_ip("203.0.113.9", "b" * 32)
