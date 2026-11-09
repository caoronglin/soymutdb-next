"""Persistence for saved admin data views.

Views are plain configuration rows over the existing release-scoped public
read APIs. This module never queries biological tables; it only resolves which
source vocabulary a view belongs to and keeps the per-source invariants:
unique names and at most one default view.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.data_views import AdminDataView
from ..schemas.data_views import (
    DEFAULT_VISIBLE_FIELDS,
    SOURCE_FIELDS,
    SOURCE_FILTER_FIELDS,
    AdminDataViewBase,
    AdminDataViewCreate,
    AdminDataViewUpdate,
    DataViewSourceInfo,
)

DATA_VIEW_SOURCES: tuple[str, ...] = tuple(SOURCE_FIELDS)
DATA_VIEW_KINDS: tuple[str, ...] = ("grid", "kanban", "gallery")


def source_catalog() -> list[DataViewSourceInfo]:
    return [
        DataViewSourceInfo(
            source=source,  # type: ignore[arg-type]
            fields=list(SOURCE_FIELDS[source]),
            filter_fields=list(SOURCE_FILTER_FIELDS[source]),
            default_fields=list(DEFAULT_VISIBLE_FIELDS[source]),
        )
        for source in DATA_VIEW_SOURCES
    ]


async def list_views(
    db: AsyncSession, *, source: str | None = None
) -> list[AdminDataView]:
    statement = select(AdminDataView)
    if source is not None:
        statement = statement.where(AdminDataView.source == source)
    result = await db.execute(
        statement.order_by(
            AdminDataView.source,
            AdminDataView.is_default.desc(),
            AdminDataView.name,
        )
    )
    return list(result.scalars().all())


async def create_view(db: AsyncSession, payload: AdminDataViewCreate) -> AdminDataView:
    await _assert_name_free(db, payload.source, payload.name)
    view = AdminDataView(
        name=payload.name,
        source=payload.source,
        view_type=payload.view_type,
        visible_fields=list(payload.visible_fields),
        filters=dict(payload.filters),
        sort_field=payload.sort_field,
        sort_dir=payload.sort_dir,
        group_field=payload.group_field,
        title_field=payload.title_field,
        page_size=payload.page_size,
        is_default=payload.is_default,
        notes=payload.notes,
    )
    try:
        if payload.is_default:
            # Demote before the INSERT: the partial unique index allows only
            # one default per source and would reject the new row otherwise.
            await _demote_other_defaults(db, payload.source, None)
        db.add(view)
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A data view with this name already exists for the source",
        ) from exc
    await db.refresh(view)
    return view


async def update_view(
    db: AsyncSession, view_id: int, payload: AdminDataViewUpdate
) -> AdminDataView:
    view = await db.get(AdminDataView, view_id)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data view not found")

    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        await _assert_name_free(db, view.source, updates["name"], ignore_id=view.id)
    _validate_merged(view, updates)

    for field, value in updates.items():
        if field == "is_default" and value is True:
            # Demote first: setting is_default on the pending row and executing
            # the UPDATE would autoflush the new default into the partial
            # unique index before the competitors are cleared.
            await _demote_other_defaults(db, view.source, view.id)
        setattr(view, field, value)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A data view with this name already exists for the source",
        ) from exc
    await db.refresh(view)
    return view


async def delete_view(db: AsyncSession, view_id: int) -> None:
    view = await db.get(AdminDataView, view_id)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data view not found")
    await db.delete(view)
    await db.commit()


def _validate_merged(view: AdminDataView, updates: dict[str, Any]) -> None:
    """Validate the post-update row, not just the patch.

    A partial update that switches a view to kanban must already carry (or
    keep) a group field, and a field rename must stay inside the source
    vocabulary. Validating only the patch would let both drift.
    """
    merged = {
        "name": updates.get("name", view.name),
        "source": view.source,
        "view_type": updates.get("view_type", view.view_type),
        "visible_fields": updates.get("visible_fields", view.visible_fields),
        "filters": updates.get("filters", view.filters),
        "sort_field": updates.get("sort_field", view.sort_field),
        "sort_dir": updates.get("sort_dir", view.sort_dir),
        "group_field": updates.get("group_field", view.group_field),
        "title_field": updates.get("title_field", view.title_field),
        "page_size": updates.get("page_size", view.page_size),
        "is_default": updates.get("is_default", view.is_default),
        "notes": updates.get("notes", view.notes),
    }
    try:
        AdminDataViewBase.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid data view: {exc}",
        ) from exc


async def _assert_name_free(
    db: AsyncSession, source: str, name: str, *, ignore_id: int | None = None
) -> None:
    statement = select(AdminDataView.id).where(
        AdminDataView.source == source, AdminDataView.name == name
    )
    if ignore_id is not None:
        statement = statement.where(AdminDataView.id != ignore_id)
    existing = (await db.execute(statement.limit(1))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A data view named '{name}' already exists for {source}",
        )


async def _demote_other_defaults(
    db: AsyncSession, source: str, winner_id: int | None
) -> None:
    statement = update(AdminDataView).where(
        AdminDataView.source == source,
        AdminDataView.is_default.is_(True),
    )
    if winner_id is not None:
        statement = statement.where(AdminDataView.id != winner_id)
    await db.execute(statement.values(is_default=False))


__all__ = [
    "DATA_VIEW_KINDS",
    "DATA_VIEW_SOURCES",
    "create_view",
    "delete_view",
    "list_views",
    "source_catalog",
    "update_view",
]