"""ASGI middleware: request-id propagation, timing, and rate limiting."""

from __future__ import annotations

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

logger = get_logger(__name__)
settings = get_settings()


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

    Falls back to allowing all requests if Redis is unavailable so that the
    API remains available during a Redis outage.
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
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, 60)
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
