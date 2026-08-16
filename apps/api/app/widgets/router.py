"""Widget API endpoints – public rendering and admin CRUD.

Public endpoints:
    GET  /layout/{page}         – JSON list of widget descriptors for a page
    GET  /widget/{name}         – rendered HTML fragment for one widget

Admin endpoints (require ADMINISTRATOR role):
    GET    /admin/widgets                – list all widgets
    POST   /admin/widgets                – create a widget
    GET    /admin/widgets/{name}         – get one widget
    PUT    /admin/widgets/{name}         – update a widget
    DELETE /admin/widgets/{name}         – deactivate a widget
    POST   /admin/widgets/{name}/preview – preview render with given params
    GET    /admin/widgets/health         – health/cache metrics
    PUT    /admin/layout/{page}          – upsert page layout
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db, get_redis
from ..core.exceptions import NotFoundError, ValidationError
from ..core.security import RoleName, has_role
from ..models.auth import User
from .cache import WidgetCache
from .data_sources.registry import WIDGET_DATA_SOURCE_REGISTRY, get_widget_data_source
from .deps import bearer_scheme, get_current_user, get_user_roles, require_admin
from .engine import get_engine, render_error_fragment
from .models import PageLayout, Widget, WidgetPermission
from .schemas import (
    LayoutResponse,
    LayoutUpdateRequest,
    WidgetCreate,
    WidgetDescriptor,
    WidgetHealthResponse,
    WidgetListResponse,
    WidgetPreviewRequest,
    WidgetResponse,
    WidgetUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["widgets"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _widget_to_response(w: Widget) -> WidgetResponse:
    return WidgetResponse(
        id=w.id,
        name=w.name,
        display_name=w.display_name,
        description=w.description,
        category=w.category,
        template_path=w.template_path,
        data_source=w.data_source,
        params_schema=w.params_schema or {},
        cache_ttl=w.cache_ttl,
        admin_config=w.admin_config or {},
        permissions=w.permissions,
        is_active=w.is_active,
        created_at=w.created_at,
        updated_at=w.updated_at,
    )


def _widget_to_descriptor(w: Widget) -> WidgetDescriptor:
    return WidgetDescriptor(
        name=w.name,
        display_name=w.display_name,
        category=w.category,
        params_schema=w.params_schema or {},
        cache_ttl=w.cache_ttl,
    )


def _check_widget_permission(widget: Widget, user: User | None) -> bool:
    """Return True if *user* may view *widget*."""
    if widget.permissions == WidgetPermission.PUBLIC.value:
        return True
    if user is None:
        return False
    if widget.permissions == WidgetPermission.AUTHENTICATED.value:
        return True
    if widget.permissions == WidgetPermission.ADMIN.value:
        return has_role(get_user_roles(user), RoleName.ADMINISTRATOR)
    return False


async def _resolve_optional_user(
    db: AsyncSession,
    credentials: HTTPAuthorizationCredentials | None,
) -> User | None:
    """Resolve a user from optional Bearer credentials, returning None on failure."""
    if credentials is None:
        return None
    try:
        return await get_current_user(db=db, credentials=credentials)
    except Exception:
        return None


async def _load_data_source(
    widget: Widget, params: dict[str, Any], db: AsyncSession
) -> dict[str, Any]:
    """Load context data from a registered widget data source."""
    context: dict[str, Any] = dict(params)
    if not widget.data_source:
        return context

    source_id = widget.data_source.strip()
    spec = get_widget_data_source(source_id)
    if spec is None:
        logger.warning("widget_data_source_not_registered: %s", source_id)
        raise ValidationError(
            f"Widget data source '{source_id}' is not registered",
            details={
                "data_source": source_id,
                "allowed": sorted(WIDGET_DATA_SOURCE_REGISTRY),
            },
        )

    try:
        validated_params = spec.params_schema.model_validate(params)
    except PydanticValidationError as exc:
        raise ValidationError(
            f"Invalid parameters for widget data source '{source_id}'",
            details={"data_source": source_id, "errors": exc.errors()},
        ) from exc

    try:
        data = await asyncio.wait_for(
            spec.handler(validated_params.model_dump(), db),
            timeout=spec.timeout_seconds,
        )
    except TimeoutError:
        logger.warning("widget_data_source_timeout: %s", source_id)
        return context
    except Exception as exc:
        logger.warning("widget_data_source_error source=%s error=%s", source_id, exc)
        return context

    try:
        validated_data = spec.return_schema.model_validate(data)
    except PydanticValidationError as exc:
        raise ValidationError(
            f"Invalid response from widget data source '{source_id}'",
            details={"data_source": source_id, "errors": exc.errors()},
        ) from exc

    context.update(validated_data.model_dump())
    return context


def _validate_data_source_identifier(data_source: str | None) -> None:
    """Reject unknown identifiers before they can be persisted in the DB."""
    if data_source is None:
        return
    source_id = data_source.strip()
    if get_widget_data_source(source_id) is None:
        raise ValidationError(
            f"Widget data source '{source_id}' is not registered",
            details={
                "data_source": source_id,
                "allowed": sorted(WIDGET_DATA_SOURCE_REGISTRY),
            },
        )


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@router.get("/layout/{page}", response_model=LayoutResponse)
async def get_layout(
    page: str,
    db: AsyncSession = Depends(get_db),
) -> LayoutResponse:
    """Return the ordered list of active, public widget descriptors for *page*."""
    result = await db.execute(
        select(PageLayout).where(
            PageLayout.page_name == page, PageLayout.is_active.is_(True)
        )
    )
    layout = result.scalar_one_or_none()
    if layout is None:
        raise NotFoundError(f"Layout for page '{page}' not found")

    widget_names = layout.widget_order or []
    descriptors: list[WidgetDescriptor] = []
    if widget_names:
        result = await db.execute(
            select(Widget).where(
                Widget.name.in_(widget_names), Widget.is_active.is_(True)
            )
        )
        widget_map = {w.name: w for w in result.scalars().all()}

        for name in widget_names:
            w = widget_map.get(name)
            if w is None:
                continue
            # Public layout endpoint only serves public widgets
            if w.permissions != WidgetPermission.PUBLIC.value:
                continue
            descriptors.append(_widget_to_descriptor(w))

    return LayoutResponse(
        page_name=layout.page_name,
        display_name=layout.display_name,
        widgets=descriptors,
    )


@router.get("/widget/{name}", response_class=HTMLResponse)
async def render_widget(
    name: str,
    request: Request,
    params: str = Query(default="{}", description="JSON-encoded widget parameters"),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Render a single widget to sanitized HTML.

    Parameters are passed as a JSON-encoded query string
    (``?params={"gene":"Glyma.01G000100"}``).  Rendered output is cached in
    Redis per widget+params combination.  Errors degrade to a safe HTML
    fragment rather than a 500.
    """
    # Parse params JSON
    try:
        params_dict: dict[str, Any] = json.loads(params) if params else {}
    except (json.JSONDecodeError, TypeError):
        params_dict = {}

    # Load widget
    result = await db.execute(
        select(Widget).where(Widget.name == name, Widget.is_active.is_(True))
    )
    widget = result.scalar_one_or_none()
    if widget is None:
        return HTMLResponse(
            content=render_error_fragment(name, f"Widget '{name}' not found"),
            status_code=404,
            media_type="text/html; charset=utf-8",
        )

    # Resolve optional user for permission checks
    user = await _resolve_optional_user(db, credentials)

    if not _check_widget_permission(widget, user):
        return HTMLResponse(
            content=render_error_fragment(name, "Permission denied"),
            status_code=403,
            media_type="text/html; charset=utf-8",
        )

    engine = get_engine()
    redis = get_redis()
    cache = WidgetCache(redis)

    async def _render() -> str:
        context = await _load_data_source(widget, params_dict, db)
        context["widget_name"] = name
        context["params"] = params_dict
        return engine.render(widget.template_path, context, widget_name=name)

    try:
        html = await cache.get_or_render(name, params_dict, widget.cache_ttl, _render)
    except ValidationError:
        raise
    except Exception as exc:
        logger.warning("widget_render_failed", widget=name, error=str(exc))
        html = render_error_fragment(name, str(exc))

    return HTMLResponse(
        content=html,
        media_type="text/html; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get("/admin/widgets", response_model=WidgetListResponse)
async def admin_list_widgets(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    category: str | None = Query(default=None),
) -> WidgetListResponse:
    """List all widgets (including inactive) with pagination."""
    conditions = []
    if category:
        conditions.append(Widget.category == category)
    where_clause = conditions[0] if conditions else None
    total_stmt = select(func.count()).select_from(Widget)
    if where_clause is not None:
        total_stmt = total_stmt.where(where_clause)
    total = int((await db.execute(total_stmt)).scalar() or 0)
    stmt = select(Widget).order_by(Widget.category, Widget.name)
    if where_clause is not None:
        stmt = stmt.where(where_clause)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    items = [_widget_to_response(w) for w in result.scalars().all()]
    return WidgetListResponse(items=items, total=total)


@router.post("/admin/widgets", response_model=WidgetResponse, status_code=201)
async def admin_create_widget(
    data: WidgetCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> WidgetResponse:
    """Create a new widget definition."""
    _validate_data_source_identifier(data.data_source)
    existing = await db.execute(select(Widget).where(Widget.name == data.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409, detail=f"Widget '{data.name}' already exists"
        )

    widget = Widget(
        name=data.name,
        display_name=data.display_name,
        description=data.description,
        category=data.category.value,
        template_path=data.template_path,
        data_source=data.data_source,
        params_schema=data.params_schema,
        cache_ttl=data.cache_ttl,
        admin_config=data.admin_config,
        permissions=data.permissions.value,
        is_active=data.is_active,
    )
    db.add(widget)
    await db.commit()
    await db.refresh(widget)
    return _widget_to_response(widget)


@router.get("/admin/widgets/{name}", response_model=WidgetResponse)
async def admin_get_widget(
    name: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> WidgetResponse:
    """Get a single widget by name."""
    result = await db.execute(select(Widget).where(Widget.name == name))
    widget = result.scalar_one_or_none()
    if widget is None:
        raise NotFoundError(f"Widget '{name}' not found")
    return _widget_to_response(widget)


@router.put("/admin/widgets/{name}", response_model=WidgetResponse)
async def admin_update_widget(
    name: str,
    data: WidgetUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> WidgetResponse:
    """Update a widget definition and invalidate its cache."""
    result = await db.execute(select(Widget).where(Widget.name == name))
    widget = result.scalar_one_or_none()
    if widget is None:
        raise NotFoundError(f"Widget '{name}' not found")

    update_data = data.model_dump(exclude_unset=True)
    if "data_source" in update_data:
        _validate_data_source_identifier(update_data["data_source"])
    for key, value in update_data.items():
        if key in ("category", "permissions") and value is not None:
            value = value.value if hasattr(value, "value") else value
        setattr(widget, key, value)

    # Invalidate cache on update
    try:
        redis = get_redis()
        cache = WidgetCache(redis)
        await cache.invalidate(name)
    except Exception:
        pass

    await db.commit()
    await db.refresh(widget)
    return _widget_to_response(widget)


@router.delete("/admin/widgets/{name}", status_code=204)
async def admin_delete_widget(
    name: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Deactivate a widget (soft delete via is_active flag) and invalidate cache."""
    result = await db.execute(select(Widget).where(Widget.name == name))
    widget = result.scalar_one_or_none()
    if widget is None:
        raise NotFoundError(f"Widget '{name}' not found")

    widget.is_active = False

    try:
        redis = get_redis()
        cache = WidgetCache(redis)
        await cache.invalidate(name)
    except Exception:
        pass

    await db.commit()
    return None


@router.post("/admin/widgets/{name}/preview", response_class=HTMLResponse)
async def admin_preview_widget(
    name: str,
    data: WidgetPreviewRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Preview-render a widget with given parameters (bypasses cache)."""
    result = await db.execute(select(Widget).where(Widget.name == name))
    widget = result.scalar_one_or_none()
    if widget is None:
        raise NotFoundError(f"Widget '{name}' not found")

    engine = get_engine()
    context = await _load_data_source(widget, data.params, db)
    context["widget_name"] = name
    context["params"] = data.params
    html = engine.render(widget.template_path, context, widget_name=name)

    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")


@router.get("/admin/widgets/health", response_model=WidgetHealthResponse)
async def admin_widget_health(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> WidgetHealthResponse:
    """Return widget system health metrics."""
    from sqlalchemy import func as sa_func

    total_result = await db.execute(select(sa_func.count()).select_from(Widget))
    total_widgets = total_result.scalar() or 0

    active_result = await db.execute(
        select(sa_func.count())
        .select_from(Widget)
        .where(Widget.is_active.is_(True))
    )
    active_widgets = active_result.scalar() or 0

    layouts_result = await db.execute(
        select(sa_func.count()).select_from(PageLayout)
    )
    total_layouts = layouts_result.scalar() or 0

    active_layouts_result = await db.execute(
        select(sa_func.count())
        .select_from(PageLayout)
        .where(PageLayout.is_active.is_(True))
    )
    active_layouts = active_layouts_result.scalar() or 0

    engine = get_engine()
    builtin_templates = engine.list_builtin_templates()

    from datetime import UTC, datetime
    return WidgetHealthResponse(
        total_widgets=total_widgets,
        active_widgets=active_widgets,
        total_layouts=total_layouts,
        active_layouts=active_layouts,
        builtin_templates=builtin_templates,
        cache_backend="redis",
        widgets=[],
        generated_at=datetime.now(UTC),
    )


@router.put("/admin/layout/{page}", response_model=LayoutResponse)
async def admin_update_layout(
    page: str,
    data: LayoutUpdateRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LayoutResponse:
    """Create or update the widget layout for a page."""
    result = await db.execute(
        select(PageLayout).where(PageLayout.page_name == page)
    )
    layout = result.scalar_one_or_none()

    if layout is None:
        layout = PageLayout(
            page_name=page,
            display_name=data.display_name,
            widget_order=data.widget_order,
            is_active=data.is_active if data.is_active is not None else True,
        )
        db.add(layout)
    else:
        if data.display_name is not None:
            layout.display_name = data.display_name
        if data.widget_order is not None:
            layout.widget_order = data.widget_order
        if data.is_active is not None:
            layout.is_active = data.is_active

    await db.commit()
    await db.refresh(layout)

    descriptors: list[WidgetDescriptor] = []
    if layout.widget_order:
        w_result = await db.execute(
            select(Widget).where(Widget.name.in_(layout.widget_order))
        )
        w_map = {w.name: w for w in w_result.scalars().all()}
        for wn in layout.widget_order:
            w = w_map.get(wn)
            if w is not None:
                descriptors.append(_widget_to_descriptor(w))

    return LayoutResponse(
        page_name=layout.page_name,
        display_name=layout.display_name,
        widgets=descriptors,
    )
