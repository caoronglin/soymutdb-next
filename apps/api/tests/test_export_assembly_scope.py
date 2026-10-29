"""Export assembly scope resolution — pure unit tests, no database.

The assembly scope of an export is decided *before* anything is written: the
resolved namespace is stored in ``variant_exports.assembly_key`` and handed to
the worker as a filter.  These tests pin that decision itself — which value
wins, when the request is refused, and how long a name may be — with no
database, no HTTP client and no worker.

The production helper is imported and called, never copied here, so a change
in the resolution rule fails in this file instead of silently changing the
namespace an export is built from.  The tests request no database fixture at
all (see ``test_the_scope_tests_use_no_database_fixture``), so they run
without a PostgreSQL server.
"""

from __future__ import annotations

import pytest

from app.api.v1.variants import _export_assembly_scope
from app.core.exceptions import ValidationError
from app.schemas.variant import MAX_ASSEMBLY_KEY_LENGTH
from app.services.release_context import ReleaseContext


def _context(assembly: str | None) -> ReleaseContext:
    """A resolved release with (or without) its own assembly scope."""
    return ReleaseContext(release_id=7, assembly_id=3, assembly=assembly)


def _name(length: int) -> str:
    """An assembly name of exactly *length* characters."""
    return "A" * length


# ---------------------------------------------------------------------------
# 1. Which assembly wins.
# ---------------------------------------------------------------------------


def test_a_named_assembly_wins_over_the_release_scope() -> None:
    assert (
        _export_assembly_scope("Wm82.a5.v1", _context("Wm82.a4.v1")) == "Wm82.a5.v1"
    )


def test_the_release_scope_is_used_when_the_request_names_none() -> None:
    assert _export_assembly_scope(None, _context("Wm82.a4.v1")) == "Wm82.a4.v1"


def test_the_release_scope_is_used_when_the_request_names_an_empty_string() -> None:
    assert _export_assembly_scope("", _context("Wm82.a4.v1")) == "Wm82.a4.v1"


def test_surrounding_whitespace_is_removed_from_a_named_assembly() -> None:
    assert (
        _export_assembly_scope("  Wm82.a5.v1  ", _context("Wm82.a4.v1"))
        == "Wm82.a5.v1"
    )


def test_a_blank_assembly_is_treated_as_unnamed() -> None:
    """Whitespace is not a name: it falls back to the release scope."""
    assert _export_assembly_scope("   ", _context("Wm82.a4.v1")) == "Wm82.a4.v1"


def test_a_blank_release_scope_is_treated_as_no_scope() -> None:
    """A release scope of whitespace is no scope at all."""
    with pytest.raises(ValidationError):
        _export_assembly_scope("   ", _context("   "))


def test_an_export_is_refused_when_no_assembly_can_be_resolved() -> None:
    with pytest.raises(ValidationError):
        _export_assembly_scope(None, _context(None))


# ---------------------------------------------------------------------------
# 2. The resolved name must fit the export record.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("length", [1, 63, MAX_ASSEMBLY_KEY_LENGTH])
def test_a_name_that_fits_is_accepted_unchanged(length: int) -> None:
    """A name that fits is returned exactly as it was given."""
    name = _name(length)
    assert _export_assembly_scope(name, _context("Wm82.a4.v1")) == name


@pytest.mark.parametrize("length", [MAX_ASSEMBLY_KEY_LENGTH + 1, 65, 200])
def test_a_name_that_is_too_long_is_refused(length: int) -> None:
    """An over-long name is refused, never truncated."""
    with pytest.raises(ValidationError):
        _export_assembly_scope(_name(length), _context("Wm82.a4.v1"))


@pytest.mark.parametrize("length", [MAX_ASSEMBLY_KEY_LENGTH, MAX_ASSEMBLY_KEY_LENGTH + 1])
def test_the_release_scope_is_held_to_the_same_limit(length: int) -> None:
    """The default scope is checked exactly like an explicitly named one."""
    scope = _name(length)
    if length <= MAX_ASSEMBLY_KEY_LENGTH:
        assert _export_assembly_scope(None, _context(scope)) == scope
    else:
        with pytest.raises(ValidationError):
            _export_assembly_scope(None, _context(scope))


def test_an_over_long_name_is_refused_even_when_the_release_scope_fits() -> None:
    """A named assembly wins — so it is the named value that is judged."""
    with pytest.raises(ValidationError):
        _export_assembly_scope(_name(65), _context("Wm82.a4.v1"))


def test_the_refusal_does_not_echo_the_rejected_name() -> None:
    """The error states the limit, not the value the caller sent."""
    secret = "S" * 65
    with pytest.raises(ValidationError) as excinfo:
        _export_assembly_scope(secret, _context("Wm82.a4.v1"))
    assert secret not in str(excinfo.value)
    assert str(MAX_ASSEMBLY_KEY_LENGTH) in str(excinfo.value)


# ---------------------------------------------------------------------------
# 3. These tests must not reach a database.
# ---------------------------------------------------------------------------


def test_the_scope_tests_use_no_database_fixture(request: pytest.FixtureRequest) -> None:
    """The unit tests must not pull the session's PostgreSQL fixtures."""
    requested = set(request.fixturenames)
    assert not requested & {
        "db_session",
        "db_connection",
        "client",
        "app",
        "test_engine",
        "postgres_container",
    }
