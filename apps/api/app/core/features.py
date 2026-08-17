"""Atomic, auditable feature flags.

Feature flags are server-owned capabilities, not arbitrary settings.  Each
flag has a stable definition, a safe default, visibility metadata, and a
well-defined disable behavior.  Runtime overrides live in ``system_settings``
under ``feature.<key>`` and are audited by the caller's transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.auth import AuditLog
from ..models.system_settings import SystemSetting


@dataclass(frozen=True)
class FeatureDefinition:
    key: str
    default: bool
    public: bool
    description: str
    disable_behavior: str = "reject_new_requests"


FEATURES: Final[dict[str, FeatureDefinition]] = {
    "page_builder": FeatureDefinition(
        "page_builder", True, True, "Render published PageDefinition components."
    ),
    "search.external": FeatureDefinition(
        "search.external", True, True, "Enable federated external search providers."
    ),
    "imports.module_tsv": FeatureDefinition(
        "imports.module_tsv", True, True, "Enable schema-driven module imports."
    ),
    "imports.module_xlsx": FeatureDefinition(
        "imports.module_xlsx", True, True, "Enable XLSX module imports."
    ),
    "imports.local_upload": FeatureDefinition(
        "imports.local_upload", True, True, "Enable browser-direct multipart uploads."
    ),
    "publication.github_pages": FeatureDefinition(
        "publication.github_pages", True, False, "Enable GitHub Pages publication target."
    ),
    "publication.cloudflare_pages": FeatureDefinition(
        "publication.cloudflare_pages", True, False, "Enable Cloudflare Pages publication target."
    ),
}


class UnknownFeatureError(ValueError):
    pass


def get_definition(key: str) -> FeatureDefinition:
    try:
        return FEATURES[key]
    except KeyError as exc:
        raise UnknownFeatureError(f"Unknown feature '{key}'") from exc


def parse_feature_value(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def serialize_feature_value(value: bool) -> str:
    return "true" if value else "false"


class FeatureFlagService:
    """Read/update registered feature flags within the caller's transaction."""

    @staticmethod
    async def snapshot(
        db: AsyncSession, *, public_only: bool = False
    ) -> dict[str, bool]:
        definitions = {
            key: definition
            for key, definition in FEATURES.items()
            if not public_only or definition.public
        }
        keys = [f"feature.{key}" for key in definitions]
        rows = (
            (await db.execute(select(SystemSetting).where(SystemSetting.key.in_(keys))))
            .scalars()
            .all()
        )
        overrides = {row.key.removeprefix("feature."): row.value for row in rows}
        return {
            key: parse_feature_value(overrides.get(key), definition.default)
            for key, definition in definitions.items()
        }

    @staticmethod
    async def is_enabled(db: AsyncSession, key: str) -> bool:
        definition = get_definition(key)
        row = await db.scalar(
            select(SystemSetting).where(SystemSetting.key == f"feature.{key}")
        )
        return parse_feature_value(row.value if row else None, definition.default)

    @staticmethod
    async def update(
        db: AsyncSession,
        *,
        updates: dict[str, bool],
        actor_id: object,
    ) -> dict[str, bool]:
        for key in updates:
            get_definition(key)
        full_keys = [f"feature.{key}" for key in updates]
        rows = (
            (await db.execute(select(SystemSetting).where(SystemSetting.key.in_(full_keys))))
            .scalars()
            .all()
        )
        existing = {row.key: row for row in rows}
        old_values: dict[str, bool] = {}
        for key, enabled in updates.items():
            full_key = f"feature.{key}"
            row = existing.get(full_key)
            old_values[key] = parse_feature_value(
                row.value if row else None, get_definition(key).default
            )
            if row is None:
                db.add(
                    SystemSetting(
                        key=full_key,
                        value=serialize_feature_value(enabled),
                        updated_by=str(actor_id),
                    )
                )
            else:
                row.value = serialize_feature_value(enabled)
                row.updated_by = str(actor_id)
        db.add(
            AuditLog(
                user_id=actor_id,
                action="feature_flags_update",
                resource_type="feature_flags",
                resource_id="feature",
                old_value=old_values,
                new_value=updates,
            )
        )
        await db.flush()
        return await FeatureFlagService.snapshot(db)


__all__ = [
    "FEATURES",
    "FeatureDefinition",
    "FeatureFlagService",
    "UnknownFeatureError",
    "get_definition",
    "parse_feature_value",
]
