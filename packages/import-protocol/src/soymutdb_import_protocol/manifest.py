"""Import manifest lifecycle contract (ADR-0005 / P2-1).

The manifest is the application-level control plane for import idempotency and
publish-visibility. ClickHouse ``MergeTree`` has no native dedup and the
SummingMergeTree summary tables double-count on duplicate inserts, so this
state machine — not the storage engine — is the correctness guarantee.

This module is the single source of truth shared by the API (which persists the
manifest) and the Celery worker (which drives the transitions during an
import). It is framework-neutral and database-neutral on purpose.
"""

from __future__ import annotations

import enum

# The database enum type name. Kept here so the API's SQLAlchemy column and any
# future migration agree on one identifier.
STATUS_ENUM_NAME = "import_manifest_status_enum"


class ImportManifestStatus(enum.StrEnum):
    """ADR-0005 lifecycle. Only ``PUBLISHED`` is visible to the portal."""

    CREATED = "created"
    PARSING = "parsing"
    WRITING = "writing"
    VERIFYING = "verifying"
    PUBLISHED = "published"
    FAILED = "failed"


# Explicit lifecycle transitions (ADR-0005). FAILED -> CREATED models a retry
# starting a fresh attempt over the same logical import (same fingerprint).
ALLOWED_MANIFEST_TRANSITIONS: dict[ImportManifestStatus, frozenset[ImportManifestStatus]] = {
    ImportManifestStatus.CREATED: frozenset(
        {ImportManifestStatus.PARSING, ImportManifestStatus.FAILED}
    ),
    ImportManifestStatus.PARSING: frozenset(
        {ImportManifestStatus.WRITING, ImportManifestStatus.FAILED}
    ),
    ImportManifestStatus.WRITING: frozenset(
        {ImportManifestStatus.VERIFYING, ImportManifestStatus.FAILED}
    ),
    ImportManifestStatus.VERIFYING: frozenset(
        {ImportManifestStatus.PUBLISHED, ImportManifestStatus.FAILED}
    ),
    ImportManifestStatus.PUBLISHED: frozenset(),
    ImportManifestStatus.FAILED: frozenset({ImportManifestStatus.CREATED}),
}

# States from which a retry may resume without creating a second logical import.
RESUMABLE_STATES: frozenset[ImportManifestStatus] = frozenset(
    {ImportManifestStatus.CREATED, ImportManifestStatus.FAILED}
)

# The one status the public portal is allowed to observe (publish-visibility
# rule, DB-CORE-5). Everything else is treated as not-yet / not-public.
PORTAL_VISIBLE_STATUSES: frozenset[ImportManifestStatus] = frozenset(
    {ImportManifestStatus.PUBLISHED}
)


def can_transition(current: str, target: ImportManifestStatus) -> bool:
    """True when advancing ``current`` -> ``target`` is a permitted transition."""
    try:
        current_status = ImportManifestStatus(current)
    except ValueError:
        return False
    return target in ALLOWED_MANIFEST_TRANSITIONS[current_status]


def is_portal_visible_status(status: str) -> bool:
    """Publish-visibility rule: the portal sees only PUBLISHED imports."""
    try:
        return ImportManifestStatus(status) in PORTAL_VISIBLE_STATUSES
    except ValueError:
        return False
