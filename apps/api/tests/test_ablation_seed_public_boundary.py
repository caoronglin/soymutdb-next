"""Ablation guards for the public seed surface.

The review found two leaks on ``/seeds``:

* ``GET /seeds/inventory`` listed **every** ``SeedInventory`` row (any release,
  including drafts) and ``GET /seeds/inventory/{id}`` looked a row up by its
  persistence key;
* both the inventory and the request DTOs returned the line's internal
  ``mutant_line_id``, and ``POST /seeds/requests`` accepted that numeric key as
  the locator and echoed it in its not-found message.

``seed_inventory`` has no release column, so scoping means joining
``mutant_lines`` and filtering ``MutantLine.release_id``.

Unit-level guards (no PostgreSQL): the service is driven with a fake session
that records the compiled SQL.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.exceptions import NotFoundError
from app.schemas.seed import SeedRequestCreate
from app.services.release_context import ReleaseContext
from app.services.seed_service import SeedService

_RELEASE_ID = 7
_PUBLIC_ID = "SM7K3ZQ9P2AX"


def _context(release_id: int = _RELEASE_ID) -> ReleaseContext:
    return ReleaseContext(release_id=release_id, assembly_id=3, assembly="Wm82.a4.v1")


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
    def __init__(self, results: list[Any] | None = None) -> None:
        self.statements: list[Any] = []
        self._results = list(results or [])
        self.added: list[Any] = []

    async def execute(self, statement: Any) -> _Rows:
        self.statements.append(statement)
        result = self._results.pop(0) if self._results else []
        if isinstance(result, _Rows):
            return result
        if isinstance(result, list):
            return _Rows(result)
        return _Rows([result])

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        return None

    async def refresh(self, value: Any) -> None:
        return None

    def sql(self, index: int = -1) -> str:
        return str(self.statements[index])


class _Line:
    """Minimal mutant-line stand-in for the joined relationship.

    A ``SimpleNamespace`` cannot be assigned to a SQLAlchemy relationship (the
    backref event needs instance state), so this uses a real mapped object.
    """

    def __init__(self, public_id: str) -> None:
        self.public_id = public_id


def _inventory(*, public_id: str = _PUBLIC_ID):
    """A detached-ish inventory row with the fields the projection reads.

    Built via a real ``SeedInventory`` instance so the relationship descriptor
    is available, then the joined line is attached through the ORM's own
    ``mutant_line`` attribute by constructing the pair together.
    """
    from datetime import UTC, datetime

    from app.models.seed import SeedInventory
    from app.models.variant import MutantLine

    line = MutantLine(public_id=public_id, name="line", is_public=True, is_deleted=False)
    line.release_id = _RELEASE_ID

    row = SeedInventory(
        id=99,
        mutant_line_id=4242,
        seed_lot="LOT-1",
        quantity_grams=10.0,
    )
    row.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    row.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    row.mutant_line = line
    return row


# ---------------------------------------------------------------------------
# 1. Listing is release-scoped and never filtered by an internal key.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inventory_list_joins_the_release():
    """Ablation: without the join a draft release's lots are listed."""
    db = _RecordingDb([_inventory()])

    await SeedService().list_inventory(db, release_context=_context())

    sql = db.sql(0)
    assert "JOIN mutant_lines ON" in sql, sql
    assert "mutant_lines.release_id" in sql, sql


@pytest.mark.asyncio
async def test_inventory_list_filters_by_public_line_id():
    db = _RecordingDb([_inventory()])

    await SeedService().list_inventory(
        db, release_context=_context(), mutant_line_public_id=_PUBLIC_ID.lower()
    )

    sql = db.sql(0)
    assert "upper(mutant_lines.public_id)" in sql.lower(), sql
    assert "mutant_lines.release_id" in sql, sql


# ---------------------------------------------------------------------------
# 2. Detail is addressed by the public lot label inside the release.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inventory_detail_uses_the_lot_label_and_release():
    db = _RecordingDb([_inventory()])

    await SeedService().get_inventory(
        db, "LOT-1", release_context=_context()
    )

    sql = db.sql(0)
    assert "seed_inventory.seed_lot" in sql, sql
    assert "mutant_lines.release_id" in sql, sql
    # The persistence key must not be the locator.
    assert "seed_inventory.id =" not in sql, sql


@pytest.mark.asyncio
async def test_unknown_lot_is_not_found():
    db = _RecordingDb([])

    with pytest.raises(NotFoundError):
        await SeedService().get_inventory(db, "NOPE", release_context=_context())


# ---------------------------------------------------------------------------
# 3. Requests resolve a public id; internal keys are refused.
# ---------------------------------------------------------------------------


def _request(public_id: str = _PUBLIC_ID) -> SeedRequestCreate:
    return SeedRequestCreate(
        mutant_line_public_id=public_id,
        quantity_grams=1.0,
        requester_name="Ada",
        requester_email="ada@example.org",
        requester_institution="Lab",
        purpose="Breeding programme seed increase request.",
        agrees_to_terms=True,
    )


@pytest.mark.asyncio
async def test_request_rejects_a_numeric_internal_locator():
    """A numeric key must not be accepted as a line locator."""
    db = _RecordingDb([])

    with pytest.raises(NotFoundError):
        await SeedService().create_request(
            db, _request("4242"), release_context=_context()
        )

    # Rejected on shape, before any line lookup.
    assert db.statements == []


@pytest.mark.asyncio
async def test_request_resolves_the_public_id_within_the_release():
    db = _RecordingDb([4242])

    await SeedService().create_request(
        db, _request(), release_context=_context()
    )

    sql = db.sql(0)
    assert "mutant_lines.public_id" in sql, sql
    assert "mutant_lines.release_id" in sql, sql
    assert "mutant_lines.is_public" in sql, sql
    created = next(o for o in db.added if type(o).__name__ == "SeedRequest")
    # The row stores the internal key (that is its job) but the key never
    # appears in a response — asserted below.
    assert created.mutant_line_id == 4242


# ---------------------------------------------------------------------------
# 4. Public DTOs carry the public id, never the internal key.
# ---------------------------------------------------------------------------


def test_inventory_response_projection_omits_the_persistence_keys():
    payload = SeedService._inv_to_response(_inventory())  # noqa: SLF001

    assert payload.mutant_line_public_id == _PUBLIC_ID
    assert payload.seed_lot == "LOT-1"
    dumped = payload.model_dump(mode="json")
    for forbidden in ("id", "mutant_line_id"):
        assert forbidden not in dumped, dumped
    assert "4242" not in str(dumped)
    assert "99" not in str(dumped)


def test_seed_request_schema_field_is_the_public_identifier():
    from app.schemas.seed import SeedRequestCreate as Create

    assert "mutant_line_public_id" in Create.model_fields
    assert "mutant_line_id" not in Create.model_fields


def test_seed_request_response_field_is_the_public_identifier():
    from app.schemas.seed import SeedRequestResponse

    assert "mutant_line_public_id" in SeedRequestResponse.model_fields
    assert "mutant_line_id" not in SeedRequestResponse.model_fields
