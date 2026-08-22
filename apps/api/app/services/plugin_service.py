"""Persisted enabled overrides for verified deployment plugins."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import log_action
from ..core.exceptions import NotFoundError
from ..core.plugins import BUILTIN_PLUGINS, PluginRegistry, PluginState
from ..models.system_settings import SystemSetting


def _parse_enabled(value: str, default: bool) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


class PluginService:
    @staticmethod
    def override_key(key: str) -> str:
        return f"plugin.{key}.enabled"

    @staticmethod
    async def _rows(db: AsyncSession) -> dict[str, SystemSetting]:
        keys = [PluginService.override_key(key) for key in BUILTIN_PLUGINS]
        rows = (
            (await db.execute(select(SystemSetting).where(SystemSetting.key.in_(keys))))
            .scalars()
            .all()
        )
        return {row.key: row for row in rows if row.key in keys}

    @staticmethod
    async def snapshot(
        db: AsyncSession, registry: PluginRegistry
    ) -> dict[str, PluginState]:
        rows = await PluginService._rows(db)
        overrides: dict[str, bool] = {}
        for key in BUILTIN_PLUGINS:
            row = rows.get(PluginService.override_key(key))
            manifest = registry.verified_manifest(key)
            if row is not None and manifest is not None:
                overrides[key] = _parse_enabled(row.value, manifest.enabled)
        return registry.snapshot(enabled_overrides=overrides)

    @staticmethod
    async def status(
        db: AsyncSession, registry: PluginRegistry, key: str
    ) -> PluginState:
        states = await PluginService.snapshot(db, registry)
        try:
            return states[key]
        except KeyError as exc:
            raise NotFoundError(f"Plugin '{key}' not found") from exc

    @staticmethod
    async def update_enabled(
        db: AsyncSession,
        registry: PluginRegistry,
        *,
        key: str,
        enabled: bool,
        actor_id: object,
        ip_address: str | None = None,
    ) -> PluginState:
        manifest = registry.verified_manifest(key)
        if manifest is None:
            raise NotFoundError(f"Plugin '{key}' not found")
        rows = await PluginService._rows(db)
        override_key = PluginService.override_key(key)
        row = rows.get(override_key)
        old_enabled = _parse_enabled(row.value, manifest.enabled) if row else manifest.enabled
        serialized = "true" if enabled else "false"
        if row is None:
            db.add(
                SystemSetting(
                    key=override_key,
                    value=serialized,
                    updated_by=str(actor_id),
                )
            )
        else:
            row.value = serialized
            row.updated_at = datetime.now(UTC)
            row.updated_by = str(actor_id)
        await log_action(
            db,
            user_id=actor_id,  # type: ignore[arg-type]
            action="plugin_state_update",
            resource_type="plugin",
            resource_id=key,
            old_value={"enabled": old_enabled},
            new_value={"enabled": enabled},
            ip_address=ip_address,
        )
        return registry.status(key, enabled_override=enabled)


__all__ = ["PluginService"]
