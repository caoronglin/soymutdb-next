"""ASGI middleware: request-id propagation, timing, rate limiting, metrics."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from structlog import get_logger
from structlog.contextvars import bind_contextvars, clear_contextvars

from .config import get_settings
from .database import get_redis
from .metrics import REQUEST_COUNT, REQUEST_LATENCY, update_db_pool_metrics

logger = get_logger(__name__)
settings = get_settings()

# Path normalization for the Prometheus ``endpoint`` label.  User middleware
# runs outside the router (scope["route"] is not available yet), so we
# normalize the raw path instead of using the matched route template.
# High-cardinality identifiers (UUIDs, numeric IDs, long tokens) are replaced
# with placeholders — never expose user/gene/job IDs as labels.
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
_NUMERIC_RE = re.compile(r"^\d+$")
_TOKEN_RE = re.compile(r"^[0-9a-zA-Z]{16,}$")


def normalize_metrics_path(path: str) -> str:
    """Return a low-cardinality label-safe version of ``path``."""
    parts = path.strip("/").split("/")
    normalized = []
    for part in parts:
        if _UUID_RE.fullmatch(part):
            normalized.append("{uuid}")
        elif _NUMERIC_RE.fullmatch(part):
            normalized.append("{id}")
        elif _TOKEN_RE.fullmatch(part):
            normalized.append("{token}")
        else:
            normalized.append(part)
    return "/" + "/".join(normalized)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record Prometheus HTTP request count and latency histograms.

    The ``endpoint`` label uses ``normalize_metrics_path`` so identifiers
    never become high-cardinality labels.  The ``/metrics`` endpoint itself
    is excluded to avoid self-scraping noise.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)
        endpoint = normalize_metrics_path(request.url.path)
        method = request.method
        status = 500
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(
                time.perf_counter() - start
            )
            REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
            update_db_pool_metrics()


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique ``request_id`` to every request and response header."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        clear_contextvars()
        bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            clear_contextvars()


class TimingMiddleware(BaseHTTPMiddleware):
    """Log request duration and add an ``X-Process-Time`` header."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        response.headers["X-Process-Time"] = f"{elapsed_ms:.3f}"
        logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(elapsed_ms, 2),
            request_id=getattr(request.state, "request_id", None),
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple per-IP rate limiter backed by Redis.

    ``INCR`` + ``EXPIRE`` are batched into one pipeline round-trip (the key
    embeds the minute window, so the unconditional EXPIRE is harmless — each
    window gets its own key).  Falls back to allowing all requests if Redis
    is unavailable so that the API remains available during a Redis outage.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        from .exceptions import RateLimitExceededError

        # Skip rate limiting for health checks.
        if request.url.path.endswith("/health"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        key = f"ratelimit:{client_ip}:{int(time.time() // 60)}"
        try:
            redis = get_redis()
            async with redis.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, 60)
                results = await pipe.execute()
            count = int(results[0])
            if count > settings.rate_limit_per_minute:
                raise RateLimitExceededError(
                    "Rate limit exceeded. Please retry later."
                )
        except RateLimitExceededError:
            raise
        except Exception:
            # Redis unavailable – fail open.
            logger.warning("rate_limit_redis_unavailable")

        return await call_next(request)
