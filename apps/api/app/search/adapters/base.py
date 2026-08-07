"""Base class for external search source adapters.

Each concrete adapter implements :meth:`do_search` which performs the HTTP
call(s) against a specific provider and returns normalized
:class:`SearchHit` objects.  The base class wraps the call with:

* per-request timeout
* circuit breaker (Redis-backed)
* exponential-backoff retry (2 retries by default)
* token-bucket rate limiting
* structured error / timeout translation into a :class:`SourceResult`
"""

from __future__ import annotations

import asyncio
import time
from typing import ClassVar

import httpx
import structlog
from redis.asyncio import Redis

from ..circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from ..models import SearchHit, SearchSource, SourceResult, SourceStatus
from ..rate_limiter import TokenBucketRateLimiter

logger = structlog.get_logger(__name__)

DEFAULT_TIMEOUT = 5.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_BASE = 0.3


class BaseAdapter:
    """Abstract base adapter.

    Subclasses must set :attr:`source` and implement :meth:`do_search`.
    """

    source: ClassVar[SearchSource]
    base_url: ClassVar[str] = ""

    # Per-adapter tunables.
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    backoff_base: float = DEFAULT_BACKOFF_BASE
    user_agent: str = "SoyMutDB/2.0 (+https://soymutdb.org)"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self.circuit_breaker = CircuitBreaker(
            redis,
            name=f"search:{self.source.value}",
            failure_threshold=5,
            recovery_timeout=30.0,
        )
        # Default rate limit — conservative; subclasses can override via
        # ``rate_per_second`` class attribute after __init__ by subclassing.
        rate = getattr(self, "rate_per_second", 5.0)
        burst = getattr(self, "rate_burst", 8)
        self.rate_limiter = TokenBucketRateLimiter(
            redis,
            name=f"search:{self.source.value}",
            rate_per_second=rate,
            burst=burst,
        )

    # ------------------------------------------------------------------ API
    async def search(self, query: str, limit: int = 10, client: httpx.AsyncClient | None = None) -> SourceResult:
        """Run the search with resilience wrapping; never raise."""
        start = time.perf_counter()
        try:
            # Circuit breaker fast-fail.
            if not await self.circuit_breaker.allow_request():
                return SourceResult(
                    source=self.source,
                    status=SourceStatus.CIRCUIT_OPEN,
                    elapsed_ms=(time.perf_counter() - start) * 1000,
                    error_message=f"{self.source.value} temporarily unavailable",
                )

            # Await a rate-limit token (polite outbound).
            if not await self.rate_limiter.acquire(max_wait=self.timeout):
                return SourceResult(
                    source=self.source,
                    status=SourceStatus.RATE_LIMITED,
                    elapsed_ms=(time.perf_counter() - start) * 1000,
                    error_message="rate limited",
                )

            owns_client = client is None
            if owns_client:
                client = httpx.AsyncClient(
                    timeout=self.timeout,
                    headers={"User-Agent": self.user_agent, "Accept": "application/json"},
                    follow_redirects=True,
                )
            try:
                hits = await self._call_with_retry(client, query, limit)
            finally:
                if owns_client:
                    await client.aclose()

            await self.circuit_breaker.record_success()
            elapsed = (time.perf_counter() - start) * 1000
            if not hits:
                return SourceResult(
                    source=self.source,
                    status=SourceStatus.EMPTY,
                    elapsed_ms=elapsed,
                )
            return SourceResult(
                source=self.source,
                status=SourceStatus.OK,
                hits=hits[:limit],
                elapsed_ms=elapsed,
            )

        except CircuitBreakerOpen:
            return SourceResult(
                source=self.source,
                status=SourceStatus.CIRCUIT_OPEN,
                elapsed_ms=(time.perf_counter() - start) * 1000,
                error_message=f"{self.source.value} temporarily unavailable (circuit open)",
            )
        except asyncio.TimeoutError:
            await self.circuit_breaker.record_failure()
            return SourceResult(
                source=self.source,
                status=SourceStatus.TIMEOUT,
                elapsed_ms=(time.perf_counter() - start) * 1000,
                error_message="request timed out",
            )
        except httpx.TimeoutException:
            await self.circuit_breaker.record_failure()
            return SourceResult(
                source=self.source,
                status=SourceStatus.TIMEOUT,
                elapsed_ms=(time.perf_counter() - start) * 1000,
                error_message="upstream timed out",
            )
        except httpx.HTTPStatusError as e:
            # Do not trip the breaker for 4xx (our fault), only for 5xx.
            if e.response.status_code >= 500:
                await self.circuit_breaker.record_failure()
            else:
                await self.circuit_breaker.record_success()
            logger.warning(
                "search.adapter.http_error",
                source=self.source.value,
                status=e.response.status_code,
            )
            return SourceResult(
                source=self.source,
                status=SourceStatus.ERROR,
                elapsed_ms=(time.perf_counter() - start) * 1000,
                error_message=f"HTTP {e.response.status_code}",
            )
        except (httpx.HTTPError, OSError) as e:
            await self.circuit_breaker.record_failure()
            logger.warning("search.adapter.error", source=self.source.value, error=str(e))
            return SourceResult(
                source=self.source,
                status=SourceStatus.ERROR,
                elapsed_ms=(time.perf_counter() - start) * 1000,
                error_message=str(e)[:200],
            )
        except Exception as e:  # pragma: no cover - defensive
            await self.circuit_breaker.record_failure()
            logger.exception("search.adapter.unexpected", source=self.source.value)
            return SourceResult(
                source=self.source,
                status=SourceStatus.ERROR,
                elapsed_ms=(time.perf_counter() - start) * 1000,
                error_message=f"unexpected error: {e!s:.200}",
            )

    async def _call_with_retry(
        self, client: httpx.AsyncClient, query: str, limit: int
    ) -> list[SearchHit]:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return await self.do_search(client, query, limit)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, OSError) as e:
                last_exc = e
                if attempt >= self.retries:
                    break
                await asyncio.sleep(self.backoff_base * (2 ** attempt))
            except httpx.HTTPStatusError as e:
                # Retry 5xx and 429 only.
                if e.response.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    last_exc = e
                    await asyncio.sleep(self.backoff_base * (2 ** attempt))
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------- subclass
    async def do_search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[SearchHit]:
        """Perform the actual search and return normalized hits.

        Subclasses **must** override this.  Raised HTTP/transport errors are
        handled by :meth:`search` (circuit breaker + retry + translation).
        """
        raise NotImplementedError
