"""Shared immutable-import helpers used by the API and ingestion worker."""

from __future__ import annotations

import hashlib
import uuid


def source_row_key(draft_id: uuid.UUID | str, row_number: int) -> str:
    """Return the stable identity for one physical source row in a draft.

    The key intentionally derives only from the immutable draft identifier and
    the parser's physical row number.  Business columns are editable and must
    therefore never participate in the identity used to locate a patch.
    """
    if isinstance(row_number, bool) or not isinstance(row_number, int) or row_number < 1:
        raise ValueError("row_number must be a positive physical row number")
    try:
        canonical_draft_id = str(uuid.UUID(str(draft_id)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("draft_id must be a UUID") from exc
    payload = f"soymutdb/import-draft-row/v1:{canonical_draft_id}:{row_number}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["source_row_key"]
