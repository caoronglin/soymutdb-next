"""Redis-backed, fixed-window limits for sensitive request paths.

The limiters use an atomic Redis Lua script and aligned fixed windows.
The script increments the counter and sets the window expiry in one Redis
operation, so concurrent API workers share the same limit. Development
environments use a process-local fallback during a Redis outage; non-dev
environments fail closed so an outage cannot silently disable brute-force
protection.

The module also owns the *global* inbound request limiter
(:class:`RequestRateLimiter`) that is wired into the ASGI stack by
``app/main.py``.  Its budget is graded per request class: anonymous public
reads fail **open** while the backend is unavailable (public data
availability first, the nginx edge ``limit_req`` stays the backstop) and
writes fail **closed** with 503 (an unverified write budget must never
become an unbounded write path).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable
from ipaddress import ip_address
from typing import Any

from starlette.requests import Request

from .config import Settings, get_settings
from .database import get_redis
from .exceptions import RateLimitExceededError, ServiceUnavailableError
from .security import decode_token

logger = logging.getLogger(__name__)

_FIXED_WINDOW_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""

#: Bucket for anonymous public reads (GET/HEAD without a verified principal).
REQUEST_BUCKET_PUBLIC_READ = "public-read"
#: Bucket for write operations (POST/PUT/PATCH/DELETE).
REQUEST_BUCKET_WRITE = "write"

#: Request methods that consume the write budget.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: Request methods that can consume the anonymous-read budget.
READ_METHODS = frozenset({"GET", "HEAD"})

#: Path prefixes that are never rate limited.  The liveness/readiness probes
#: and the Prometheus scrape endpoint must stay reachable during a traffic
#: spike.  The API's own probes live under ``{api_v1_prefix}/health`` (the
#: container ``HEALTHCHECK`` calls ``/api/v1/health/live``), and the mounted
#: Prometheus application is served under ``/metrics/``.
EXEMPT_PATH_PREFIXES = ("/health", "/metrics")

#: Length of the fixed window used by the global request limiter.
REQUEST_RATE_LIMIT_WINDOW_SECONDS = 60

#: Upper bound for every process-local fallback counter. Both limiter
#: families go through :func:`_bound_fallback_counts`, which hard caps the
#: map so a burst of distinct peers cannot grow the process heap.
FALLBACK_MAX_KEYS = 2048


def _default_redis_getter() -> Any:
    """Return the shared Redis client.

    Late bound on purpose: a test can replace ``ratelimit.get_redis`` and the
    module-level singletons below pick the replacement up.
    """
    return get_redis()


def _default_settings_getter() -> Settings:
    """Return the shared settings (late bound, see :func:`_default_redis_getter`)."""
    return get_settings()


def _bound_fallback_counts(
    counts: dict[str, tuple[int, int]], window_number: int
) -> dict[str, tuple[int, int]]:
    """Prune stale windows and hard-cap the process-local fallback map.

    Both the login-family limiters and the global request limiter share this
    fallback. A Redis outage in dev creates one key per distinct identity or
    peer *inside the same window*, so dropping previous windows alone cannot
    bound the heap: an unconditional cap is required. Keeping the algorithm in
    one place stops the two copies from drifting apart again.
    """
    if len(counts) <= FALLBACK_MAX_KEYS:
        return counts
    bounded = {key: value for key, value in counts.items() if value[0] >= window_number - 1}
    if len(bounded) > FALLBACK_MAX_KEYS:
        bounded = dict(list(bounded.items())[-FALLBACK_MAX_KEYS:])
    return bounded


def resolve_trusted_peer_ip(request: Request, trusted_proxies: Iterable[str]) -> str:
    """Return the client address used as the rate-limit key.

    A direct untrusted peer cannot supply forwarding metadata. For a trusted
    peer, walk the forwarded chain from right to left and stop at the first
    untrusted hop. Nginx appends the actual peer with proxy_add_x_forwarded_for;
    trusting the first element would let a caller prepend any budget key.
    Invalid addresses fail safe to the direct peer rather than granting a
    caller-controlled bucket.
    """
    peer_ip = request.client.host if request.client and request.client.host else ""
    forwarded = request.headers.get("x-forwarded-for")
    trusted = set(trusted_proxies)
    if forwarded and peer_ip in trusted:
        candidate = peer_ip
        for hop in reversed(forwarded.split(",")):
            if candidate not in trusted:
                break
            try:
                candidate = str(ip_address(hop.strip()))
            except ValueError:
                return peer_ip
        return candidate
    return peer_ip or "unknown"


def has_authenticated_principal(request: Request) -> bool:
    """Return whether the request carries a verifiable authenticated principal.

    Rule (the middleware runs before routing, so the principal is resolved
    from the request itself):

    * the request must present an ``Authorization: Bearer <token>`` header;
    * the token must be a valid, unexpired **access** token signed with the
      deployment's JWT secret.

    Anything else - a missing header, a non-Bearer scheme, a malformed or
    expired token - counts as *anonymous*.  The check is deliberately strict
    so a caller cannot opt out of the anonymous-read budget by sending a
    bogus ``Authorization`` header.  A token that is cryptographically valid
    but belongs to a deleted or inactive user is still "authenticated" here;
    the route's own dependency rejects such a request with 401 afterwards.
    """
    header = request.headers.get("authorization")
    if not header:
        return False
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return False
    token = token.strip()
    if not token:
        return False
    try:
        payload = decode_token(token)
    except Exception:
        # Any decoding problem (malformed, wrong signature, expired) simply
        # means "no principal" - it must never fail the request itself.
        return False
    return payload.get("type") == "access"


def is_exempt_path(path: str, *, settings: Settings) -> bool:
    """Return whether *path* is a probe or scrape endpoint.

    Exempt are ``/health`` (and its sub paths), ``/metrics`` (and its sub
    paths, the Prometheus application is mounted with a trailing slash) and
    the API's own health router under ``{api_v1_prefix}/health`` - the
    container ``HEALTHCHECK`` calls ``/api/v1/health/live`` and a rate
    limited probe would restart healthy instances.
    """
    prefixes = (
        *EXEMPT_PATH_PREFIXES,
        f"{settings.api_v1_prefix.rstrip('/')}/health",
    )
    for prefix in prefixes:
        if path == prefix or path.startswith(f"{prefix}/"):
            return True
    return False


def classify_request(request: Request, *, settings: Settings) -> str | None:
    """Return the rate-limit bucket for *request*, or ``None`` to skip it.

    The classification rules are:

    * the probe/scrape endpoints are exempt (see :func:`is_exempt_path`).
    * ``POST {api_v1_prefix}/auth/login`` keeps its dedicated
      :class:`LoginRateLimiter` and is not counted twice. Other auth writes
      (registration, refresh, logout and password changes) have no dedicated
      budget and must still consume the global write budget.
    * ``POST``/``PUT``/``PATCH``/``DELETE`` consume the write budget.
    * ``GET``/``HEAD`` consume the anonymous-read budget **only** when the
      request carries no authenticated principal; an authenticated read is
      not part of the anonymous budget.
    * every other method (``OPTIONS`` preflight, ...) is not limited.
    """
    path = request.url.path
    if is_exempt_path(path, settings=settings):
        return None

    method = request.method.upper()
    login_path = f"{settings.api_v1_prefix.rstrip('/')}/auth/login"
    if method == "POST" and path.rstrip("/") == login_path:
        return None
    if method in WRITE_METHODS:
        return REQUEST_BUCKET_WRITE
    if method in READ_METHODS and not has_authenticated_principal(request):
        return REQUEST_BUCKET_PUBLIC_READ
    return None


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

            self._fallback_counts = _bound_fallback_counts(
                self._fallback_counts, window_number
            )

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
        """Consume one login attempt or raise a controlled API exception.

        Two budgets are consumed: the per-(username, IP) pair (the original
        behaviour) and a per-IP budget that spans usernames. Without the
        second, an attacker rotating the username gets a fresh counter for
        every pair and the per-pair limit never bounds the source address.
        """
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
        await self._enforce(
            identity=None,
            client_ip=client_ip,
            window=settings.login_rate_limit_window,
            maximum=settings.login_ip_rate_limit_max,
            namespace="login-ip",
            unavailable_message="Login rate limiter is unavailable; please try again later",
            exceeded_message="Too many login attempts from this network. Please retry later.",
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


class PublicBlastRateLimiter(LoginRateLimiter):
    """Dedicated per-peer budget for resource-consuming anonymous searches."""

    async def enforce(self, *, client_ip: str | None) -> None:  # type: ignore[override]
        settings = self._settings_getter()
        await self._enforce(
            identity=None,
            client_ip=client_ip,
            window=settings.blast_public_rate_limit_window,
            maximum=settings.blast_public_rate_limit_max,
            namespace="blast-public-submit",
            unavailable_message="Public BLAST submission quota is unavailable; retry later",
            exceeded_message="Too many public BLAST submissions. Please retry later.",
        )


public_blast_rate_limiter = PublicBlastRateLimiter(
    redis_getter=_default_redis_getter, settings_getter=_default_settings_getter
)


login_rate_limiter = LoginRateLimiter()
external_article_preview_rate_limiter = ExternalArticlePreviewRateLimiter()


class RequestRateLimiter:
    """Graded per-peer request budgets for the global inbound limiter.

    Two budgets are maintained, both keyed by the *trusted* peer address
    (see :func:`resolve_trusted_peer_ip`) and both using a shared, aligned
    one-minute fixed window:

    ``REQUEST_BUCKET_PUBLIC_READ``
        Anonymous ``GET``/``HEAD`` requests.  While the backend is
        unavailable the bucket **fails open**: the request is served, because
        public data availability comes first and the nginx edge
        ``limit_req`` stays the backstop.  The process-local fallback
        counter keeps recording the peer's volume (bounded, see
        :attr:`fallback_key_count`) so an outage is still observable, but it
        never rejects a read.

    ``REQUEST_BUCKET_WRITE``
        ``POST``/``PUT``/``PATCH``/``DELETE`` requests.  While the backend
        is unavailable the bucket **fails closed** with
        :class:`ServiceUnavailableError` (HTTP 503): an unverified write
        budget must never degrade into an unbounded write path.
    """

    def __init__(
        self,
        *,
        redis_getter: Callable[[], Any] = _default_redis_getter,
        settings_getter: Callable[[], Settings] = _default_settings_getter,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._redis_getter = redis_getter
        self._settings_getter = settings_getter
        self._clock = clock
        self._fallback_counts: dict[str, tuple[int, int]] = {}
        self._fallback_lock = asyncio.Lock()

    @property
    def settings(self) -> Settings:
        """Return the currently effective settings."""
        return self._settings_getter()

    @property
    def fallback_key_count(self) -> int:
        """Return the number of tracked process-local fallback keys."""
        return len(self._fallback_counts)

    @staticmethod
    def _key(
        *,
        bucket: str,
        peer_ip: str,
        window: int,
        now: float,
    ) -> tuple[str, int]:
        """Return the shared window key and the remaining seconds of it."""
        window_number = int(now // window)
        window_remaining = max(1, window - int(now % window))
        return (
            f"soymutdb:request-ratelimit:{bucket}:ip:{peer_ip}:window:{window_number}",
            window_remaining,
        )

    async def _fallback_increment(
        self,
        key: str,
        *,
        window: int,
        now: float,
    ) -> tuple[int, int]:
        """Increment the bounded process-local fallback counter.

        The pruning pattern mirrors
        :meth:`LoginRateLimiter._fallback_increment`: counters from older
        windows are dropped first and the map is then hard capped, so the
        process heap stays bounded even when an outage exposes the limiter
        to a flood of distinct peers.
        """
        window_number = int(now // window)
        async with self._fallback_lock:
            previous_window, previous_count = self._fallback_counts.get(
                key, (window_number, 0)
            )
            count = previous_count + 1 if previous_window == window_number else 1
            self._fallback_counts[key] = (window_number, count)

            self._fallback_counts = _bound_fallback_counts(
                self._fallback_counts, window_number
            )

        retry_after = max(1, window - int(now % window))
        return count, retry_after

    def _maximum_for(self, bucket: str, settings: Settings) -> int:
        """Return the per-minute budget of *bucket*."""
        if bucket == REQUEST_BUCKET_WRITE:
            return max(1, int(settings.write_rate_limit_per_minute))
        return max(1, int(settings.public_read_rate_limit_per_minute))

    async def _consume(
        self,
        *,
        bucket: str,
        peer_ip: str,
        settings: Settings,
    ) -> None:
        """Consume one unit of the *bucket* budget for *peer_ip*."""
        maximum = self._maximum_for(bucket, settings)
        window = REQUEST_RATE_LIMIT_WINDOW_SECONDS
        now = self._clock()
        key, window_remaining = self._key(
            bucket=bucket,
            peer_ip=peer_ip,
            window=window,
            now=now,
        )

        try:
            redis = self._redis_getter()
            result = await redis.eval(_FIXED_WINDOW_SCRIPT, 1, key, window_remaining)
            count = int(result[0])
            retry_after = max(1, int(result[1]))
        except Exception as exc:
            if bucket == REQUEST_BUCKET_WRITE:
                logger.error(
                    "write_rate_limit_redis_unavailable_fail_closed peer=%s: %s",
                    peer_ip,
                    exc,
                )
                raise ServiceUnavailableError(
                    "Write rate limiter is unavailable; please try again later"
                ) from exc

            # Anonymous public reads fail OPEN: the request is served, the
            # nginx edge limiter remains the backstop.  The bounded
            # process-local counter only records the volume.
            logger.warning(
                "public_read_rate_limit_redis_unavailable_fail_open peer=%s: %s",
                peer_ip,
                exc,
            )
            count, _retry_after = await self._fallback_increment(
                key,
                window=window,
                now=now,
            )
            if count > maximum:
                logger.warning(
                    "public_read_rate_limit_degraded_budget_exceeded peer=%s "
                    "count=%s limit=%s",
                    peer_ip,
                    count,
                    maximum,
                )
            return

        if count > maximum:
            raise RateLimitExceededError(
                "Too many requests. Please retry later.",
                retry_after=retry_after,
                details={"retry_after": retry_after},
            )

    async def check(self, request: Request) -> None:
        """Consume the request's budget or raise a domain error.

        Raises:
            RateLimitExceededError: the peer exceeded its budget (HTTP 429,
                with a ``Retry-After`` header).
            ServiceUnavailableError: a write budget could not be verified
                because the limiter backend is unavailable (HTTP 503).
        """
        settings = self.settings
        if not settings.rate_limit_enabled:
            return
        bucket = classify_request(request, settings=settings)
        if bucket is None:
            return
        peer_ip = resolve_trusted_peer_ip(
            request,
            settings.analytics_trusted_proxy_ips,
        )
        await self._consume(bucket=bucket, peer_ip=peer_ip, settings=settings)


request_rate_limiter = RequestRateLimiter()


__all__ = [
    "EXEMPT_PATH_PREFIXES",
    "FALLBACK_MAX_KEYS",
    "ExternalArticlePreviewRateLimiter",
    "LoginRateLimiter",
    "PublicBlastRateLimiter",
    "READ_METHODS",
    "REQUEST_BUCKET_PUBLIC_READ",
    "REQUEST_BUCKET_WRITE",
    "REQUEST_RATE_LIMIT_WINDOW_SECONDS",
    "RequestRateLimiter",
    "WRITE_METHODS",
    "classify_request",
    "external_article_preview_rate_limiter",
    "has_authenticated_principal",
    "is_exempt_path",
    "login_rate_limiter",
    "request_rate_limiter",
    "public_blast_rate_limiter",
    "resolve_trusted_peer_ip",
]
