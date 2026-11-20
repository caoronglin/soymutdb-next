"""Admin endpoints: audit-log inspection, export, and timeout config \
(administrator-only)."""

from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import String, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.audit import compute_online_duration
from ...core.audit_policy import declares_audit
from ...core.config import get_settings
from ...core.database import get_db, get_session_factory
from ...core.exceptions import ConflictError, NotFoundError, ValidationError
from ...core.security import require_admin_roles
from ...core.spreadsheet import neutralize_spreadsheet_cell
from ...models.auth import AuditLog, User
from ...models.content import Release, ReleaseStatus
from ...models.data_publishing import ActiveRelease, DataSet, ReleaseDataSet
from ...models.import_task import ImportTask, ImportTaskStatus
from ...models.variant import VariantSummary
from ...schemas.analytics import (
    AdminDashboardSeries,
    AdminDashboardStats,
    ImportThroughputPoint,
    QueryLatencyPoint,
)
from ...schemas.data_publishing import (
    ReleaseActionRequest,
    ReleaseCreateRequest,
    ReleaseReadyRequest,
)
from ...services.postgres_variant_service import PostgresVariantService
from ...services.release_service import (
    ReleaseNotReady,
    mark_release_ready,
    publish_release,
    rollback_release,
    validate_release,
)
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin", tags=["admin"])

settings = get_settings()
variant_service = PostgresVariantService()


def _require_admin(current_user: User) -> None:
    """Raise :class:`AuthorizationError` unless *current_user* is an administrator."""
    require_admin_roles(get_user_roles(current_user))


def _release_to_dict(
    release: Release, datasets: list[DataSet], active_id: int | None
) -> dict[str, Any]:
    return {
        "id": release.id,
        "version": release.version,
        "name": release.name,
        "description": release.description,
        "assembly": release.assembly,
        "status": release.status,
        "manifest": release.manifest,
        "readiness": (release.manifest or {}).get("readiness", {}),
        "active_release_id": active_id,
        "datasets": [
            {"id": ds.id, "type": ds.type, "status": ds.status, "source_objects": ds.source_objects,
             "provenance": ds.validation_evidence or {}}
            for ds in datasets
        ],
        "audit_action": f"release_{release.status}",
    }


async def _get_release(
    db: AsyncSession, release_id: int
) -> tuple[Release, list[DataSet], int | None]:
    release = await db.scalar(select(Release).where(Release.id == release_id))
    if release is None:
        raise NotFoundError(f"Release {release_id} not found")
    datasets = list((await db.execute(
        select(DataSet).join(ReleaseDataSet, ReleaseDataSet.data_set_id == DataSet.id)
        .where(ReleaseDataSet.release_id == release_id)
    )).scalars())
    active_id = await db.scalar(select(ActiveRelease.release_id).where(ActiveRelease.id == 1))
    return release, datasets, active_id


def _release_failure(exc: ReleaseNotReady) -> ValidationError:
    return ValidationError(str(exc), details={"code": "release_not_ready"})


# ---------------------------------------------------------------------------
# Data publishing Release lifecycle
# ---------------------------------------------------------------------------


@router.post("/releases", status_code=status.HTTP_201_CREATED)
@declares_audit("release_created", roles={"administrator"})
async def create_release(
    body: ReleaseCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(current_user)
    if await db.scalar(select(Release).where(Release.version == body.version)):
        raise ConflictError("Release version already exists")
    datasets = list(
        (await db.execute(select(DataSet).where(DataSet.id.in_(body.data_set_ids)))).scalars()
    )
    if len(datasets) != len(set(body.data_set_ids)):
        raise NotFoundError("One or more data sets were not found")
    release = Release(
        version=body.version, name=body.name, description=body.description, assembly=body.assembly
    )
    db.add(release)
    await db.flush()
    for dataset in datasets:
        db.add(ReleaseDataSet(release_id=release.id, data_set_id=dataset.id))
    db.add(
        AuditLog(
            user_id=current_user.id,
            action="release_created",
            resource_type="release",
            resource_id=str(release.id),
            new_value={"version": release.version, "assembly": release.assembly},
        )
    )
    await db.commit()
    await db.refresh(release)
    return _release_to_dict(
        release,
        datasets,
        await db.scalar(select(ActiveRelease.release_id).where(ActiveRelease.id == 1)),
    )


@router.post("/releases/{release_id}/validate")
@declares_audit("release_validated", roles={"administrator"})
async def validate_admin_release(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(current_user)
    try:
        await validate_release(db, release_id=release_id, actor_id=current_user.id)
        await db.commit()
    except ReleaseNotReady as exc:
        await db.rollback()
        raise _release_failure(exc) from exc
    release, datasets, active_id = await _get_release(db, release_id)
    return _release_to_dict(release, datasets, active_id)


@router.post("/releases/{release_id}/ready")
@declares_audit("release_ready", roles={"administrator"})
async def ready_admin_release(
    release_id: int,
    body: ReleaseReadyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(current_user)
    try:
        await mark_release_ready(
            db,
            release_id=release_id,
            actor_id=current_user.id,
            manifest=body.manifest,
            readiness=body.readiness,
        )
        await db.commit()
    except ReleaseNotReady as exc:
        await db.rollback()
        raise _release_failure(exc) from exc
    release, datasets, active_id = await _get_release(db, release_id)
    return _release_to_dict(release, datasets, active_id)


@router.post("/releases/{release_id}/publish")
@declares_audit("release_published", roles={"administrator"})
async def publish_admin_release(
    release_id: int,
    body: ReleaseActionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(current_user)
    try:
        await publish_release(
            db,
            release_id=release_id,
            actor_id=current_user.id,
            reason=body.reason,
            request_id=getattr(request.state, "request_id", None),
        )
    except ReleaseNotReady as exc:
        await db.rollback()
        raise _release_failure(exc) from exc
    release, datasets, active_id = await _get_release(db, release_id)
    return _release_to_dict(release, datasets, active_id)


@router.post("/releases/{release_id}/rollback")
@declares_audit("release_rolled_back", roles={"administrator"})
async def rollback_admin_release(
    release_id: int,
    body: ReleaseActionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(current_user)
    try:
        await rollback_release(
            db,
            release_id=release_id,
            actor_id=current_user.id,
            reason=body.reason,
            request_id=getattr(request.state, "request_id", None),
        )
    except ReleaseNotReady as exc:
        await db.rollback()
        raise _release_failure(exc) from exc
    release, datasets, active_id = await _get_release(db, release_id)
    return _release_to_dict(release, datasets, active_id)


@router.get("/releases/{release_id}")
async def get_admin_release(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(current_user)
    release, datasets, active_id = await _get_release(db, release_id)
    return _release_to_dict(release, datasets, active_id)


def _build_conditions(
    search: str | None,
    action: str | None,
    user_id: uuid.UUID | None,
    ip_address: str | None,
    start_date: datetime | None,
    end_date: datetime | None,
) -> list[Any]:
    """Build the common filter conditions shared by the list & export endpoints."""
    conditions: list[Any] = []
    if search:
        pattern = f"%{search}%"
        conditions.append(
            AuditLog.action.ilike(pattern)
            | AuditLog.resource_type.ilike(pattern)
            | AuditLog.resource_id.ilike(pattern)
            | cast(AuditLog.ip_address, String).ilike(pattern)
            | AuditLog.user.has(User.username.ilike(pattern))
        )
    if action:
        conditions.append(AuditLog.action == action)
    if user_id:
        conditions.append(AuditLog.user_id == user_id)
    if ip_address:
        conditions.append(AuditLog.ip_address == ip_address)
    if start_date:
        conditions.append(AuditLog.timestamp >= start_date)
    if end_date:
        conditions.append(AuditLog.timestamp <= end_date)
    return conditions


def _audit_log_to_item(log: AuditLog) -> dict[str, Any]:
    """Serialise an :class:`AuditLog` row into the API item shape."""
    details = log.new_value
    status_val = "success"
    if isinstance(details, dict) and details.get("status"):
        status_val = str(details["status"])
    return {
        "id": log.id,
        "timestamp": log.timestamp.isoformat() if log.timestamp else None,
        "actor": log.user.username if log.user else None,
        "action": log.action,
        "resource": log.resource_type,
        "resourceId": log.resource_id,
        "ipAddress": log.ip_address,
        "details": details,
        "status": status_val,
    }


# ---------------------------------------------------------------------------
# Audit-log list & stats
# ---------------------------------------------------------------------------


@router.get("/audit-logs")
async def list_audit_logs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    search: str | None = Query(default=None),
    action: str | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    ip_address: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
) -> dict[str, Any]:
    """Paginated audit logs with filtering (administrator-only).

    Joins with the User table (via the eager ``user`` relationship) to populate
    the ``actor`` field with the username of the user who performed the action.
    """
    _require_admin(current_user)

    conditions = _build_conditions(search, action, user_id, ip_address, start_date, end_date)
    where_clause = and_(*conditions) if conditions else None

    # Total count (for pagination metadata).
    count_stmt = select(func.count()).select_from(AuditLog)
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
    total = int(await db.scalar(count_stmt) or 0)

    # Paginated rows, newest first.  The ``user`` relationship is eagerly
    # loaded (lazy="joined") so no explicit join is required.
    offset = (page - 1) * page_size
    stmt = select(AuditLog).order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
    if where_clause is not None:
        stmt = stmt.where(where_clause)
    stmt = stmt.offset(offset).limit(page_size)
    result = await db.execute(stmt)
    logs = result.scalars().all()

    items = [_audit_log_to_item(log) for log in logs]
    has_more = (offset + len(items)) < total

    return {"items": items, "total": total, "has_more": has_more}


@router.get("/audit-logs/stats")
async def audit_log_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    period: str = Query(default="day", pattern="^(day|week|month)$"),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
) -> dict[str, Any]:
    """Aggregate statistics for audit-log visualisation (administrator-only)."""
    _require_admin(current_user)

    if start_date is None:
        start_date = datetime.now(UTC) - timedelta(days=30)
    if end_date is None:
        end_date = datetime.now(UTC)

    where_clause = and_(
        AuditLog.timestamp >= start_date,
        AuditLog.timestamp <= end_date,
    )

    # --- Login trend (grouped by period) -----------------------------------
    bucket = func.date_trunc(period, AuditLog.timestamp).label("bucket")
    trend_stmt = (
        select(bucket, func.count(AuditLog.id))
        .where(and_(where_clause, AuditLog.action == "login"))
        .group_by(bucket)
        .order_by(bucket)
    )
    trend_result = await db.execute(trend_stmt)
    login_trend: list[dict[str, Any]] = []
    for value, count in trend_result.all():
        if value is None:
            continue
        date_str = value.strftime("%Y-%m-%d") if hasattr(value, "strftime") else str(value)[:10]
        login_trend.append({"date": date_str, "count": int(count)})

    # --- Action distribution -----------------------------------------------
    action_stmt = (
        select(AuditLog.action, func.count(AuditLog.id))
        .where(where_clause)
        .group_by(AuditLog.action)
        .order_by(func.count(AuditLog.id).desc())
    )
    action_result = await db.execute(action_stmt)
    action_distribution = [{"action": act, "count": int(cnt)} for act, cnt in action_result.all()]

    # --- IP distribution (city left as null – no external geo-IP lookup) ----
    ip_stmt = (
        select(AuditLog.ip_address, func.count(AuditLog.id))
        .where(and_(where_clause, AuditLog.ip_address.isnot(None)))
        .group_by(AuditLog.ip_address)
        .order_by(func.count(AuditLog.id).desc())
    )
    ip_result = await db.execute(ip_stmt)
    ip_distribution = [{"ip": ip, "count": int(cnt), "city": None} for ip, cnt in ip_result.all()]

    # --- Totals -------------------------------------------------------------
    total_logins = int(
        await db.scalar(
            select(func.count(AuditLog.id)).where(and_(where_clause, AuditLog.action == "login"))
        )
        or 0
    )
    total_actions = int(await db.scalar(select(func.count(AuditLog.id)).where(where_clause)) or 0)
    unique_ips = int(
        await db.scalar(
            select(func.count(func.distinct(AuditLog.ip_address))).where(
                and_(where_clause, AuditLog.ip_address.isnot(None))
            )
        )
        or 0
    )

    return {
        "loginTrend": login_trend,
        "actionDistribution": action_distribution,
        "ipDistribution": ip_distribution,
        "totalLogins": total_logins,
        "totalActions": total_actions,
        "uniqueIps": unique_ips,
    }


# ---------------------------------------------------------------------------
# Online duration
# ---------------------------------------------------------------------------


@router.get("/audit-logs/online-duration")
async def audit_log_online_duration(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    user_id: uuid.UUID | None = Query(default=None),
) -> list[dict[str, Any]]:
    """Compute online duration (seconds) per user from login/logout audit entries.

    Pairs consecutive login/logout events per user.  Returns a list of dicts
    with ``user_id``, ``username``, ``total_seconds``, and ``login_count``.
    (Administrator-only.)
    """
    _require_admin(current_user)
    return await compute_online_duration(db, user_id=user_id)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


@router.get("/audit-logs/export")
async def export_audit_logs(
    request: Request,
    current_user: User = Depends(get_current_user),
    search: str | None = Query(default=None),
    action: str | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    ip_address: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
) -> StreamingResponse:
    """Stream audit logs as a CSV download (administrator-only).

    A dedicated session is opened inside the generator so that streaming is
    not coupled to the request-scoped dependency lifetime.
    """
    _require_admin(current_user)

    conditions = _build_conditions(search, action, user_id, ip_address, start_date, end_date)

    columns = [
        "timestamp",
        "actor",
        "action",
        "resource",
        "resource_id",
        "ip_address",
        "details",
    ]

    async def generate() -> AsyncIterator[str]:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(columns)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        batch_size = 500
        last_timestamp: datetime | None = None
        last_id: int | None = None
        factory = get_session_factory()
        async with factory() as session:
            while True:
                stmt = select(AuditLog).order_by(
                    AuditLog.timestamp.desc(), AuditLog.id.desc()
                )
                cursor_conditions = list(conditions)
                if last_timestamp is not None and last_id is not None:
                    cursor_conditions.append(
                        (AuditLog.timestamp < last_timestamp)
                        | (
                            (AuditLog.timestamp == last_timestamp)
                            & (AuditLog.id < last_id)
                        )
                    )
                if cursor_conditions:
                    stmt = stmt.where(and_(*cursor_conditions))
                stmt = stmt.limit(batch_size)
                result = await session.execute(stmt)
                logs = result.scalars().all()
                if not logs:
                    break
                for log in logs:
                    actor = log.user.username if log.user else ""
                    details = log.new_value
                    writer.writerow(
                        [
                            log.timestamp.isoformat() if log.timestamp else "",
                            neutralize_spreadsheet_cell(actor),
                            neutralize_spreadsheet_cell(log.action),
                            neutralize_spreadsheet_cell(log.resource_type),
                            # `resource_id` carries the caller's raw search
                            # query, so it is the cell an outsider controls.
                            neutralize_spreadsheet_cell(log.resource_id or ""),
                            neutralize_spreadsheet_cell(log.ip_address or ""),
                            neutralize_spreadsheet_cell(
                                json.dumps(details) if details is not None else ""
                            ),
                        ]
                    )
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)

                last_log = logs[-1]
                if last_log.timestamp is None:
                    break
                last_timestamp = last_log.timestamp
                last_id = last_log.id
                if len(logs) < batch_size:
                    break

    headers = {"Content-Disposition": "attachment; filename=audit-logs.csv"}
    return StreamingResponse(generate(), media_type="text/csv", headers=headers)


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------


@router.get("/audit-logs/export-excel")
async def export_audit_logs_excel(
    current_user: User = Depends(get_current_user),
    search: str | None = Query(default=None),
    action: str | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    ip_address: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    limit: int = Query(
        default=10_000,
        ge=1,
        le=50_000,
        description="Maximum XLSX rows. Use the streaming CSV export for larger result sets.",
    ),
) -> StreamingResponse:
    """Export a bounded audit-log slice as an Excel (.xlsx) file.

    XLSX generation is intentionally capped because ``openpyxl`` constructs a
    workbook in process memory. Use the streaming CSV endpoint for complete,
    high-volume exports.
    """
    _require_admin(current_user)
    import openpyxl  # noqa: PLC0415 — lazy import
    from openpyxl.styles import Font, PatternFill  # noqa: PLC0415
    from openpyxl.utils import get_column_letter  # noqa: PLC0415 — lazy import

    factory = get_session_factory()
    async with factory() as session:
        conditions = _build_conditions(search, action, user_id, ip_address, start_date, end_date)
        where_clause = and_(*conditions) if conditions else None

        stmt = select(AuditLog).order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        if where_clause is not None:
            stmt = stmt.where(where_clause)

        # Fetch one extra row to reject broad exports predictably instead of
        # allowing a request to consume unbounded database and process memory.
        result = await session.execute(stmt.limit(limit + 1))
        logs = result.scalars().all()
        if len(logs) > limit:
            raise ValidationError(
                "XLSX export exceeds the requested limit; narrow filters or use the "
                "streaming CSV export."
            )

        wb = openpyxl.Workbook()
        ws = wb.active
        assert ws is not None, "a new Workbook always has an active sheet"
        ws.title = "Audit Logs"

        # Header styling.
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        headers = [
            "Timestamp", "Actor", "Action", "Resource", "Resource ID", "IP Address", "Details"
        ]

        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill

        for row_idx, log in enumerate(logs, start=2):
            ws.cell(row=row_idx, column=1, value=log.timestamp.isoformat() if log.timestamp else "")
            ws.cell(
                row=row_idx,
                column=2,
                value=neutralize_spreadsheet_cell(log.user.username if log.user else ""),
            )
            ws.cell(row=row_idx, column=3, value=neutralize_spreadsheet_cell(log.action))
            ws.cell(row=row_idx, column=4, value=neutralize_spreadsheet_cell(log.resource_type))
            ws.cell(row=row_idx, column=5, value=neutralize_spreadsheet_cell(log.resource_id or ""))
            ws.cell(row=row_idx, column=6, value=neutralize_spreadsheet_cell(log.ip_address or ""))
            ws.cell(
                row=row_idx,
                column=7,
                value=neutralize_spreadsheet_cell(
                    json.dumps(log.new_value) if log.new_value is not None else ""
                ),
            )

        # Auto-adjust column widths.
        for col_idx, header in enumerate(headers, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = max(
                len(header) + 4, 20
            )

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=audit-logs.xlsx"},
    )


# ---------------------------------------------------------------------------
# Timeout config (centralized)
# ---------------------------------------------------------------------------


@router.get("/timeout-config")
async def get_timeout_config(
    current_user: User = Depends(get_current_user),
) -> dict[str, int]:
    """Return the centralized timeout configuration (authenticated users).

    These values are set in the backend ``Settings`` and are used by the
    frontend API client to configure request timeouts.
    """
    return {
        "api_timeout_critical": settings.api_timeout_critical,
        "api_timeout_non_critical": settings.api_timeout_non_critical,
        "api_timeout_file_transfer": settings.api_timeout_file_transfer,
    }


# ---------------------------------------------------------------------------
# Dashboard overview (system stats & trend series)
# ---------------------------------------------------------------------------


def _pct_change(current: float, previous: float) -> float:
    """Percent change from *previous* to *current* (0.0 when not computable)."""
    if previous <= 0:
        return 0.0
    return round((current - previous) / previous * 100.0, 2)


async def _total_variants(db: AsyncSession) -> int:
    """Total variant count: native PostgreSQL projection first, fallback, 0 last."""
    try:
        variant_stats = await variant_service.get_dashboard_stats(public_only=False)
        return int(variant_stats.get("total_variants", 0))
    except Exception:
        return await db.scalar(select(func.count(VariantSummary.id))) or 0


@router.get(
    "/dashboard-stats",
    response_model=AdminDashboardStats,
    summary="System overview statistics",
)
async def admin_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AdminDashboardStats:
    """High-level system numbers for the admin dashboard.

    All values are real aggregations (users/releases from PostgreSQL, variant
    count from the native PostgreSQL projection with a ``variant_summaries``
    fallback).  Change percentages are computed between the last 30 days and
    the previous 30 days; metrics without a temporal source report 0.0.
    """
    _require_admin(current_user)
    now = datetime.now(UTC)
    since_30 = now - timedelta(days=30)
    since_60 = now - timedelta(days=60)

    total_users = (
        await db.scalar(
            select(func.count(User.id)).where(User.is_deleted.is_(False))
        )
        or 0
    )
    active_releases = (
        await db.scalar(
            select(func.count(Release.id)).where(
                Release.status == ReleaseStatus.ACTIVE.value
            )
        )
        or 0
    )
    users_30 = (
        await db.scalar(
            select(func.count(User.id)).where(
                User.is_deleted.is_(False), User.created_at >= since_30
            )
        )
        or 0
    )
    users_60 = (
        await db.scalar(
            select(func.count(User.id)).where(
                User.is_deleted.is_(False), User.created_at >= since_60
            )
        )
        or 0
    )
    releases_30 = (
        await db.scalar(
            select(func.count(Release.id)).where(
                Release.status == ReleaseStatus.ACTIVE.value,
                Release.published_at >= since_30,
            )
        )
        or 0
    )
    releases_60 = (
        await db.scalar(
            select(func.count(Release.id)).where(
                Release.status == ReleaseStatus.ACTIVE.value,
                Release.published_at >= since_60,
            )
        )
        or 0
    )

    total_variants = await _total_variants(db)

    # 95th-percentile query latency from the analytics events (best-effort).
    try:
        query_p95_ms = await variant_service.get_query_latency_percentile(
            percentile=0.95, days=30
        )
    except Exception:
        query_p95_ms = 0.0

    return AdminDashboardStats(
        total_users=int(total_users),
        active_releases=int(active_releases),
        total_variants=int(total_variants),
        query_p95_ms=round(float(query_p95_ms), 2),
        users_change=_pct_change(float(users_30), float(users_60 - users_30)),
        releases_change=_pct_change(
            float(releases_30), float(releases_60 - releases_30)
        ),
        variants_change=0.0,
        query_p95_change=0.0,
    )


@router.get(
    "/dashboard-series",
    response_model=AdminDashboardSeries,
    summary="Dashboard trend series",
)
async def admin_dashboard_series(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    days: int = Query(default=30, ge=1, le=365),
) -> AdminDashboardSeries:
    """Time series for the admin dashboard charts.

    - ``import_throughput``: daily import tasks from the PostgreSQL
      ``import_tasks`` table, split into completed vs. failed/cancelled vs.
      still queued or running.
    - ``query_latency``: daily p50/p95/p99 percentiles from the PostgreSQL
      analytics events (empty when that query is unavailable).
    - ``storage_growth``: no reliable storage source exists yet — empty.
    """
    _require_admin(current_user)
    since = datetime.now(UTC) - timedelta(days=days)

    import_stmt = (
        select(
            func.date(ImportTask.submitted_at),
            ImportTask.status,
            func.count(),
        )
        .where(ImportTask.submitted_at >= since)
        .group_by(func.date(ImportTask.submitted_at), ImportTask.status)
        .order_by(func.date(ImportTask.submitted_at))
    )
    rows = (await db.execute(import_stmt)).all()

    # Every status lands in a bucket. The first version only counted COMPLETED
    # and FAILED, so queued/validating/ingesting tasks vanished: a day whose
    # imports were still executing rendered as a day with no activity at all.
    # Anything that is not a terminal outcome is counted as in flight, so a
    # status added to `ImportStatus` later cannot silently under-report again.
    completed_states = {ImportTaskStatus.COMPLETED.value}
    failed_states = {ImportTaskStatus.FAILED.value}
    by_day: dict[str, dict[str, int]] = {}
    for day, status_val, count in rows:
        key = day.isoformat() if hasattr(day, "isoformat") else str(day)
        entry = by_day.setdefault(key, {"imported": 0, "failed": 0, "running": 0})
        status_text = str(status_val)
        if status_text in completed_states:
            entry["imported"] += int(count)
        elif status_text in failed_states:
            entry["failed"] += int(count)
        else:
            entry["running"] += int(count)

    import_throughput = [
        ImportThroughputPoint(date=day, **entry) for day, entry in sorted(by_day.items())
    ]

    try:
        latency_rows = await variant_service.get_query_latency_series(days=days)
    except Exception:
        latency_rows = []
    query_latency = [
        QueryLatencyPoint(
            date=str(row["date"]),
            p50=float(row.get("p50", 0) or 0),
            p95=float(row.get("p95", 0) or 0),
            p99=float(row.get("p99", 0) or 0),
        )
        for row in latency_rows
    ]

    return AdminDashboardSeries(
        import_throughput=import_throughput,
        query_latency=query_latency,
        storage_growth=[],
    )
