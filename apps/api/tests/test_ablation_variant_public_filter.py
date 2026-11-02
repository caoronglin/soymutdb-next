"""Public-boundary guards for the variant mutant-line filter.

Historical fact surrogates are hashes, not PostgreSQL primary keys. Public
identifiers resolve to the fact's line name inside the visible release; neither
private names nor surrogate keys are accepted from clients. The real PostgreSQL
HTTP regression lives in test_variant_mutant_identity.py.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from app.api.v1 import variants as variants_routes
from app.core.exceptions import NotFoundError
from app.services.release_context import ReleaseContext

_RELEASE_ID = 7
#: Taken from the issuer so the guard cannot drift from the id scheme.
from app.core.public_ids import generate_public_id  # noqa: E402

_PUBLIC_ID = generate_public_id()


def _context(release_id: int = _RELEASE_ID) -> ReleaseContext:
    return ReleaseContext(release_id=release_id, assembly_id=3, assembly="Wm82.a4.v1")


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _RecordingDb:
    def __init__(self, value: Any = None) -> None:
        self.statements: list[Any] = []
        self._value = value

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(self._value)


# ---------------------------------------------------------------------------
# 1. Shape validation happens before any query.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    # `U` is excluded from the Crockford alphabet, so this cannot be an id.
    ["42", "0", "1", "SM", "SMU", "not-an-id", "", "SM7QF3Z9P2!"],
)
def test_internal_or_malformed_values_are_rejected_as_client_input(value: str):
    """A numeric/internal locator must be a 422, never an accepted filter."""
    db = _RecordingDb(value=1)

    with pytest.raises(HTTPException) as excinfo:
        import asyncio

        asyncio.run(
            variants_routes._resolve_mutant_line_name(  # noqa: SLF001
                db, value, release_context=_context()
            )
        )

    assert excinfo.value.status_code == 422
    # Rejected before touching the database.
    assert db.statements == []


@pytest.mark.parametrize("case", ["upper", "lower"])
def _cased(value: str, case: str) -> str:
    return value.upper() if case == "upper" else value.lower()


@pytest.mark.parametrize("case", ["upper", "lower"])
def test_public_identifiers_are_accepted_case_insensitively(case: str):
    db = _RecordingDb(value="private-line-name")

    import asyncio

    resolved = asyncio.run(
        variants_routes._resolve_mutant_line_name(  # noqa: SLF001
            db, _cased(_PUBLIC_ID, case), release_context=_context()
        )
    )

    assert resolved == "private-line-name"


def test_the_issuer_produces_ids_this_validator_accepts():
    """Ties the boundary check to the issuance scheme."""
    for _ in range(50):
        assert variants_routes._looks_like_public_id(generate_public_id())  # noqa: SLF001


# ---------------------------------------------------------------------------
# 2. Resolution is release-scoped, public and non-deleted only.
# ---------------------------------------------------------------------------


def test_resolution_filters_by_release_visibility_and_public_id():
    """Ablation: dropping the release predicate resolves a draft release's line."""
    db = _RecordingDb(value="private-line-name")

    import asyncio

    asyncio.run(
        variants_routes._resolve_mutant_line_name(  # noqa: SLF001
            db, _PUBLIC_ID, release_context=_context()
        )
    )

    sql = str(db.statements[0])
    assert "mutant_lines.release_id" in sql, sql
    assert "mutant_lines.is_deleted" in sql, sql
    assert "mutant_lines.is_public" in sql, sql
    assert "upper(mutant_lines.public_id)" in sql.lower(), sql
    bound = set(db.statements[0].compile().params.values())
    assert _RELEASE_ID in bound, bound


def test_an_unknown_public_id_is_a_404_not_a_422():
    db = _RecordingDb(value=None)

    import asyncio

    with pytest.raises(NotFoundError):
        asyncio.run(
            variants_routes._resolve_mutant_line_name(  # noqa: SLF001
                db, _PUBLIC_ID, release_context=_context()
            )
        )


# ---------------------------------------------------------------------------
# 3. The filter field stays internal and is only set by the resolver.
# ---------------------------------------------------------------------------


def test_variant_filter_schema_marks_the_field_internal():
    from app.schemas.variant import VariantFilterParams

    params = VariantFilterParams()
    # Nothing is accepted from a client by default...
    assert params.mutant_line_name is None
    # ...and the field carries the internal-only contract in its source docs.
    import inspect

    source = inspect.getsource(VariantFilterParams)
    assert "never accepted directly from a client" in source


def test_route_exposes_a_public_parameter_and_not_an_internal_one():
    import inspect

    from app.api.v1.variants import list_variants

    signature = inspect.signature(list_variants)
    assert "mutant_line_public_id" in signature.parameters
    # The legacy alias exists for old deep links but is hidden from the schema.
    legacy = signature.parameters.get("mutant_line_id")
    assert legacy is not None
    assert legacy.default.include_in_schema is False
