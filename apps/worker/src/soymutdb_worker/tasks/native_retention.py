"""Bounded PostgreSQL retention; each batch commits independently."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from soymutdb_worker.main import celery_app
from soymutdb_worker.utils.db import get_db

_TABLES = {"analytics_events": "event_pk", "web_vitals": "vital_pk"}


def prune_telemetry(table: str, cutoff: datetime, *, batch_size: int = 2000) -> int:
    """Delete one indexed batch, skipping rows another cleanup has locked."""
    if table not in _TABLES or not 1 <= batch_size <= 10000:
        raise ValueError("Invalid retention table or batch size")
    key = _TABLES[table]
    with get_db() as session:
        return int(session.execute(text(f"""
            WITH expired AS (
                SELECT {key} FROM {table} WHERE timestamp < :cutoff
                ORDER BY timestamp, {key} LIMIT :batch_size FOR UPDATE SKIP LOCKED
            ), removed AS (
                DELETE FROM {table} USING expired
                WHERE {table}.{key} = expired.{key} RETURNING 1
            ) SELECT count(*) FROM removed
        """), {"cutoff": cutoff, "batch_size": batch_size}).scalar_one())


def prune_published_staging(*, batch_size: int = 2000) -> int:
    """Remove only staging rows whose manifest publication has committed."""
    if not 1 <= batch_size <= 10000:
        raise ValueError("Invalid retention batch size")
    with get_db() as session:
        return int(session.execute(text("""
            WITH expired AS (
                SELECT s.ctid FROM variant_facts_staging s
                JOIN import_manifests m ON m.import_id = s.import_id
                WHERE m.status = 'published'
                ORDER BY s.import_id, s.assembly_id, s.variant_id
                LIMIT :batch_size FOR UPDATE OF s SKIP LOCKED
            ), removed AS (
                DELETE FROM variant_facts_staging s USING expired
                WHERE s.ctid = expired.ctid RETURNING 1
            ) SELECT count(*) FROM removed
        """), {"batch_size": batch_size}).scalar_one())


def _two_years_before(now: datetime) -> datetime:
    try:
        return now.replace(year=now.year - 2)
    except ValueError:  # February 29 has no counterpart two years earlier.
        return now.replace(year=now.year - 2, day=28)


@celery_app.task(name="soymutdb_worker.tasks.native_retention.cleanup", queue="cleanup")
def cleanup() -> dict[str, int]:
    """Retain events for two calendar years and vitals for 90 days.

    At most 20,000 rows per category per run keeps transaction duration and
    database connection use bounded. Remaining rows wait for the next run.
    """
    now = datetime.now(UTC)
    totals = {"analytics_events": 0, "web_vitals": 0, "published_staging": 0}
    for table, cutoff in (("analytics_events", _two_years_before(now)),
                          ("web_vitals", now - timedelta(days=90))):
        for _ in range(10):
            count = prune_telemetry(table, cutoff)
            totals[table] += count
            if count < 2000:
                break
    for _ in range(10):
        count = prune_published_staging()
        totals["published_staging"] += count
        if count < 2000:
            break
    return totals
