"""Origin verification for state-changing auth endpoints (CSRF defence).

The refresh token travels in an HttpOnly + SameSite=Lax cookie.  SameSite
alone is not a complete CSRF defence, so ``refresh`` and ``logout`` also
require an ``Origin`` (or, failing that, a ``Referer``) header that matches
either the API's own origin or a configured CORS origin.

Policy: requests with **no** ``Origin``/``Referer`` header are **rejected**.
Legacy non-browser clients that do not send ``Origin`` must adopt cookie
handling and send the header; there is no relaxed compatibility mode.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request

from .config import Settings
from .exceptions import AuthenticationError


def _is_trusted_origin(origin: str, request: Request, settings: Settings) -> bool:
    """Return True when *origin* is same-origin with the API or CORS-listed."""
    own_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin == own_origin:
        return True
    if origin in settings.cors_origins:
        return True
    return False


def _referer_origin(referer: str) -> str | None:
    """Normalise a Referer URL into its scheme://netloc origin."""
    parts = urlsplit(referer.strip())
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return None


def validate_request_origin(request: Request, settings: Settings) -> None:
    """Reject auth state changes whose origin cannot be verified.

    Raises :class:`AuthenticationError` when the ``Origin`` (or ``Referer``)
    header is missing, malformed, or not trusted.
    """
    origin = request.headers.get("origin")
    if origin:
        origin = origin.strip()
        if origin and _is_trusted_origin(origin, request, settings):
            return
        raise AuthenticationError("Request origin is not allowed")

    referer = request.headers.get("referer")
    if referer:
        ref_origin = _referer_origin(referer)
        if ref_origin and _is_trusted_origin(ref_origin, request, settings):
            return
        raise AuthenticationError("Request origin is not allowed")

    # Neither Origin nor Referer present — reject instead of guessing.
    raise AuthenticationError(
        "Request origin could not be verified; refresh/logout require an "
        "Origin or Referer header"
    )


__all__ = ["validate_request_origin"]
