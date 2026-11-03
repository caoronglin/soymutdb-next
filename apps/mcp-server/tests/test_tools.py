"""Tool-level tests for the SoyMutDB MCP server (B4).

Mock ``httpx.AsyncClient`` (``unittest.mock``) and verify, per tool:

- the exact URL / params / payload / auth header sent to apps/api
- success-response formatting into the manifest's structured shape
- error mapping (404 -> not_found, 422 -> validation+details, 429 ->
  rate_limited+retry_after, transport failure -> upstream_unavailable)
- local rate limiting (global 60/min and blast_submit 10/hr quota) returns
  ``{"error": "rate_limited", "retry_after": N}`` before any API call
- IDOR protection: blast_job_status / analyses_query refuse cross-token and
  unbound reads (``forbidden``), and honour the submitter_token returned by
  blast_submit
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Self
from unittest import mock

import httpx
import pytest
from mcp_server import server
from mcp_server.ratelimit import GLOBAL_LIMITER, SUBMIT_LIMITER, FixedWindowLimiter

# ---------------------------------------------------------------------------
# httpx mock plumbing
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}

    def json(self) -> Any:
        return self._json


class FakeAsyncClient:
    """In-memory httpx.AsyncClient stand-in recording every request."""

    def __init__(self, handler: Callable[..., Awaitable[FakeResponse]]) -> None:
        self._handler = handler
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "params": params,
                "json": json,
                "headers": headers,
            }
        )
        return await self._handler(
            method, url, params=params, json=json, headers=headers
        )


class ClientPatch:
    """Context manager installing a fake AsyncClient into the server module."""

    def __init__(self, handler: Callable[..., Awaitable[FakeResponse]]) -> None:
        self.fake = FakeAsyncClient(handler)
        self._patcher = mock.patch.object(
            server.httpx, "AsyncClient", return_value=self.fake
        )

    def __enter__(self) -> FakeAsyncClient:
        self._patcher.start()
        return self.fake

    def __exit__(self, *args: object) -> None:
        self._patcher.stop()


def _patch_client(handler: Callable[..., Awaitable[FakeResponse]]) -> ClientPatch:
    return ClientPatch(handler)


def _ok(
    json_data: Any, status_code: int = 200, headers: dict[str, str] | None = None
) -> FakeResponse:
    return FakeResponse(status_code=status_code, json_data=json_data, headers=headers)


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset module-level rate limiters + job ownership registry per test."""
    GLOBAL_LIMITER.reset()
    SUBMIT_LIMITER.reset()
    server._JOB_OWNERSHIP.clear()
    yield
    GLOBAL_LIMITER.reset()
    SUBMIT_LIMITER.reset()
    server._JOB_OWNERSHIP.clear()


# ---------------------------------------------------------------------------
# ratelimit.FixedWindowLimiter unit tests
# ---------------------------------------------------------------------------


class TestFixedWindowLimiter:
    def test_allows_until_limit_then_denies(self):
        limiter = FixedWindowLimiter(limit=3, window_seconds=60.0)
        t0 = 1000.0
        for i in range(3):
            allowed, retry = limiter.check("k", now=t0 + i)
            assert (allowed, retry) == (True, 0)
        allowed, retry = limiter.check("k", now=t0 + 3)
        assert allowed is False
        assert retry >= 1  # seconds until window reset

    def test_window_rolls_over(self):
        limiter = FixedWindowLimiter(limit=2, window_seconds=60.0)
        t0 = 1000.0
        limiter.check("k", now=t0)
        limiter.check("k", now=t0 + 1)
        assert limiter.check("k", now=t0 + 2)[0] is False
        # 60s later the window has reset
        assert limiter.check("k", now=t0 + 61)[0] is True

    def test_keys_are_isolated(self):
        limiter = FixedWindowLimiter(limit=1, window_seconds=60.0)
        assert limiter.check("a", now=1.0) == (True, 0)
        assert limiter.check("b", now=1.0) == (True, 0)  # different key
        assert limiter.check("a", now=1.0)[0] is False

    def test_reset_clears(self):
        limiter = FixedWindowLimiter(limit=1, window_seconds=60.0)
        limiter.check("k", now=1.0)
        assert limiter.check("k", now=1.0)[0] is False
        limiter.reset("k")
        assert limiter.check("k", now=1.0)[0] is True


# ---------------------------------------------------------------------------
# Read tools: URL / params / auth / formatting
# ---------------------------------------------------------------------------


class TestGeneById:
    def test_hits_expected_url_and_formats(self):
        captured: dict[str, Any] = {}

        async def handler(method, url, *, params, json, headers):
            captured.update(method=method, url=url, params=params, headers=headers)
            return _ok(
                {
                    "gene_id": "Glyma.01G000100",
                    "assembly_id": 1,
                    "chromosome": "chr1",
                    "start": 1000,
                    "end": 5000,
                    "strand": "+",
                    "name": "Gm01G000100",
                    "biotype": "protein_coding",
                    "description": "A soybean gene",
                    "variant_count": 3,
                    "transcripts": [{"name": "t1"}, {"name": "t2"}],
                    "aliases": ["Alias1"],
                }
            )

        with _patch_client(handler):
            result = asyncio.run(server.gene_by_id("Glyma.01G000100"))

        assert captured["method"] == "GET"
        assert captured["url"] == "http://localhost:8010/api/v1/genes/Glyma.01G000100"
        assert captured["params"] is None
        assert result["gene_id"] == "Glyma.01G000100"
        assert result["chromosome"] == "chr1"
        assert result["transcript_count"] == 2
        assert result["aliases"] == ["Alias1"]
        assert result["variant_count"] == 3

    def test_forwards_assembly_id_and_bearer_token(self):
        server.API_TOKEN = "test-secret"
        try:
            captured: dict[str, Any] = {}

            async def handler(method, url, *, params, json, headers):
                captured.update(params=params, headers=headers)
                return _ok(
                    {
                        "gene_id": "G1",
                        "chromosome": "chr1",
                        "start": 1,
                        "end": 2,
                        "strand": "+",
                    }
                )

            with _patch_client(handler):
                asyncio.run(server.gene_by_id("G1", assembly_id=7))

            assert captured["params"] == {"assembly_id": 7}
            assert captured["headers"]["Authorization"] == "Bearer test-secret"
        finally:
            server.API_TOKEN = ""

    def test_api_404_maps_to_not_found(self):
        async def handler(method, url, *, params, json, headers):
            return _ok(
                status_code=404,
                json_data={
                    "error": {
                        "code": "not_found",
                        "message": "Gene G1 not found",
                        "details": {},
                    },
                    "request_id": "r1",
                    "status_code": 404,
                },
            )

        with _patch_client(handler):
            result = asyncio.run(server.gene_by_id("G1"))

        assert result["error"] == "not_found"
        assert result["message"] == "Gene G1 not found"

    def test_api_422_maps_to_validation_with_details(self):
        async def handler(method, url, *, params, json, headers):
            return _ok(
                status_code=422,
                json_data={
                    "error": {
                        "code": "validation_error",
                        "message": "Request validation failed",
                        "details": {},
                    },
                    "errors": [
                        {
                            "field": "query.gene_id",
                            "message": "too long",
                            "type": "string_too_long",
                        }
                    ],
                    "status_code": 422,
                },
            )

        with _patch_client(handler):
            result = asyncio.run(server.gene_by_id("G1"))

        assert result["error"] == "validation"
        assert result["details"][0]["field"] == "query.gene_id"


class TestVariantByRegion:
    def test_hits_expected_url_and_formats(self):
        captured: dict[str, Any] = {}

        async def handler(method, url, *, params, json, headers):
            captured.update(method=method, url=url, params=params)
            return _ok(
                [
                    {
                        "variant_id": "V1",
                        "chromosome": "chr1",
                        "position": 1500,
                        "ref_allele": "A",
                        "alt_allele": "G",
                        "variant_type": "SNP",
                        "quality": 99.0,
                        "filter_status": "PASS",
                        "allele_frequency": 0.05,
                    }
                ]
            )

        with _patch_client(handler):
            result = asyncio.run(
                server.variant_by_region("GmWm82.a2.v1", "chr1", 1000, 2000)
            )

        assert captured["method"] == "GET"
        assert captured["url"] == "http://localhost:8010/api/v1/variants/region"
        assert captured["params"] == {
            "assembly": "GmWm82.a2.v1",
            "chromosome": "chr1",
            "start": 1000,
            "end": 2000,
            "max_results": 1000,
        }
        assert result["count"] == 1
        assert result["variants"][0]["variant_id"] == "V1"
        assert result["variants"][0]["allele_frequency"] == 0.05

    def test_clamps_max_results_to_api_cap(self):
        captured: dict[str, Any] = {}

        async def handler(method, url, *, params, json, headers):
            captured["params"] = params
            return _ok([])

        with _patch_client(handler):
            asyncio.run(server.variant_by_region("a", "chr1", 1, 2, max_results=50_000))

        assert captured["params"]["max_results"] == 10_000


class TestNewsList:
    def test_hits_expected_url_and_formats(self):
        captured: dict[str, Any] = {}

        async def handler(method, url, *, params, json, headers):
            captured.update(method=method, url=url, params=params)
            return _ok(
                {
                    "items": [
                        {
                            "id": "1",
                            "title_en": "Hello",
                            "title_zh": "你好",
                            "slug": "hello",
                            "category": "news",
                            "cover_url": "http://img/1.png",
                            "published_at": "2026-08-01T00:00:00Z",
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 20,
                }
            )

        with _patch_client(handler):
            result = asyncio.run(server.news_list(category="news"))

        assert captured["url"] == "http://localhost:8010/api/v1/news"
        assert captured["params"] == {"page": 1, "page_size": 20, "category": "news"}
        assert result["total"] == 1
        assert result["items"][0]["title_en"] == "Hello"

    def test_no_category_param_when_omitted(self):
        captured: dict[str, Any] = {}

        async def handler(method, url, *, params, json, headers):
            captured["params"] = params
            return _ok({"items": [], "total": 0, "page": 1, "page_size": 20})

        with _patch_client(handler):
            asyncio.run(server.news_list())

        assert captured["params"] == {"page": 1, "page_size": 20}


class TestStatsSummary:
    def test_hits_expected_url_and_formats(self):
        captured: dict[str, Any] = {}

        async def handler(method, url, *, params, json, headers):
            captured.update(method=method, url=url, params=params)
            return _ok(
                {
                    "total_variants": 12345,
                    "total_genes": 5678,
                    "total_mutant_lines": 90,
                    "total_phenotypes": 12,
                    "assemblies_count": 2,
                    "current_release": "v1.0",
                    "last_updated": "2026-08-09T00:00:00Z",
                }
            )

        with _patch_client(handler):
            result = asyncio.run(server.stats_summary())

        assert captured["url"] == "http://localhost:8010/api/v1/stats/dashboard"
        assert result["total_variants"] == 12345
        assert result["current_release"] == "v1.0"


class TestSeqFetch:
    def test_hits_expected_url_and_formats(self):
        captured: dict[str, Any] = {}

        async def handler(method, url, *, params, json, headers):
            captured.update(method=method, url=url, json=json)
            return _ok(
                {
                    "format": "fasta",
                    "sequence": ">G1\nACGT",
                    "count": 1,
                    "truncated": False,
                    "missing": ["G2"],
                    "download_url": None,
                    "expires_in": None,
                }
            )

        with _patch_client(handler):
            result = asyncio.run(server.seqfetch(assembly="Wm82.v5", genes=["G1"]))

        assert captured["method"] == "POST"
        assert captured["url"] == "http://localhost:8010/api/v1/tools/seqfetch"
        assert captured["json"] == {"assembly": "Wm82.v5", "genes": ["G1"]}
        assert result["sequence"] == ">G1\nACGT"
        assert result["assembly"] == "Wm82.v5"
        assert result["missing"] == ["G2"]

    def test_region_mode_payload(self):
        captured: dict[str, Any] = {}

        async def handler(method, url, *, params, json, headers):
            captured["json"] = json
            return _ok(
                {"format": "fasta", "count": 0, "truncated": False, "missing": []}
            )

        with _patch_client(handler):
            asyncio.run(
                server.seqfetch(assembly="GmWm82.a2.v1", region="chr1:1000-2000")
            )

        assert captured["json"] == {
            "assembly": "GmWm82.a2.v1",
            "region": "chr1:1000-2000",
        }


# ---------------------------------------------------------------------------
# Write tools: blast_submit / blast_job_status / analyses_query + IDOR
# ---------------------------------------------------------------------------


class TestBlastSubmit:
    def test_submits_job_and_binds_submitter_token(self):
        captured: dict[str, Any] = {}

        async def handler(method, url, *, params, json, headers):
            captured.update(method=method, url=url, json=json)
            return _ok(
                status_code=201,
                json_data={
                    "job_id": "job-1",
                    "status": "pending",
                    "program": "blastp",
                    "database_id": 3,
                    "submitted_at": "2026-08-09T00:00:00Z",
                },
            )

        with _patch_client(handler):
            result = asyncio.run(
                server.blast_submit(
                    "MEEPQSDPSV",
                    program="blastp",
                    database="glyma_cds",
                    database_id=3,
                    params={"evalue": 1e-5},
                )
            )

        assert captured["method"] == "POST"
        assert captured["url"] == "http://localhost:8010/api/v1/blast/jobs"
        assert captured["json"] == {
            "engine": "ncbi_blast",
            "program": "blastp",
            "query_sequence": "MEEPQSDPSV",
            "database": "glyma_cds",
            "database_id": 3,
            "parameters": {"evalue": 1e-5},
        }
        assert result["job_id"] == "job-1"
        assert result["status"] == "pending"
        assert result["poll"] == "blast_job_status"
        # A submitter token was generated and bound to the job.
        assert len(result["submitter_token"]) == 32
        assert server._JOB_OWNERSHIP["job-1"] == result["submitter_token"]

    def test_all_ncbi_programs_and_explicit_diamond_engine_are_forwarded(self):
        captured: list[dict[str, Any]] = []

        async def handler(method, url, *, params, json, headers):
            captured.append(json)
            return _ok(
                status_code=201,
                json_data={
                    "job_id": f"job-{len(captured)}",
                    "status": "pending",
                    "program": json["program"],
                },
            )

        with _patch_client(handler):
            for program in ("blastn", "blastp", "blastx", "tblastn", "tblastx"):
                asyncio.run(server.blast_submit("ACGTACGTACGT", program=program))
            asyncio.run(
                server.blast_submit("MEEPQSDPSV", program="blastp", engine="diamond")
            )

        assert [(item["engine"], item["program"]) for item in captured] == [
            ("ncbi_blast", program)
            for program in ("blastn", "blastp", "blastx", "tblastn", "tblastx")
        ] + [("diamond", "blastp")]

    def test_api_422_maps_to_validation(self):
        async def handler(method, url, *, params, json, headers):
            return _ok(
                status_code=422,
                json_data={
                    "error": {
                        "code": "validation_error",
                        "message": "Request validation failed",
                        "details": {},
                    },
                    "errors": [
                        {
                            "field": "body.query_sequence",
                            "message": "String should have at least 10 characters",
                            "type": "string_too_short",
                        }
                    ],
                    "status_code": 422,
                },
            )

        with _patch_client(handler):
            result = asyncio.run(server.blast_submit("ACGT"))

        assert result["error"] == "validation"
        assert result["details"][0]["field"] == "body.query_sequence"


class TestBlastJobStatus:
    def _flow(self, analyses: bool = False):
        """Shared fake API for the submit -> poll flow."""

        async def handler(method, url, *, params, json, headers):
            if url.endswith("/api/v1/blast/jobs"):
                return _ok(
                    status_code=201, json_data={"job_id": "job-1", "status": "pending"}
                )
            if url.endswith("/api/v1/blast/jobs/job-1"):
                return _ok(
                    {
                        "job_id": "job-1",
                        "status": "running",
                        "program": "blastn",
                        "submitted_at": "2026-08-09T00:00:00Z",
                        "started_at": None,
                        "completed_at": None,
                        "error_message": None,
                        "result_url": None,
                    }
                )
            if url.endswith("/api/v1/analyses/job-1"):
                return _ok(
                    {
                        "job_id": "job-1",
                        "analysis_type": "fastp",
                        "status": "succeeded",
                        "error_message": None,
                        "result": {"summary": "ok"},
                        "created_at": "2026-08-09T00:00:00Z",
                        "updated_at": "2026-08-09T01:00:00Z",
                    }
                )
            raise AssertionError(f"unexpected call {method} {url}")

        return handler

    def test_owner_can_poll_job(self):
        with _patch_client(self._flow()):
            submit = asyncio.run(server.blast_submit("ACGTACGTACGTACGTACGT"))
            token = submit["submitter_token"]
            result = asyncio.run(server.blast_job_status("job-1", token))

        assert result["job_id"] == "job-1"
        assert result["status"] == "running"

    def test_cross_token_read_is_refused(self):
        with _patch_client(self._flow()):
            _ = asyncio.run(server.blast_submit("ACGTACGTACGTACGTACGT"))
            result = asyncio.run(server.blast_job_status("job-1", "a" * 32))

        assert result["error"] == "forbidden"
        assert "submitter token" in result["message"]

    def test_unbound_job_is_refused_fail_closed(self):
        # A job id never submitted through this MCP server must not leak data,
        # even with a plausible-looking token.
        with _patch_client(self._flow()):
            result = asyncio.run(server.blast_job_status("job-1", "b" * 32))

        assert result["error"] == "forbidden"

    def test_analyses_query_owner_ok_cross_token_refused(self):
        with _patch_client(self._flow(analyses=True)):
            submit = asyncio.run(server.blast_submit("ACGTACGTACGTACGTACGT"))
            token = submit["submitter_token"]
            ok = asyncio.run(server.analyses_query("job-1", token))
            denied = asyncio.run(server.analyses_query("job-1", "c" * 32))

        assert ok["status"] == "succeeded"
        assert ok["result"] == {"summary": "ok"}
        assert denied["error"] == "forbidden"

    def test_api_404_maps_to_not_found_for_owner(self):
        async def handler(method, url, *, params, json, headers):
            if url.endswith("/api/v1/blast/jobs"):
                return _ok(
                    status_code=201, json_data={"job_id": "job-1", "status": "pending"}
                )
            return _ok(
                status_code=404,
                json_data={
                    "error": {
                        "code": "not_found",
                        "message": "BLAST job job-1 not found",
                        "details": {},
                    }
                },
            )

        with _patch_client(handler):
            submit = asyncio.run(server.blast_submit("ACGTACGTACGTACGTACGT"))
            result = asyncio.run(
                server.blast_job_status("job-1", submit["submitter_token"])
            )

        assert result["error"] == "not_found"


# ---------------------------------------------------------------------------
# Error mapping: API 429 / transport failures
# ---------------------------------------------------------------------------


class TestErrorMapping:
    def test_api_429_maps_to_rate_limited_with_retry_after(self):
        async def handler(method, url, *, params, json, headers):
            return _ok(
                status_code=429,
                headers={"Retry-After": "30"},
                json_data={
                    "error": {
                        "code": "rate_limited",
                        "message": "Too many requests",
                        "details": {},
                    },
                    "status_code": 429,
                },
            )

        with _patch_client(handler):
            result = asyncio.run(server.stats_summary())

        assert result["error"] == "rate_limited"
        assert result["retry_after"] == 30

    def test_transport_failure_maps_to_upstream_unavailable(self):
        async def handler(method, url, *, params, json, headers):
            raise httpx.ConnectError("connection refused")

        with _patch_client(handler):
            result = asyncio.run(server.stats_summary())

        assert result["error"] == "upstream_unavailable"

    def test_timeout_maps_to_upstream_unavailable(self):
        async def handler(method, url, *, params, json, headers):
            raise httpx.TimeoutException("timed out")

        with _patch_client(handler):
            result = asyncio.run(server.gene_by_id("G1"))

        assert result["error"] == "upstream_unavailable"


# ---------------------------------------------------------------------------
# Local rate limiting (before any API call)
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_global_60_per_minute_window(self):
        # Exhaust the real global window for the anonymous caller.
        for _ in range(60):
            assert GLOBAL_LIMITER.check("anonymous")[0] is True
        result = asyncio.run(server.gene_by_id("G1"))
        assert result["error"] == "rate_limited"
        assert result["retry_after"] >= 1

    def test_global_window_rolls_over_after_60s(self):
        for _ in range(60):
            assert GLOBAL_LIMITER.check("anonymous")[0] is True
        GLOBAL_LIMITER.reset("anonymous")

        async def handler(method, url, *, params, json, headers):
            return _ok({"total_genes": 1, "total_variants": 0})

        with _patch_client(handler):
            result = asyncio.run(server.stats_summary())
        assert "error" not in result

    def test_blast_submit_quota_10_per_hour(self):
        for _ in range(10):
            assert SUBMIT_LIMITER.check("anonymous")[0] is True
        result = asyncio.run(server.blast_submit("ACGTACGTACGTACGTACGT"))
        assert result["error"] == "rate_limited"
        assert result["retry_after"] >= 1

    def test_blast_submit_quota_is_separate_from_global(self):
        # Exhaust the submit quota but keep the global window open: read
        # tools must still work.
        for _ in range(10):
            assert SUBMIT_LIMITER.check("anonymous")[0] is True

        async def handler(method, url, *, params, json, headers):
            return _ok({"total_genes": 1, "total_variants": 0})

        with _patch_client(handler):
            result = asyncio.run(server.stats_summary())
        assert "error" not in result
