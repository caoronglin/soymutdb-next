"""Redis-backed, fixed-window limits for sensitive request paths.

The limiters use an atomic Redis Lua script and aligned fixed windows.
The script increments the counter and sets the window expiry in one Redis
operation, so concurrent API workers share the same limit. Development
environments use a process-local fallback during a Redis outage; non-dev
environments fail closed so an outage cannot silently disable brute-force
protection.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from .config import Settings, get_settings
from .database import get_redis
from .exceptions import RateLimitExceededError, ServiceUnavailableError

logger = logging.getLogger(__name__)

_FIXED_WINDOW_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""


class LoginRateLimiter:
    """Enforce a shared fixed-window limit for login requests."""

    def __init__(
        self,
        *,
        redis_getter: Callable[[], Any] = get_redis,
        settings_getter: Callable[[], Settings] = get_settings,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._redis_getter = redis_getter
        self._settings_getter = settings_getter
        self._clock = clock
        self._fallback_counts: dict[str, tuple[int, int]] = {}
        self._fallback_lock = asyncio.Lock()

    @staticmethod
    def _normalize_username(username: str | None) -> str | None:
        """Normalize the login identifier without changing its meaning."""
        if username is None:
            return None
        normalized = username.strip().lower()
        return normalized or None

    @staticmethod
    def _normalize_ip(client_ip: str | None) -> str:
        normalized = (client_ip or "").strip()
        return normalized or "unknown"

    def _key(
        self,
        *,
        username: str | None,
        client_ip: str | None,
        window: int,
        now: float,
        namespace: str = "login",
    ) -> tuple[str, int]:
        normalized_username = self._normalize_username(username)
        normalized_ip = self._normalize_ip(client_ip)
        identity = (
            f"user:{normalized_username}"
            if normalized_username is not None
            else f"ip:{normalized_ip}"
        )
        window_number = int(now // window)
        window_remaining = max(1, window - int(now % window))
        return (
            f"soymutdb:{namespace}:ratelimit:{identity}:ip:{normalized_ip}:window:{window_number}",
            window_remaining,
        )

    async def _fallback_increment(
        self,
        key: str,
        *,
        window: int,
        now: float,
    ) -> tuple[int, int]:
        """Increment the process-local fallback counter for the current window."""
        window_number = int(now // window)
        async with self._fallback_lock:
            previous_window, previous_count = self._fallback_counts.get(
                key, (window_number, 0)
            )
            count = previous_count + 1 if previous_window == window_number else 1
            self._fallback_counts[key] = (window_number, count)

            # Bound memory if a development process receives many distinct keys.
            if len(self._fallback_counts) > 2048:
                self._fallback_counts = {
                    stored_key: value
                    for stored_key, value in self._fallback_counts.items()
                    if value[0] >= window_number - 1
                }

        retry_after = max(1, window - int(now % window))
        return count, retry_after

    async def _enforce(
        self,
        *,
        identity: str | None,
        client_ip: str | None,
        window: int,
        maximum: int,
        namespace: str,
        unavailable_message: str,
        exceeded_message: str,
    ) -> None:
        """Consume one shared fixed-window budget or raise a controlled error."""
        settings = self._settings_getter()
        window = max(1, int(window))
        maximum = max(1, int(maximum))
        now = self._clock()
        key, window_remaining = self._key(
            username=identity,
            client_ip=client_ip,
            window=window,
            now=now,
            namespace=namespace,
        )

        try:
            redis = self._redis_getter()
            result = await redis.eval(_FIXED_WINDOW_SCRIPT, 1, key, window_remaining)
            count = int(result[0])
            retry_after = max(1, int(result[1]))
        except Exception as exc:
            if settings.app_env == "dev":
                logger.warning(
                    "%s_rate_limit_redis_unavailable_dev_fallback: %s", namespace, exc
                )
                count, retry_after = await self._fallback_increment(
                    key,
                    window=window,
                    now=now,
                )
            else:
                logger.error(
                    "%s_rate_limit_redis_unavailable_fail_closed app_env=%s: %s",
                    namespace,
                    settings.app_env,
                    exc,
                )
                raise ServiceUnavailableError(unavailable_message) from exc

        if count > maximum:
            raise RateLimitExceededError(
                exceeded_message,
                retry_after=retry_after,
                details={"retry_after": retry_after},
            )

    async def enforce(self, *, username: str | None, client_ip: str | None) -> None:
        """Consume one login attempt or raise a controlled API exception."""
        settings = self._settings_getter()
        await self._enforce(
            identity=username,
            client_ip=client_ip,
            window=settings.login_rate_limit_window,
            maximum=settings.login_rate_limit_max,
            namespace="login",
            unavailable_message="Login rate limiter is unavailable; please try again later",
            exceeded_message="Too many login attempts. Please retry later.",
        )


class ExternalArticlePreviewRateLimiter(LoginRateLimiter):
    """Limit expensive external fetch previews per authenticated editor and IP."""

    async def enforce(self, *, user_id: str, client_ip: str | None) -> None:  # type: ignore[override]
        settings = self._settings_getter()
        await self._enforce(
            identity=user_id,
            client_ip=client_ip,
            window=settings.external_article_preview_rate_limit_window,
            maximum=settings.external_article_preview_rate_limit_max,
            namespace="external-article-preview",
            unavailable_message=(
                "External article preview rate limiter is unavailable; please try again later"
            ),
            exceeded_message="Too many external article previews. Please retry later.",
        )


login_rate_limiter = LoginRateLimiter()
external_article_preview_rate_limiter = ExternalArticlePreviewRateLimiter()


__all__ = [
    "ExternalArticlePreviewRateLimiter",
    "LoginRateLimiter",
    "external_article_preview_rate_limiter",
    "login_rate_limiter",
]
