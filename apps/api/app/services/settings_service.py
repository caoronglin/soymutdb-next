"""Versioned, fail-closed mutations for registered runtime settings."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Literal, cast

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import log_action
from ..core.exceptions import (
    NotFoundError,
    SettingsVersionConflictError,
    ValidationError,
)
from ..core.sanitize import sanitize_rich_html
from ..core.settings_registry import (
    SettingRedaction,
    SettingValidationError,
    get_setting_definition,
    public_setting_value,
    registered_keys_for_section,
    validate_setting_update,
)
from ..core.site_variant import (
    SITE_VARIANTS,
    legacy_section_for_variant,
    variant_section,
)
from ..models.system_settings import SystemSetting, SystemSettingRevision
from ..schemas.settings import (
    SettingsDocumentResponse,
    SettingsHistoryItem,
    SettingsHistoryResponse,
    SettingValue,
)
from .content_snapshot_cache import invalidate_mutable_content_snapshot

_RICH_TEXT_KEYS = frozenset(
    {
        ("about", "content_en"),
        ("about", "content_zh"),
        ("home", "welcome_en"),
        ("home", "welcome_zh"),
    }
    | {
        (variant_section(section, variant), key)
        for section, keys in {
            "about": ("content_en", "content_zh"),
            "home": ("welcome_en", "welcome_zh"),
        }.items()
        for variant in SITE_VARIANTS
        for key in keys
    }
)


#: The revision actions this service can record, mirroring the response schema's
#: `Literal` so the same vocabulary is enforced on both sides.
SettingsHistoryAction = Literal["patch", "put_compat", "rollback"]
_HISTORY_ACTIONS: tuple[SettingsHistoryAction, ...] = ("patch", "put_compat", "rollback")


def _history_action(value: str) -> SettingsHistoryAction:
    """Narrow the stored revision action to the published vocabulary.

    The column is a plain string, but this service is its only writer and it
    only ever records one of the three actions. Narrowing here keeps the response
    schema honest without inventing a database enum for a value that never varies.
    """
    if value not in _HISTORY_ACTIONS:
        raise ValueError(f"unknown settings revision action {value!r}")
    return cast(SettingsHistoryAction, value)


def _canonical_values(
    section: str, values: Mapping[str, SettingValue]
) -> dict[str, str]:
    try:
        canonical = {
            key: validate_setting_update(section, key, value)
            for key, value in values.items()
        }
    except SettingValidationError as exc:
        raise ValidationError(str(exc)) from exc
    for key, value in canonical.items():
        if (section, key) in _RICH_TEXT_KEYS:
            canonical[key] = sanitize_rich_html(value)
    return canonical


def _document(
    section: str, version: int, snapshot: dict[str, str]
) -> SettingsDocumentResponse:
    return SettingsDocumentResponse(
        section=section,
        version=version,
        values={
            key: public_setting_value(section, key, value)
            for key, value in snapshot.items()
        },
    )


def validate_settings_values(
    section: str, values: dict[str, SettingValue]
) -> dict[str, SettingValue]:
    """Return the exact typed values a mutation would safely persist."""
    canonical = _canonical_values(section, values)
    return {
        key: public_setting_value(section, key, value)
        for key, value in canonical.items()
    }


def _public_snapshot(
    section: str, snapshot: dict[str, str]
) -> dict[str, SettingValue]:
    allowed_keys = registered_keys_for_section(section)
    values: dict[str, SettingValue] = {}
    for key, value in snapshot.items():
        if key not in allowed_keys:
            continue
        try:
            canonical = validate_setting_update(section, key, value)
            values[key] = public_setting_value(section, key, canonical)
        except (SettingValidationError, ValueError):
            continue
    return values


def _public_changes(
    section: str, changes: dict[str, str | None]
) -> dict[str, SettingValue | None]:
    allowed_keys = registered_keys_for_section(section)
    values: dict[str, SettingValue | None] = {}
    for key, value in changes.items():
        if key not in allowed_keys:
            continue
        if value is None:
            values[key] = None
            continue
        try:
            canonical = validate_setting_update(section, key, value)
            values[key] = public_setting_value(section, key, canonical)
        except (SettingValidationError, ValueError):
            continue
    return values


async def _latest_revision(
    db: AsyncSession, section: str, *, lock: bool
) -> SystemSettingRevision | None:
    statement = (
        select(SystemSettingRevision)
        .where(SystemSettingRevision.section == section)
        .order_by(SystemSettingRevision.version.desc())
        .limit(1)
    )
    if lock:
        statement = statement.with_for_update()
    return (await db.execute(statement)).scalar_one_or_none()


async def _live_snapshot(
    db: AsyncSession, section: str
) -> tuple[dict[str, SystemSetting], dict[str, str]]:
    keys = registered_keys_for_section(section)
    if not keys:
        raise ValidationError(f"Unknown settings section '{section}'")
    prefix = f"{section}."
    full_keys = [f"{prefix}{key}" for key in keys]
    legacy_section = legacy_section_for_variant(section)
    legacy_prefix = f"{legacy_section}." if legacy_section else None
    if legacy_prefix:
        full_keys.extend(
            f"{legacy_prefix}{key}"
            for key in keys
            if f"{legacy_prefix}{key}" not in full_keys
        )
    rows = (
        (await db.execute(select(SystemSetting).where(SystemSetting.key.in_(full_keys))))
        .scalars()
        .all()
    )
    selected_rows = {row.key: row for row in rows if row.key.startswith(prefix)}
    row_map = {row.key: row for row in selected_rows.values() if row.key in full_keys}
    snapshot: dict[str, str] = {}
    for row in rows:
        if row.key.startswith(prefix):
            short_key = row.key.removeprefix(prefix)
            validation_section = section
        elif legacy_prefix and legacy_section is not None and row.key.startswith(legacy_prefix):
            short_key = row.key.removeprefix(legacy_prefix)
            if short_key in snapshot:
                continue
            validation_section = legacy_section
        else:
            continue
        if short_key not in keys:
            continue
        definition = get_setting_definition(validation_section, short_key)
        if definition.redaction is SettingRedaction.OMIT:
            continue
        try:
            value = validate_setting_update(validation_section, short_key, row.value)
        except SettingValidationError as exc:
            raise ValidationError(f"Stored setting '{row.key}' is invalid") from exc
        snapshot[short_key] = (
            sanitize_rich_html(value)
            if (validation_section, short_key) in _RICH_TEXT_KEYS
            else value
        )
    return row_map, snapshot


async def patch_settings(
    db: AsyncSession,
    *,
    section: str,
    expected_version: int,
    values: dict[str, SettingValue],
    actor_id: uuid.UUID,
    ip_address: str | None,
) -> SettingsDocumentResponse:
    """Apply a partial update with optimistic section-version checking."""
    canonical = _canonical_values(section, values)
    latest = await _latest_revision(db, section, lock=True)
    current_version = latest.version if latest is not None else 0
    if expected_version != current_version:
        raise SettingsVersionConflictError(
            "Settings version conflict",
            details={
                "section": section,
                "expected_version": expected_version,
                "current_version": current_version,
            },
        )

    rows, previous = await _live_snapshot(db, section)
    snapshot = {**previous, **canonical}
    prefix = f"{section}."
    for key, value in canonical.items():
        full_key = f"{prefix}{key}"
        row = rows.get(full_key)
        if row is None:
            db.add(SystemSetting(key=full_key, value=value, updated_by=str(actor_id)))
        else:
            row.value = value
            row.updated_by = str(actor_id)

    version = current_version + 1
    db.add(
        SystemSettingRevision(
            section=section,
            version=version,
            action="patch",
            snapshot=snapshot,
            changes=canonical,
            created_by=actor_id,
        )
    )
    try:
        await log_action(
            db,
            user_id=actor_id,
            action="settings_patch",
            resource_type="system_settings",
            resource_id=section,
            old_value={"version": current_version, "values": previous},
            new_value={"version": version, "values": snapshot},
            ip_address=ip_address,
        )
        await db.commit()
        if section == "about":
            await invalidate_mutable_content_snapshot()
    except IntegrityError as exc:
        await db.rollback()
        winner = await _latest_revision(db, section, lock=False)
        winner_version = winner.version if winner is not None else current_version
        raise SettingsVersionConflictError(
            "Settings version conflict",
            details={
                "section": section,
                "expected_version": expected_version,
                "current_version": winner_version,
            },
        ) from exc
    return _document(section, version, snapshot)


async def get_settings_document(
    db: AsyncSession, *, section: str
) -> SettingsDocumentResponse:
    """Read typed live values and their optimistic section version together."""
    if not registered_keys_for_section(section):
        raise ValidationError(f"Unknown settings section '{section}'")
    latest = await _latest_revision(db, section, lock=True)
    _, snapshot = await _live_snapshot(db, section)
    return _document(section, latest.version if latest is not None else 0, snapshot)


async def settings_history(
    db: AsyncSession, *, section: str, limit: int
) -> SettingsHistoryResponse:
    """Return bounded, non-secret revision history newest first."""
    if not registered_keys_for_section(section):
        raise ValidationError(f"Unknown settings section '{section}'")
    revisions = list(
        (
            await db.execute(
                select(SystemSettingRevision)
                .where(SystemSettingRevision.section == section)
                .order_by(SystemSettingRevision.version.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    items = [
        SettingsHistoryItem(
            version=revision.version,
            action=_history_action(revision.action),
            values=_public_snapshot(section, revision.snapshot),
            changes=_public_changes(section, revision.changes),
            actor_id=revision.created_by,
            created_at=revision.created_at,
            rollback_from_version=revision.rollback_from_version,
            reason=revision.reason,
        )
        for revision in revisions
    ]
    return SettingsHistoryResponse(
        section=section,
        current_version=items[0].version if items else 0,
        items=items,
    )


async def rollback_settings(
    db: AsyncSession,
    *,
    section: str,
    expected_version: int,
    target_version: int,
    reason: str,
    actor_id: uuid.UUID,
    ip_address: str | None,
) -> SettingsDocumentResponse:
    """Restore an immutable snapshot as a new optimistic settings version."""
    if not registered_keys_for_section(section):
        raise ValidationError(f"Unknown settings section '{section}'")
    latest = await _latest_revision(db, section, lock=True)
    current_version = latest.version if latest is not None else 0
    if expected_version != current_version:
        raise SettingsVersionConflictError(
            "Settings version conflict",
            details={
                "section": section,
                "expected_version": expected_version,
                "current_version": current_version,
            },
        )
    target = (
        await db.execute(
            select(SystemSettingRevision).where(
                SystemSettingRevision.section == section,
                SystemSettingRevision.version == target_version,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise NotFoundError(
            f"Settings version {target_version} not found for section '{section}'"
        )

    snapshot = _canonical_values(section, target.snapshot)
    rows, previous = await _live_snapshot(db, section)
    prefix = f"{section}."
    removed_full_keys = [
        full_key
        for full_key in rows
        if full_key.removeprefix(prefix) not in snapshot
    ]
    if removed_full_keys:
        await db.execute(
            delete(SystemSetting).where(SystemSetting.key.in_(removed_full_keys))
        )
    for key, value in snapshot.items():
        full_key = f"{prefix}{key}"
        row = rows.get(full_key)
        if row is None:
            db.add(SystemSetting(key=full_key, value=value, updated_by=str(actor_id)))
        else:
            row.value = value
            row.updated_by = str(actor_id)

    version = current_version + 1
    changes = {
        key: snapshot.get(key)
        for key in previous.keys() | snapshot.keys()
        if previous.get(key) != snapshot.get(key)
    }
    db.add(
        SystemSettingRevision(
            section=section,
            version=version,
            action="rollback",
            snapshot=snapshot,
            changes=changes,
            created_by=actor_id,
            rollback_from_version=target_version,
            reason=reason,
        )
    )
    await log_action(
        db,
        user_id=actor_id,
        action="settings_rollback",
        resource_type="system_settings",
        resource_id=section,
        old_value={"version": current_version, "values": previous},
        new_value={
            "version": version,
            "values": snapshot,
            "rollback_from_version": target_version,
            "reason": reason,
        },
        ip_address=ip_address,
    )
    await db.commit()
    if section == "about":
        await invalidate_mutable_content_snapshot()
    return _document(section, version, snapshot)


async def put_settings_compat(
    db: AsyncSession,
    *,
    section: str,
    values: dict[str, SettingValue],
    actor_id: uuid.UUID,
    ip_address: str | None,
) -> SettingsDocumentResponse:
    """Apply the legacy partial PUT while preserving the revision chain."""
    canonical = _canonical_values(section, values)
    latest = await _latest_revision(db, section, lock=True)
    current_version = latest.version if latest is not None else 0
    rows, previous = await _live_snapshot(db, section)
    snapshot = {**previous, **canonical}
    prefix = f"{section}."
    for key, value in canonical.items():
        full_key = f"{prefix}{key}"
        row = rows.get(full_key)
        if row is None:
            db.add(SystemSetting(key=full_key, value=value, updated_by=str(actor_id)))
        else:
            row.value = value
            row.updated_by = str(actor_id)

    version = current_version + 1
    db.add(
        SystemSettingRevision(
            section=section,
            version=version,
            action="put_compat",
            snapshot=snapshot,
            changes=canonical,
            created_by=actor_id,
        )
    )
    await log_action(
        db,
        user_id=actor_id,
        action=f"settings_update:{section}",
        resource_type="system_settings",
        resource_id=section,
        old_value={"version": current_version, "values": previous},
        new_value={"version": version, "values": snapshot},
        ip_address=ip_address,
    )
    await db.commit()
    if section == "about":
        await invalidate_mutable_content_snapshot()
    return _document(section, version, snapshot)


__all__ = [
    "get_settings_document",
    "patch_settings",
    "put_settings_compat",
    "rollback_settings",
    "settings_history",
    "validate_settings_values",
]
