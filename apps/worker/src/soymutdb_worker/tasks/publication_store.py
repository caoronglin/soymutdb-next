"""Narrow publication status store (worker side, Phase 3).

Mirrors ``app.services.publication_service``'s state machine but uses plain
SQLAlchemy Core over the ``static_publications`` and
``publication_target_leases`` tables, so the worker never imports API source.

Every status write validates the allowed transition (``requested -> building
-> validating -> deploying -> published | failed | superseded``) and uses a
guarded UPDATE keyed on the current status so concurrent deliveries never
double-apply.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text, update

from soymutdb_worker.tables import static_publications
from soymutdb_worker.utils.db import get_db

_STATUS = {
    "requested",
    "building",
    "validating",
    "deploying",
    "published",
    "failed",
    "rolled_back",
    "superseded",
}

_TRANSITIONS: dict[str, set[str]] = {
    "requested": {"building", "failed"},
    "building": {"validating", "failed"},
    "validating": {"deploying", "failed"},
    "deploying": {"published", "failed", "superseded"},
    "published": {"rolled_back"},
    "failed": set(),
    "rolled_back": set(),
    "superseded": set(),
}


class PublicationStateStore:
    """Guarded status transitions over ``static_publications``."""

    def _current(self, session, publication_id: int) -> str | None:
        row = session.execute(
            text("SELECT status FROM static_publications WHERE id = :pid"),
            {"pid": publication_id},
        ).first()
        return row[0] if row else None

    def transition(
        self,
        publication_id: int,
        to_status: str,
        **fields: Any,
    ) -> bool:
        if to_status not in _STATUS:
            return False
        with get_db() as session:
            current = self._current(session, publication_id)
            if current is None or to_status not in _TRANSITIONS.get(current, set()):
                return False
            values: dict[str, Any] = {"status": to_status}
            field_names = (
                "manifest_digest",
                "artifact_url",
                "remote_id",
                "error_message",
                "superseded_by_publication_id",
            )
            for k in field_names:
                if k in fields and fields[k] is not None:
                    values[k] = fields[k]
            result = session.execute(
                update(static_publications)
                .where(
                    static_publications.c.id == publication_id,
                    static_publications.c.status == current,
                )
                .values(**values)
            )
            return bool(getattr(result, "rowcount", 0))

    def should_promote(self, publication_id: int) -> bool:
        """True if this publication is still the target's latest request."""
        with get_db() as session:
            row = session.execute(
                text(
                    "SELECT s.publication_id, l.latest_publication_id "
                    "FROM static_publications s "
                    "LEFT JOIN publication_target_leases l ON l.target = s.target "
                    "WHERE s.id = :pid"
                ),
                {"pid": publication_id},
            ).first()
            if row is None:
                return False
            pub_id, latest = row
            return latest is None or pub_id == latest

    def mark_superseded(self, publication_id: int, by_publication_id: int) -> bool:
        with get_db() as session:
            current = self._current(session, publication_id)
            if current in (None, "superseded", "failed", "rolled_back"):
                return False
            result = session.execute(
                update(static_publications)
                .where(
                    static_publications.c.id == publication_id,
                    static_publications.c.status == current,
                )
                .values(status="superseded", superseded_by_publication_id=by_publication_id)
            )
            return bool(getattr(result, "rowcount", 0))

    def record_published(
        self, publication_id: int, *, remote_id: str, evidence: dict | None = None
    ) -> bool:
        with get_db() as session:
            current = self._current(session, publication_id)
            if current not in ("deploying", "published"):
                return False
            values: dict[str, Any] = {"status": "published"}
            if remote_id:
                values["remote_id"] = remote_id
            if evidence:
                values["evidence"] = evidence
            result = session.execute(
                update(static_publications)
                .where(
                    static_publications.c.id == publication_id,
                    static_publications.c.status == current,
                )
                .values(**values)
            )
            return bool(getattr(result, "rowcount", 0))


__all__ = ["PublicationStateStore"]
