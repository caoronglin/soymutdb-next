"""Health-check endpoints: liveness and readiness.

The readiness probe returns HTTP 503 when a downstream dependency is
unavailable, so that orchestrators do not route traffic to this instance.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
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
    """Readiness probe with baseline and extended dependency semantics.

    Baseline gates PostgreSQL only; extended also gates ClickHouse and Redis.
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

    # Optional integrations are probed only in the full stack.  Baseline must
    # remain ready with PostgreSQL alone and report disabled capabilities instead
    # of treating absent services as an API outage.
    if get_settings().deployment_mode == "extended":
        # ClickHouse
        try:
            ch = ClickHouseService()
            clickhouse_healthy = await ch.ping()
            checks["clickhouse"] = {"healthy": clickhouse_healthy, "required": True}
            if not clickhouse_healthy:
                overall = False
        except Exception as exc:
            checks["clickhouse"] = {
                "healthy": False, "required": True, "error": type(exc).__name__
            }
            overall = False

        # Redis
        try:
            redis_healthy = bool(await get_redis().ping())
            checks["redis"] = {"healthy": redis_healthy, "required": True}
            if not redis_healthy:
                overall = False
        except Exception as exc:
            checks["redis"] = {"healthy": False, "required": True, "error": type(exc).__name__}
            overall = False
    else:
        checks["clickhouse"] = {"healthy": None, "required": False, "status": "disabled"}
        checks["redis"] = {"healthy": None, "required": False, "status": "disabled"}

    if not overall:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ok" if overall else "degraded", "checks": checks}
