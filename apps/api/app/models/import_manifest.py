"""Import manifest: application-level control plane for import idempotency.

ADR-0005. The manifest is the authoritative record of one *logical* import:
its semantic fingerprint, lifecycle state, and expected/written row counts.
ClickHouse ``MergeTree`` has no native dedup and the SummingMergeTree summary
tables double-count on duplicate inserts, so this manifest is the exactly-once
guard and the source of publish-visibility for the portal.
"""

from __future__ import annotations

from datetime import datetime

from soymutdb_import_protocol import (
    RESUMABLE_STATES,
    STATUS_ENUM_NAME,
    ImportManifestStatus,
)
from sqlalchemy import BigInteger, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, enum_values

__all__ = ["ImportManifest", "ImportManifestStatus", "RESUMABLE_STATES"]


class ImportManifest(Base, TimestampMixin):
    """One logical import, keyed by a unique semantic fingerprint."""

    __tablename__ = "import_manifests"

    import_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Unique dedup key: the same semantic input maps to exactly one manifest.
    fingerprint: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    release_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    assembly_id: Mapped[int] = mapped_column(Integer, nullable=False)
    importer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(
            ImportManifestStatus,
            name=STATUS_ENUM_NAME,
            values_callable=enum_values,
        ),
        nullable=False,
        default=ImportManifestStatus.CREATED,
        server_default=ImportManifestStatus.CREATED.value,
    )
    expected_rows: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    written_rows: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
