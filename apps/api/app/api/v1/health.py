"""Health-check endpoints: liveness and readiness.

The readiness probe returns HTTP 503 when a downstream dependency is
unavailable, so that orchestrators do not route traffic to this instance.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db, get_redis
from ...services.clickhouse_service import ClickHouseService

router = APIRouter(prefix="/health", tags=["health"])


async def _readiness_db(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    """Resolve the database session through FastAPI's overrideable dependency."""
    return db


@router.get("/live")
async def liveness() -> dict[str, str]:
    """Liveness probe – always returns 200 if the process is alive."""
    return {"status": "ok"}


@router.get("/ready")
async def readiness(
    response: Response,
    db: AsyncSession = Depends(_readiness_db),
) -> dict[str, object]:
    """Readiness probe – checks PostgreSQL, ClickHouse, and Redis.

    Returns 503 if any dependency is unreachable.
    """
    checks: dict[str, dict[str, object]] = {}
    overall = True

    # PostgreSQL
    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = {"healthy": True}
    except Exception as exc:
        checks["postgres"] = {"healthy": False, "error": type(exc).__name__}
        overall = False

    # ClickHouse
    try:
        ch = ClickHouseService()
        clickhouse_healthy = await ch.ping()
        checks["clickhouse"] = {"healthy": clickhouse_healthy}
        if not clickhouse_healthy:
            overall = False
    except Exception as exc:
        checks["clickhouse"] = {"healthy": False, "error": type(exc).__name__}
        overall = False

    # Redis
    try:
        redis_healthy = bool(await get_redis().ping())
        checks["redis"] = {"healthy": redis_healthy}
        if not redis_healthy:
            overall = False
    except Exception as exc:
        checks["redis"] = {"healthy": False, "error": type(exc).__name__}
        overall = False

    if not overall:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ok" if overall else "degraded", "checks": checks}
