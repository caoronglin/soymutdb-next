"""Ablation guard: an empty window must yield 0.0, never NaN.

ClickHouse answers an ungrouped aggregate with exactly ONE row, so
``result.row_count == 0`` never fires for an empty ``analytics_events`` window
and ``quantile(0.95)(duration_ms)`` comes back as NaN. ``float(value or 0.0)``
does not rescue it either -- ``bool(nan)`` is True -- so NaN reached
``AdminDashboardStats.query_p95_ms``, whose ``ge=0`` bound rejected it and
turned ``GET /admin/dashboard-stats`` into a 500 on any database that has no
analytics events yet (i.e. every fresh deployment).

Each guard below flips if the NaN handling is removed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.clickhouse_service import ClickHouseService


class _FakeResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    @property
    def row_count(self) -> int:
        return len(self._rows)

    @property
    def first_row(self) -> tuple[object, ...]:
        return self._rows[0]


class _FakeClient:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result

    async def query(self, *_args, **_kwargs) -> _FakeResult:
        return self._result


def _service_with(result: _FakeResult) -> ClickHouseService:
    service = ClickHouseService()
    service._get_client = lambda: _async(_FakeClient(result))  # type: ignore[method-assign]
    return service


async def _async(value):
    return value


@pytest.mark.asyncio
async def test_nan_percentile_becomes_zero():
    """The empty-window aggregate returns one NaN row, not zero rows."""
    service = _service_with(_FakeResult([(float("nan"),)]))
    assert await service.get_query_latency_percentile() == 0.0


@pytest.mark.asyncio
async def test_none_percentile_becomes_zero():
    service = _service_with(_FakeResult([(None,)]))
    assert await service.get_query_latency_percentile() == 0.0


@pytest.mark.asyncio
async def test_real_percentile_is_preserved():
    """The guard must not flatten a genuine measurement."""
    service = _service_with(_FakeResult([(12.5,)]))
    assert await service.get_query_latency_percentile() == 12.5


@pytest.mark.asyncio
async def test_empty_result_still_returns_zero():
    service = _service_with(_FakeResult([]))
    assert await service.get_query_latency_percentile() == 0.0
