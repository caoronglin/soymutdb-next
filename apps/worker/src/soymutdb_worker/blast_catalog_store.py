"""Narrow, guarded PostgreSQL store for the BLAST index build lifecycle.

Only PostgreSQL decides which index is published: the atomic filesystem rename
inside :mod:`soymutdb_worker.blast_index` is necessary but not sufficient. Every
status write is a conditional UPDATE keyed on the *expected* state, so two
deliveries of the same build event cannot both publish, and a stale delivery
(cancelled/replaced build) cannot resurrect a row. No worker-local path is ever
written to the catalog; clients receive only public metadata.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from soymutdb_jobs import blast_catalog_state as state
from sqlalchemy import select, update

from soymutdb_worker.tables import blast_databases, utcnow


class CatalogStateError(RuntimeError):
    """A guarded transition lost its race or is illegal; never publish on doubt."""


class BlastCatalogStore:
    """Advance one ``blast_databases`` row through the build state machine."""

    def __init__(self, session: Any) -> None:
        self._session = session

    def get(self, database_id: int) -> dict | None:
        row = self._session.execute(
            select(
                blast_databases.c.id,
                blast_databases.c.name,
                blast_databases.c.engine,
                blast_databases.c.db_type,
                blast_databases.c.build_status,
                blast_databases.c.index_version,
                blast_databases.c.fasta_sha256,
                blast_databases.c.file_path,
            ).where(blast_databases.c.id == database_id)
        ).first()
        return dict(row._mapping) if row is not None else None

    def transition(
        self,
        database_id: int,
        *,
        expected: str,
        target: str,
        build_error: str | None = None,
        build_started_at: datetime | None = None,
        build_finished_at: datetime | None = None,
    ) -> bool:
        """Apply one legal, guarded transition; False means the claim was lost."""
        if not state.transition_allowed(expected, target):
            raise CatalogStateError(
                f"illegal BLAST catalog transition: {expected} -> {target}"
            )
        values: dict[str, Any] = {"build_status": target}
        if target == state.FAILED:
            values["build_error"] = (build_error or "index build failed")[:4000]
            values["build_finished_at"] = build_finished_at or utcnow()
        elif target == state.BUILDING:
            values["build_error"] = None
            values["build_started_at"] = build_started_at or utcnow()
            values["build_finished_at"] = None
            values["build_attempt"] = blast_databases.c.build_attempt + 1
        elif target == state.READY:
            values["build_error"] = None
            values["build_finished_at"] = build_finished_at or utcnow()
        result = self._session.execute(
            update(blast_databases)
            .where(
                blast_databases.c.id == database_id,
                blast_databases.c.build_status == expected,
            )
            .values(**values)
        )
        return bool(getattr(result, "rowcount", 0))

    def publish(
        self,
        database_id: int,
        *,
        index_identity: str,
        fasta_sha256: str,
        sequence_count: int,
        total_length: int,
        annotation_version: str | None = None,
    ) -> bool:
        """Atomically swap the catalog to a verified immutable index.

        The row must already be in ``publishing`` (filesystem rename done). The
        old ``ready`` row stays searchable until this guarded UPDATE wins, so a
        failed build cannot leave the database without a usable index.
        """
        now = utcnow()
        result = self._session.execute(
            update(blast_databases)
            .where(
                blast_databases.c.id == database_id,
                blast_databases.c.build_status == state.PUBLISHING,
            )
            .values(
                build_status=state.READY,
                build_error=None,
                build_finished_at=now,
                index_health_checked_at=now,
                index_version=index_identity,
                fasta_sha256=fasta_sha256,
                sequence_count=sequence_count,
                total_length=total_length,
                **({"annotation_version": annotation_version}
                   if annotation_version else {}),
            )
        )
        return bool(getattr(result, "rowcount", 0))

    def mark_healthy(self, database_id: int, *, checked_at: datetime | None = None) -> bool:
        """Record a successful health check on a published, immutable index."""
        result = self._session.execute(
            update(blast_databases)
            .where(
                blast_databases.c.id == database_id,
                blast_databases.c.build_status == state.READY,
            )
            .values(index_health_checked_at=checked_at or utcnow())
        )
        return bool(getattr(result, "rowcount", 0))

    @staticmethod
    def runnable(row: dict | None) -> bool:
        return row is not None and state.is_runnable(str(row["build_status"]))


__all__ = ["BlastCatalogStore", "CatalogStateError"]
