"""ASGI middleware: request-id propagation, timing, rate limiting, metrics."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp
from structlog import get_logger
from structlog.contextvars import bind_contextvars, clear_contextvars

from .exceptions import SoyMutDBError, soy_mut_db_exception_handler
from .metrics import REQUEST_COUNT, REQUEST_LATENCY, update_db_pool_metrics
from .ratelimit import RequestRateLimiter, request_rate_limiter

logger = get_logger(__name__)

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
    """Enforce the global per-peer request budget.

    The limiter itself lives in :class:`app.core.ratelimit.RequestRateLimiter`
    and is graded per request class:

    * anonymous public reads (``GET``/``HEAD`` without a verified principal)
      consume ``public_read_rate_limit_per_minute`` and **fail open** while
      the limiter backend is unavailable;
    * writes (``POST``/``PUT``/``PATCH``/``DELETE``) consume
      ``write_rate_limit_per_minute`` and **fail closed** with 503;
    * login keeps its dedicated limiter without being counted twice;
      other auth writes still consume the write budget;
    * ``/health`` / ``/metrics`` are exempt.

    Wiring: the middleware is registered by ``app/main.py``.  It is the
    innermost user middleware (directly in front of the router) so that the
    observability and response-shaping middlewares still see a rejected
    request - ``MetricsMiddleware`` counts the rejection, ``RequestIdMiddleware``
    supplies the request id of the error envelope, and the security/CORS
    headers are still added to the rejected response.

    The domain error is rendered here with the shared error handler because
    Starlette's ``ExceptionMiddleware`` sits *inside* the user middleware
    stack and therefore cannot translate an exception raised by a middleware.
    """

    def __init__(self, app: ASGIApp, *, limiter: RequestRateLimiter | None = None) -> None:
        super().__init__(app)
        self._limiter = limiter if limiter is not None else request_rate_limiter

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            await self._limiter.check(request)
        except SoyMutDBError as exc:
            return await soy_mut_db_exception_handler(request, exc)
        return await call_next(request)
