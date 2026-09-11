"""Release lifecycle status must round-trip through the public schema.

The release status vocabulary is owned by the database enum
(``app.models.content.ReleaseStatus``): draft / validated / ready / published /
rolled_back. A second, divergent vocabulary in the response schema rejects
legitimate rows during serialization and surfaces as an unhandled 500 for
any release that has moved past ``draft``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models.content import ReleaseStatus as ModelReleaseStatus
from app.schemas.content import ReleaseResponse, ReleaseStatus


def _release_kwargs(status: str) -> dict:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    return {
        "id": "7",
        "version": "1.0.0",
        "name": "Release 1.0.0",
        "description": None,
        "variant_count": 0,
        "gene_count": 0,
        "mutant_line_count": 0,
        "status": status,
        "published_at": None,
        "created_at": now,
        "updated_at": now,
    }


def test_schema_status_is_the_model_status() -> None:
    """There must be exactly one release-status vocabulary."""
    assert {member.value for member in ReleaseStatus} == {
        member.value for member in ModelReleaseStatus
    }


@pytest.mark.parametrize(
    "status",
    ["draft", "validated", "ready", "published", "rolled_back"],
)
def test_every_lifecycle_status_serializes(status: str) -> None:
    response = ReleaseResponse.model_validate(_release_kwargs(status))
    assert response.status.value == status


def test_unknown_status_is_rejected() -> None:
    with pytest.raises(Exception):
        ReleaseResponse.model_validate(_release_kwargs("not-a-status"))
