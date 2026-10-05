"""access_token acquisition and caching — W5.

## The constraint that shapes this module

The official server-API documentation states that `gettoken` must not be called
frequently — repeated calls are rate-limited. A naive implementation caches the
token and is then technically correct and practically broken: the first request
after expiry, from every concurrent worker, all miss the cache at the same
instant and all call `gettoken`. With enough workers that burst is exactly the
pattern the rate limiter exists to stop, and the recovery is a cooldown during
which nothing syncs.

So refresh is single-flight. One thread fetches; the rest wait on it and then
read the same token. The early-refresh window exists for the same reason: a
token that expires while a request is in flight produces a confusing mid-batch
failure, and refreshing ahead of the deadline avoids it.

## Confirmed vs. assumed

Confirmed from the official documentation:

* `GET https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=ID&corpsecret=SECRET`
* the response carries `errcode`/`errmsg` on failure;
* a response body without `errcode` is a success, and the token arrives as
  `access_token` plus `expires_in` seconds.

**Not** confirmed and therefore a module constant rather than a discovered
fact: the safe-margin policy. The observed lifetime is 7200s, but the exact
expiry semantics under clock skew are not something this code has verified
against a live tenant. `REFRESH_MARGIN_SECONDS` is the knob to turn if the
tenant behaves differently.

## Credentials

`corpsecret` is read from the environment and never stored, logged or included
in an exception. `TokenProvider.describe()` is the only sanctioned way to see
the configuration state, and it reports presence rather than value.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from .policy import redact

logger = logging.getLogger(__name__)

TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"

# Refresh this far ahead of the stated expiry. Unverified against a live tenant;
# see the module docstring.
REFRESH_MARGIN_SECONDS = 300


class TokenError(RuntimeError):
    """Token acquisition failed. The message never contains a secret."""


class TokenTransport(Protocol):
    """Performs the raw HTTP call. Injected so this module stays testable."""

    def fetch(self, url: str, *, timeout: float) -> str: ...


@dataclass(frozen=True)
class CachedToken:
    value: str
    expires_at: float

    def is_usable(self, now: float, *, margin: float = REFRESH_MARGIN_SECONDS) -> bool:
        return now < self.expires_at - margin


class UrllibTokenTransport:
    """Standard-library transport, matching the worker's existing HTTP style.

    `soymutdb_worker/utils/wecom_bot.py` uses `urllib` rather than adding an
    HTTP client dependency, and this keeps that property for the server API too.
    """

    def __init__(self, timeout: float = 4.0) -> None:
        self._timeout = timeout

    def fetch(self, url: str, *, timeout: float | None = None) -> str:
        from urllib.request import urlopen  # imported late: keeps module import cheap

        with urlopen(url, timeout=timeout or self._timeout) as response:  # noqa: S310
            return response.read().decode("utf-8")


class TokenProvider:
    """Caches one tenant's access_token and refreshes it at most once at a time."""

    def __init__(
        self,
        *,
        corpid: str | None,
        corpsecret: str | None,
        transport: TokenTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        margin: float = REFRESH_MARGIN_SECONDS,
    ) -> None:
        self._corpid = corpid
        self._corpsecret = corpsecret
        self._transport = transport
        self._clock = clock
        self._margin = margin
        self._cached: CachedToken | None = None
        self._lock = threading.Lock()
        self._fetch_count = 0

    @property
    def configured(self) -> bool:
        return bool(self._corpid and self._corpsecret)

    @property
    def fetch_count(self) -> int:
        """How many times `gettoken` was actually called. Asserted in tests."""
        return self._fetch_count

    def get(self) -> str:
        """Return a usable token, refreshing at most once across concurrent callers."""
        if not self.configured:
            raise TokenError("WeCom credentials are not configured; integration is disabled")

        now = self._clock()
        cached = self._cached
        if cached is not None and cached.is_usable(now, margin=self._margin):
            return cached.value

        with self._lock:
            # Re-check under the lock: a concurrent caller may have refreshed
            # while this one waited. Without this, a burst of N workers would
            # still produce N calls, just serialised.
            now = self._clock()
            cached = self._cached
            if cached is not None and cached.is_usable(now, margin=self._margin):
                return cached.value
            token = self._fetch(now)
            self._cached = token
            return token.value

    def invalidate(self) -> None:
        """Drop the cache so the next call re-fetches.

        For a `40001`-class rejection, which means the token was invalidated
        server-side rather than merely expired.
        """
        with self._lock:
            self._cached = None

    def _fetch(self, now: float) -> CachedToken:
        assert self._corpid is not None and self._corpsecret is not None  # guarded by `configured`
        query = urlencode({"corpid": self._corpid, "corpsecret": self._corpsecret})
        url = f"{TOKEN_URL}?{query}"
        self._fetch_count += 1
        try:
            raw = (self._transport or UrllibTokenTransport()).fetch(url, timeout=4.0)
        except Exception as exc:  # noqa: BLE001 - transport errors vary by implementation
            # The URL carries the secret, so it is never interpolated here.
            raise TokenError(f"access_token request failed: {redact(str(exc))}") from None

        try:
            body: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            raise TokenError("access_token response was not JSON") from None

        errcode = body.get("errcode")
        if errcode:
            message = redact(str(body.get("errmsg", "")))
            raise TokenError(f"access_token refused: errcode={errcode} errmsg={message}")

        value = body.get("access_token")
        if not isinstance(value, str) or not value:
            raise TokenError("access_token response carried no token")

        expires_in = body.get("expires_in")
        lifetime = float(expires_in) if isinstance(expires_in, int | float) else 7200.0
        return CachedToken(value=value, expires_at=now + lifetime)

    def describe(self) -> dict[str, object]:
        """Configuration state for health checks. Reports presence, never value."""
        return {
            "configured": self.configured,
            "cached": self._cached is not None,
            "fetches": self._fetch_count,
        }
