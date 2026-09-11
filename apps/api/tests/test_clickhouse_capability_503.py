"""Capability contract for ClickHouse-backed endpoints (baseline mode).

ClickHouse is a *required capability* in extended deployments and an *absent
capability* in baseline/disposable ones. When the projection is unreachable the
API must report "capability unavailable" consistently:

- endpoints whose only data source is the projection return
  ``503 service_unavailable`` — never an unhandled ``500``;
- the body names the capability and must not leak the host, port, driver
  package, or a stack trace.

Endpoints that have a PostgreSQL fallback (dashboard counters, variant-type
totals) deliberately degrade to 200 with zero/empty values; those are not part
of this contract.
"""

from __future__ import annotations

import json

import pytest
from clickhouse_connect.driver.exceptions import OperationalError

from app.core.exceptions import ServiceUnavailableError
from app.services.clickhouse_service import (
    CLICKHOUSE_UNAVAILABLE_MESSAGE,
    ClickHouseService,
)

_FORBIDDEN_FRAGMENTS = (
    "8123",  # default ClickHouse port
    "localhost",
    "127.0.0.1",
    "Traceback",
    "clickhouse_connect",
    "aiohttp",
)


class _UnreachableClient:
    """Stand-in for a client whose transport cannot reach ClickHouse."""

    async def query(self, *args, **kwargs):
        raise OperationalError(
            "Network Error: Cannot connect to host localhost:8123 ssl:default"
        )

    async def insert(self, *args, **kwargs):
        raise OperationalError(
            "Network Error: Cannot connect to host localhost:8123 ssl:default"
        )


def _unreachable_service() -> ClickHouseService:
    service = ClickHouseService()
    service._client = _UnreachableClient()  # noqa: SLF001 – inject the failing transport
    return service


@pytest.mark.asyncio
async def test_release_bound_queries_report_capability_unavailable() -> None:
    """Every public query method translates a transport failure to 503."""
    from app.schemas.variant import VariantFilterParams
    from app.services.release_context import ReleaseContext

    service = _unreachable_service()
    context = ReleaseContext(release_id=7)

    # Factories (not pre-built coroutines): each is awaited inside the
    # assertion so nothing is created and left unawaited.
    calls = [
        (
            "count_variants",
            lambda: service.count_variants(
                VariantFilterParams(), release_context=context
            ),
        ),
        (
            "query_variants",
            lambda: service.query_variants(
                VariantFilterParams(), 10, release_context=context
            ),
        ),
        (
            "query_variants_by_region",
            lambda: service.query_variants_by_region(
                "GmWm82.a4.v1", "chr01", 1, 100, release_context=context
            ),
        ),
        (
            "get_variant_by_id",
            lambda: service.get_variant_by_id("v1", release_context=context),
        ),
        ("get_dashboard_stats", lambda: service.get_dashboard_stats()),
        (
            "get_variant_type_distribution",
            lambda: service.get_variant_type_distribution(),
        ),
        (
            "get_chromosome_density",
            lambda: service.get_chromosome_density(
                assembly="GmWm82.a4.v1", chromosome="chr01"
            ),
        ),
        (
            "get_query_latency_percentile",
            lambda: service.get_query_latency_percentile(),
        ),
        ("get_query_latency_series", lambda: service.get_query_latency_series()),
    ]

    for name, factory in calls:
        with pytest.raises(ServiceUnavailableError) as excinfo:
            await factory()
        assert str(excinfo.value) == CLICKHOUSE_UNAVAILABLE_MESSAGE, name


def test_capability_message_leaks_no_transport_details() -> None:
    body = json.dumps(
        {
            "error": {
                "code": "service_unavailable",
                "message": CLICKHOUSE_UNAVAILABLE_MESSAGE,
            }
        }
    )
    for fragment in _FORBIDDEN_FRAGMENTS:
        assert fragment not in body, f"capability message leaked {fragment!r}"


@pytest.mark.asyncio
async def test_ping_reports_unavailable_without_raising() -> None:
    """The health probe must stay a boolean, not propagate the failure."""
    assert await _unreachable_service().ping() is False


@pytest.mark.asyncio
async def test_insert_transport_failure_is_not_swallowed_as_success() -> None:
    """Ingest cannot silently succeed when the projection is unreachable."""
    from clickhouse_connect.driver.exceptions import ClickHouseError

    service = _unreachable_service()
    with pytest.raises(ClickHouseError):
        await service.insert_release_variants(
            [{"variant_id": "v1", "release_key": "r7"}]
        )
