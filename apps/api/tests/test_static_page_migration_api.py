from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.api.v1 import admin_content
from app.schemas.content import StaticPageMigrationDryRunRequest
from app.services.static_page_migration_service import (
    StaticPageMigrationItem,
    StaticPageMigrationReport,
)


@pytest.mark.asyncio
async def test_dry_run_endpoint_is_admin_gated_and_never_requests_apply(monkeypatch):
    report = StaticPageMigrationReport(
        dry_run=True,
        items=[StaticPageMigrationItem(7, "legacy-about", "/pages/legacy-about", "created")],
    )
    migration = AsyncMock(return_value=report)
    require_admin = Mock()
    monkeypatch.setattr(admin_content, "migrate_static_pages", migration)
    monkeypatch.setattr(admin_content, "_require_admin", require_admin)

    user = SimpleNamespace()
    db = SimpleNamespace()
    response = await admin_content.dry_run_page_builder_migration(
        StaticPageMigrationDryRunRequest(slugs=["legacy-about"]),
        db=db,
        current_user=user,
    )

    require_admin.assert_called_once_with(user)
    migration.assert_awaited_once_with(db, dry_run=True, slugs=["legacy-about"])
    assert response.dry_run is True
    assert response.created == 1
    assert response.items[0].outcome == "created"


def test_dry_run_route_precedes_page_id_route():
    paths = [route.path for route in admin_content.router.routes]
    dry_run_path = "/admin/content/pages/migrate-to-page-builder/dry-run"
    page_path = "/admin/content/pages/{page_id}"
    assert paths.index(dry_run_path) < paths.index(page_path)


@pytest.mark.asyncio
async def test_authorization_failure_prevents_migration_service(monkeypatch):
    migration = AsyncMock()
    monkeypatch.setattr(admin_content, "migrate_static_pages", migration)
    monkeypatch.setattr(
        admin_content,
        "_require_admin",
        Mock(side_effect=admin_content.AuthorizationError("Administrator access required")),
    )

    with pytest.raises(admin_content.AuthorizationError):
        await admin_content.dry_run_page_builder_migration(
            StaticPageMigrationDryRunRequest(slugs=["legacy-about"]),
            db=SimpleNamespace(),
            current_user=SimpleNamespace(),
        )
    migration.assert_not_awaited()


@pytest.mark.parametrize(
    "slugs",
    [
        ["legacy-about", "legacy-about"],
        ["Uppercase"],
        ["contains_underscore"],
        ["a" * 257],
    ],
)
def test_dry_run_request_rejects_duplicate_or_invalid_static_page_slugs(slugs):
    with pytest.raises(ValueError):
        StaticPageMigrationDryRunRequest(slugs=slugs)
