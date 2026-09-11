"""Operational Prometheus metric contracts."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import yaml
from prometheus_client import generate_latest

from app.core import database, outbox_dispatcher
from app.core.metrics import (
    OUTBOX_DELIVERY_EXHAUSTED_TOTAL,
    OUTBOX_EVENTS,
    OUTBOX_OLDEST_UNSENT_AGE_SECONDS,
)
from app.models.outbox import OutboxEventStatus
from app.services import outbox_service


class _StatusResult:
    def all(self):
        return [
            (OutboxEventStatus.PENDING, 3),
            (OutboxEventStatus.FAILED, 1),
            (OutboxEventStatus.SENT, 8),
        ]


class _MetricsSession:
    def __init__(self, oldest: datetime) -> None:
        self.oldest = oldest

    async def execute(self, _statement):
        return _StatusResult()

    async def scalar(self, _statement):
        return self.oldest


def test_outbox_delivery_exhaustion_metric_is_unlabelled_counter() -> None:
    exported = generate_latest().decode()

    assert (
        "# HELP soymutdb_outbox_delivery_exhausted_total "
        "Terminal outbox deliveries that exhausted their retry budget"
    ) in exported
    assert "# TYPE soymutdb_outbox_delivery_exhausted_total counter" in exported
    assert OUTBOX_DELIVERY_EXHAUSTED_TOTAL._labelnames == ()


def test_outbox_delivery_exhaustion_alert_is_immediate_and_critical() -> None:
    alerts_path = Path(__file__).resolve().parents[3] / "infra/monitoring/rules/alerts.yml"
    alert_rules = yaml.safe_load(alerts_path.read_text(encoding="utf-8"))
    rules = [rule for group in alert_rules["groups"] for rule in group["rules"]]
    exhausted_alert = next(rule for rule in rules if rule.get("alert") == "OutboxDeliveryExhausted")

    assert exhausted_alert["expr"] == (
        "increase(soymutdb_outbox_delivery_exhausted_total[15m]) > 0"
    )
    assert exhausted_alert["for"] == "0m"
    assert exhausted_alert["labels"]["severity"] == "critical"


async def test_outbox_snapshot_reports_status_counts_and_unsent_age() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    session = _MetricsSession(now - timedelta(seconds=90))

    counts, age = await outbox_service.get_metrics_snapshot(session, now=now)

    assert counts == {"pending": 3, "failed": 1, "sent": 8}
    assert age == 90.0


async def test_outbox_gauge_refresh_clears_missing_statuses(monkeypatch) -> None:
    now = datetime.now(UTC)
    session = _MetricsSession(now - timedelta(seconds=30))

    @asynccontextmanager
    async def factory():
        yield session

    monkeypatch.setattr(outbox_dispatcher, "get_session_factory", lambda: factory)
    await outbox_dispatcher.refresh_outbox_metrics()

    assert OUTBOX_EVENTS.labels(status="pending")._value.get() == 3
    assert OUTBOX_EVENTS.labels(status="processing")._value.get() == 0
    assert OUTBOX_EVENTS.labels(status="failed")._value.get() == 1
    assert OUTBOX_OLDEST_UNSENT_AGE_SECONDS._value.get() >= 29


def test_database_pool_snapshot_does_not_initialize_engine(monkeypatch) -> None:
    monkeypatch.setattr(database, "_engine", None)
    assert database.get_db_pool_status() is None


def test_database_pool_snapshot_exposes_capacity_and_usage(monkeypatch) -> None:
    pool = SimpleNamespace(
        size=lambda: 3,
        checkedin=lambda: 1,
        checkedout=lambda: 2,
        overflow=lambda: -1,
    )
    engine = SimpleNamespace(sync_engine=SimpleNamespace(pool=pool))
    monkeypatch.setattr(database, "_engine", engine)

    status = database.get_db_pool_status()

    assert status == {
        "capacity": database.settings.db_pool_size
        + database.settings.db_max_overflow,
        "size": 3,
        "checked_in": 1,
        "checked_out": 2,
        "overflow": 0,
    }
