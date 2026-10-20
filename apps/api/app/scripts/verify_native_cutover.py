"""Fail deployment when known published variant releases lack native evidence."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_engine, get_session_factory


async def verify_native_cutover(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(text("""
        SELECT r.id, r.version, r.variant_count,
               b.source_version, b.source_count,
               (SELECT count(*) FROM variant_facts f WHERE f.release_id=r.id) AS actual_count,
               EXISTS (SELECT 1 FROM import_manifests m
                       WHERE m.release_id=r.id AND m.status='published') AS native_import
        FROM releases r LEFT JOIN native_variant_backfills b ON b.release_id=r.id
        WHERE r.status='published' AND (r.variant_count > 0 OR b.release_id IS NOT NULL)
        ORDER BY r.id
    """))).mappings()
    faults = []
    for row in rows:
        receipt = row["source_version"] is not None
        expected = row["source_count"] if receipt else row["variant_count"]
        reason = None
        if receipt and row["source_version"] != row["version"]:
            reason = "backfill release version differs"
        elif row["actual_count"] != expected:
            reason = "native fact count differs from verified release count"
        elif not receipt and not row["native_import"]:
            reason = "legacy release requires a verified backfill receipt"
        if reason:
            faults.append({"release_id": row["id"], "reason": reason})
    return faults


async def main() -> None:
    try:
        async with get_session_factory()() as db:
            faults = await verify_native_cutover(db)
        print(json.dumps({"native_cutover_ready": not faults, "faults": faults}))
        if faults:
            raise SystemExit(1)
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
