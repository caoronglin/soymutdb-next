"""Public-boundary guards for the legacy content surfaces.

``/content/publications`` used the persistence key as its public locator: the
response exposed ``id`` and ``GET /content/publications/{publication_id}``
accepted an integer. A DOI is the publication's own scholarly identifier and is
already unique in the schema, so it is the correct public locator — and a
numeric probe must not be an existence oracle for internal ids.

Unit-level guards (no PostgreSQL): the route coroutine is driven with a fake
session that records the statement.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.api.v1 import content as content_routes
from app.core.exceptions import NotFoundError

_DOI = "10.1038/s41586-021-03819-2"


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def scalars(self) -> _Rows:
        return self

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _RecordingDb:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.statements: list[Any] = []
        self._rows = list(rows or [])

    async def execute(self, statement: Any) -> _Rows:
        self.statements.append(statement)
        return _Rows(self._rows)

    async def scalar(self, statement: Any):
        self.statements.append(statement)
        return 0

    def sql(self, index: int = -1) -> str:
        return str(self.statements[index])


def _publication(doi: str | None = _DOI):
    from app.models.content import Publication

    pub = Publication(
        id=42,
        title="A soybean pan-genome",
        authors="Ada et al.",
        journal="Nature",
        year=2021,
        doi=doi,
        is_featured=False,
    )
    pub.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    pub.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    return pub


# ---------------------------------------------------------------------------
# 1. The public projection carries the DOI, not the persistence key.
# ---------------------------------------------------------------------------


def test_publication_response_has_no_persistence_key():
    payload = content_routes._pub_to_response(_publication())  # noqa: SLF001

    dumped = payload.model_dump(mode="json")
    assert dumped["doi"] == _DOI
    assert "id" not in dumped, dumped
    assert "42" not in str(dumped)


def test_publication_schema_has_no_id_field():
    from app.schemas.content import PublicationResponse

    assert "id" not in PublicationResponse.model_fields
    assert "doi" in PublicationResponse.model_fields


# ---------------------------------------------------------------------------
# 2. Detail is addressed by DOI; numeric probes are not-found.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_looks_the_publication_up_by_doi():
    db = _RecordingDb([_publication()])

    payload = await content_routes.get_publication(doi=_DOI, db=db)

    sql = db.sql(0)
    assert "publications.doi" in sql, sql
    # The persistence key must not be the locator.
    assert "publications.id =" not in sql, sql
    assert payload.doi == _DOI


@pytest.mark.asyncio
@pytest.mark.parametrize("probe", ["42", "1", "0", "999999"])
async def test_numeric_probe_is_not_found_without_a_query(probe: str):
    """A bare integer is a persistence-key probe, not a DOI."""
    db = _RecordingDb([_publication()])

    with pytest.raises(NotFoundError):
        await content_routes.get_publication(doi=probe, db=db)

    assert db.statements == []


@pytest.mark.asyncio
async def test_unknown_doi_is_not_found():
    db = _RecordingDb([])

    with pytest.raises(NotFoundError):
        await content_routes.get_publication(doi="10.9999/nope", db=db)


@pytest.mark.asyncio
async def test_doi_containing_slashes_round_trips():
    doi = "10.1093/nar/gkab123"
    db = _RecordingDb([_publication(doi)])

    payload = await content_routes.get_publication(doi=doi, db=db)

    assert payload.doi == doi
    bound = set(db.statements[0].compile().params.values())
    assert doi in bound, bound


# ---------------------------------------------------------------------------
# 3. The snapshot feed matches the same contract.
# ---------------------------------------------------------------------------


def test_snapshot_publication_projection_omits_the_persistence_key():
    import inspect

    from app.services.content_snapshot_service import ContentSnapshotService

    source = inspect.getsource(ContentSnapshotService._load_publications)  # noqa: SLF001
    assert "id=str(p.id)" not in source
    assert "PublicationResponse(" in source
