"""PostgreSQL-backed contracts for PageTemplate persistence and guardrails."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.v1.admin_page_builder import (
    create_template,
    delete_template,
    list_templates,
    update_template,
)
from app.models.page_builder import PageTemplate
from app.page_builder.schemas import PageTemplateCreate, PageTemplateUpdate


def _admin_user() -> MagicMock:
    user = MagicMock()
    user.is_superuser = True
    user.is_active = True
    user.is_deleted = False
    user.role_rel = MagicMock()
    user.role_rel.name = "administrator"
    return user


def _definition(content: str = "Template content") -> dict[str, object]:
    return {
        "root": {
            "type": "rich_text",
            "props": {"content": f"<p>{content}</p>"},
        }
    }


@pytest.mark.asyncio
async def test_custom_template_crud_persists_in_postgresql(db_session):
    admin = _admin_user()
    created = await create_template(
        PageTemplateCreate(
            key="field-notes",
            label="Field notes",
            category="research",
            definition=_definition(),
        ),
        db_session,
        admin,
    )
    await db_session.commit()

    assert created.key == "field-notes"
    assert created.builtin is False
    assert created.definition["schema_version"] == 2

    listing = await list_templates(db_session, admin)
    assert listing.total == 1
    assert [item.key for item in listing.items] == ["field-notes"]

    updated = await update_template(
        "field-notes",
        PageTemplateUpdate(label="Updated field notes", sort_order=5),
        db_session,
        admin,
    )
    await db_session.commit()
    assert updated.label == "Updated field notes"
    assert updated.sort_order == 5

    await delete_template("field-notes", db_session, admin)
    await db_session.flush()
    assert await db_session.scalar(select(PageTemplate).where(PageTemplate.key == "field-notes")) is None


@pytest.mark.asyncio
async def test_builtin_templates_are_immutable_in_postgresql(db_session):
    builtin = PageTemplate(
        key="builtin-readonly",
        label="Builtin",
        category="general",
        definition=_definition(),
        builtin=True,
    )
    db_session.add(builtin)
    await db_session.flush()

    with pytest.raises(HTTPException) as update_error:
        await update_template(
            "builtin-readonly",
            PageTemplateUpdate(label="Must not change"),
            db_session,
            _admin_user(),
        )
    assert update_error.value.status_code == 403

    with pytest.raises(HTTPException) as delete_error:
        await delete_template("builtin-readonly", db_session, _admin_user())
    assert delete_error.value.status_code == 403

    persisted = await db_session.scalar(
        select(PageTemplate).where(PageTemplate.key == "builtin-readonly")
    )
    assert persisted is not None
    assert persisted.label == "Builtin"
    assert persisted.builtin is True


@pytest.mark.asyncio
async def test_builtin_template_seed_is_idempotent_in_postgresql(test_engine, monkeypatch):
    from app.scripts import seed_page_builder

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(seed_page_builder, "get_session_factory", lambda: factory)

    first = await seed_page_builder.seed()
    second = await seed_page_builder.seed()

    assert first["created"] >= len(seed_page_builder.BUILTIN_TEMPLATES)
    assert second["created"] == 0

    async with factory() as session:
        templates = (await session.scalars(select(PageTemplate).order_by(PageTemplate.key))).all()

    assert [template.key for template in templates] == ["blank", "research"]
    assert all(template.builtin for template in templates)
