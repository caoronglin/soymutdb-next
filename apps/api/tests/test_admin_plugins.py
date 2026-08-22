"""Admin plugin inventory and enabled-only state override contracts."""

from __future__ import annotations

import importlib.util
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import (
    PluginDisabledError,
    SoyMutDBError,
    soy_mut_db_exception_handler,
    validation_exception_handler,
)
from app.models.system_settings import SystemSetting
from tests.test_plugins import _manifest, _registry


def test_admin_plugin_router_is_registered_module() -> None:
    assert importlib.util.find_spec("app.api.v1.admin_plugins") is not None


class _Result:
    def __init__(self, rows: list[SystemSetting]) -> None:
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))


class _Db:
    def __init__(self, rows: list[SystemSetting] | None = None) -> None:
        self.rows = rows or []
        self.added: list[object] = []
        self.commits = 0
        self.flushes = 0

    async def execute(self, _statement):
        return _Result(self.rows)

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, SystemSetting) and value not in self.rows:
            self.rows.append(value)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1


def _user(role: str = "administrator"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        is_superuser=role == "administrator",
        role_rel=SimpleNamespace(name=role),
    )


@pytest.fixture
async def admin_plugin_client(monkeypatch):
    from app.api.v1 import admin_plugins
    from app.api.v1.deps import get_current_user
    from app.core.database import get_db

    registry = _registry(_manifest())
    db = _Db()
    audit = AsyncMock()
    monkeypatch.setattr(
        admin_plugins, "get_plugin_registry", lambda: registry, raising=False
    )
    if importlib.util.find_spec("app.services.plugin_service") is not None:
        monkeypatch.setattr("app.services.plugin_service.log_action", audit)

    application = FastAPI()
    application.include_router(admin_plugins.router, prefix="/api/v1")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    application.state.user = _user()

    async def current_user():
        return application.state.user

    async def current_db():
        yield db

    application.dependency_overrides[get_current_user] = current_user
    application.dependency_overrides[get_db] = current_db

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        yield client, application, db, registry, audit


async def test_admin_plugin_list_is_a_keyed_read_only_inventory(
    admin_plugin_client,
) -> None:
    client, _, _, _, _ = admin_plugin_client

    response = await client.get("/api/v1/admin/plugins")

    assert response.status_code == 200
    plugins = response.json()["plugins"]
    assert set(plugins) == {"jbrowse", "blast", "analyses", "mcp", "ols4"}
    assert plugins["jbrowse"]["key"] == "jbrowse"
    assert plugins["jbrowse"]["status"]["installed"] is True
    assert plugins["blast"]["manifest"] is None


async def test_admin_plugin_detail_exposes_non_sensitive_manifest_metadata(
    admin_plugin_client,
) -> None:
    client, _, _, _, _ = admin_plugin_client

    response = await client.get("/api/v1/admin/plugins/jbrowse")

    assert response.status_code == 200
    manifest = response.json()["manifest"]
    assert manifest["license"] == "MPL-2.0"
    assert manifest["api_compatibility"]["minimum"] == "2.0.0"
    assert manifest["resource_limits"]["memory_mb"] == 1024
    assert manifest["uninstall_semantics"] == "disable_only"
    assert "signature" not in manifest
    assert "public_url_allowlist" not in manifest
    assert "enabled" not in manifest
    assert "configured" not in manifest
    assert "healthy" not in manifest


async def test_admin_plugin_detail_for_not_installed_plugin_is_404(
    admin_plugin_client,
) -> None:
    client, _, _, _, _ = admin_plugin_client
    response = await client.get("/api/v1/admin/plugins/blast")
    assert response.status_code == 404


async def test_patch_persists_only_enabled_override_and_records_audit(
    admin_plugin_client,
) -> None:
    client, _, db, _, audit = admin_plugin_client

    response = await client.patch(
        "/api/v1/admin/plugins/jbrowse/state", json={"enabled": False}
    )

    assert response.status_code == 200
    assert response.json()["status"]["enabled"] is False
    assert response.json()["status"]["configured"] is True
    assert response.json()["status"]["healthy"] is True
    assert response.json()["status"]["reason"] == "plugin_disabled"
    setting = next(row for row in db.rows if row.key == "plugin.jbrowse.enabled")
    assert setting.value == "false"
    assert setting.updated_by is not None
    assert db.commits == 1
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["action"] == "plugin_state_update"
    assert audit.await_args.kwargs["resource_id"] == "jbrowse"
    assert audit.await_args.kwargs["old_value"] == {"enabled": True}
    assert audit.await_args.kwargs["new_value"] == {"enabled": False}


@pytest.mark.parametrize("field", ["configured", "healthy", "installed", "version"])
async def test_patch_rejects_every_field_except_enabled(
    admin_plugin_client, field: str
) -> None:
    client, _, db, _, audit = admin_plugin_client
    response = await client.patch(
        "/api/v1/admin/plugins/jbrowse/state",
        json={"enabled": False, field: False},
    )
    assert response.status_code == 422
    assert db.rows == []
    assert db.commits == 0
    audit.assert_not_awaited()


async def test_patch_rejects_unsigned_not_installed_plugin(
    admin_plugin_client,
) -> None:
    client, _, db, _, audit = admin_plugin_client
    response = await client.patch(
        "/api/v1/admin/plugins/blast/state", json={"enabled": True}
    )
    assert response.status_code == 404
    assert db.rows == []
    assert db.commits == 0
    audit.assert_not_awaited()


async def test_admin_plugin_routes_do_not_install_or_upload_code(
    admin_plugin_client,
) -> None:
    client, _, _, _, _ = admin_plugin_client
    assert (await client.post("/api/v1/admin/plugins", json={})).status_code == 405
    assert (
        await client.post("/api/v1/admin/plugins/jbrowse/install", json={})
    ).status_code in {404, 405}


async def test_admin_plugin_inventory_requires_administrator(
    admin_plugin_client,
) -> None:
    client, application, _, _, _ = admin_plugin_client
    application.state.user = _user("viewer")
    assert (await client.get("/api/v1/admin/plugins")).status_code == 403


@pytest.mark.asyncio
async def test_override_flows_to_capabilities_and_disabled_guard() -> None:
    from app.services.plugin_service import PluginService

    registry = _registry(_manifest())
    db = _Db([SystemSetting(key="plugin.jbrowse.enabled", value="false")])

    states = await PluginService.snapshot(db, registry)

    assert states["jbrowse"].enabled is False
    with pytest.raises(PluginDisabledError):
        registry.require_available("jbrowse", enabled_override=False)
