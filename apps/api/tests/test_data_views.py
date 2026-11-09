"""Saved admin data-view contracts.

The views are configuration over the release-scoped public read APIs, so the
load-bearing properties are vocabulary enforcement and the per-source
invariants: unique names, one default view, and a group field whenever the
render mode is a kanban board.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminDataView
from app.schemas.data_views import (
    AdminDataViewCreate,
    AdminDataViewUpdate,
    DataViewSourceInfo,
)
from app.services import data_views_service as service

pytestmark = pytest.mark.integration


def _payload(**overrides) -> dict:
    payload = {
        "name": "Gene locus",
        "source": "genes",
        "view_type": "grid",
        "visible_fields": ["gene_id", "symbol", "chromosome"],
        "filters": {"chromosome": "Gm01"},
        "page_size": 25,
    }
    payload.update(overrides)
    return payload


def test_source_catalog_has_only_release_scoped_sources() -> None:
    catalog = service.source_catalog()

    assert [info.source for info in catalog] == ["genes", "variants", "mutant_lines"]
    assert all(isinstance(info, DataViewSourceInfo) for info in catalog)
    genes = catalog[0]
    assert "gene_id" in genes.fields
    assert "q" in genes.filter_fields
    # A filter must never be a field the public list endpoint cannot take.
    for info in catalog:
        assert set(info.filter_fields).isdisjoint({"id", "internal_id"})


def test_unknown_field_is_rejected_at_the_schema_boundary() -> None:
    with pytest.raises(ValidationError, match="not available"):
        AdminDataViewCreate(**_payload(visible_fields=["gene_id", "internal_id"]))


def test_unknown_filter_is_rejected_at_the_schema_boundary() -> None:
    with pytest.raises(ValidationError, match="filters not available"):
        AdminDataViewCreate(**_payload(filters={"release_id": "1"}))


def test_kanban_without_group_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="kanban views require group_field"):
        AdminDataViewCreate(**_payload(view_type="kanban"))


def test_blank_filter_values_are_dropped() -> None:
    payload = AdminDataViewCreate(**_payload(filters={"chromosome": "  ", "q": " Glyma "}))

    assert payload.filters == {"q": "Glyma"}


@pytest.mark.asyncio
async def test_create_list_and_promote_default(db_session: AsyncSession) -> None:
    first = await service.create_view(
        db_session, AdminDataViewCreate(**_payload(name="All genes", is_default=True))
    )
    second = await service.create_view(
        db_session, AdminDataViewCreate(**_payload(name="By chromosome", is_default=True))
    )

    assert first.id != second.id
    rows = await service.list_views(db_session, source="genes")
    defaults = [row.name for row in rows if row.is_default]
    assert defaults == ["By chromosome"]
    # The default sorts first within its source.
    assert rows[0].name == "By chromosome"

    await db_session.delete(second)
    await db_session.delete(first)
    await db_session.commit()


@pytest.mark.asyncio
async def test_duplicate_name_is_a_conflict(db_session: AsyncSession) -> None:
    view = await service.create_view(db_session, AdminDataViewCreate(**_payload()))

    with pytest.raises(HTTPException) as excinfo:
        await service.create_view(db_session, AdminDataViewCreate(**_payload()))

    assert excinfo.value.status_code == 409
    await db_session.delete(view)
    await db_session.commit()


@pytest.mark.asyncio
async def test_same_name_is_allowed_across_sources(db_session: AsyncSession) -> None:
    genes = await service.create_view(db_session, AdminDataViewCreate(**_payload()))
    variants = await service.create_view(
        db_session,
        AdminDataViewCreate(
            **_payload(
                name="Gene locus",
                source="variants",
                visible_fields=["variant_id", "chromosome", "position"],
                filters={"chromosome": "Gm01"},
            )
        ),
    )

    assert genes.name == variants.name
    await db_session.delete(genes)
    await db_session.delete(variants)
    await db_session.commit()


@pytest.mark.asyncio
async def test_partial_update_validates_the_merged_row(db_session: AsyncSession) -> None:
    view = await service.create_view(db_session, AdminDataViewCreate(**_payload()))

    with pytest.raises(HTTPException) as excinfo:
        await service.update_view(
            db_session, view.id, AdminDataViewUpdate(view_type="kanban")
        )
    assert excinfo.value.status_code == 422

    updated = await service.update_view(
        db_session,
        view.id,
        AdminDataViewUpdate(view_type="kanban", group_field="chromosome"),
    )
    assert updated.view_type == "kanban"
    assert updated.group_field == "chromosome"

    await db_session.delete(updated)
    await db_session.commit()


@pytest.mark.asyncio
async def test_update_can_clear_optional_sort(db_session: AsyncSession) -> None:
    view = await service.create_view(
        db_session,
        AdminDataViewCreate(**_payload(sort_field="gene_id", sort_dir="asc")),
    )

    updated = await service.update_view(
        db_session, view.id, AdminDataViewUpdate(sort_field=None, sort_dir=None)
    )
    assert updated.sort_field is None
    assert updated.sort_dir is None

    await db_session.delete(updated)
    await db_session.commit()


@pytest.mark.asyncio
async def test_delete_missing_view_is_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(HTTPException) as excinfo:
        await service.delete_view(db_session, 999999)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_stored_row_is_a_configuration_only_artifact(
    db_session: AsyncSession,
) -> None:
    view = await service.create_view(db_session, AdminDataViewCreate(**_payload()))

    stored = (
        await db_session.execute(select(AdminDataView).where(AdminDataView.id == view.id))
    ).scalar_one()
    assert stored.visible_fields == ["gene_id", "symbol", "chromosome"]
    assert stored.filters == {"chromosome": "Gm01"}
    assert not hasattr(stored, "internal_id")

    await db_session.delete(stored)
    await db_session.commit()