"""Cursor contract of the public homolog endpoints.

The cursor used to be the raw ``GeneHomolog.id`` rendered as a plain integer,
which made it enumerable and allowed it to be replayed against a different
release or filter set. It is now an opaque, signed token bound to the release
and to the query that produced it.

This file keeps the original positive/negative decode coverage but against the
new contract.
"""

from __future__ import annotations

import pytest

from app.api.v1.homolog import _decode_cursor
from app.core.exceptions import ValidationError
from app.services.release_context import ReleaseContext, encode_bound_cursor


def _context(release_id: int = 7) -> ReleaseContext:
    return ReleaseContext(release_id=release_id, assembly_id=3, assembly="Wm82.a4.v1")


def _filters(**overrides) -> dict[str, str]:
    values = {"gene_id": "Glyma.01G000100", "limit": "100"}
    values.update(overrides)
    return values


def _cursor(row_id: str, *, release_id: int = 7, filters: dict[str, str] | None = None) -> str:
    return encode_bound_cursor(
        kind="homolog",
        sort_key={"d": row_id},
        release_context=_context(release_id),
        filters=filters if filters is not None else _filters(),
    )


@pytest.mark.parametrize("row_id, expected", [("1", 1), ("42", 42), ("918273", 918273)])
def test_homolog_cursor_decodes_positive_row_ids(row_id: str, expected: int) -> None:
    assert _decode_cursor(
        _cursor(row_id), release_context=_context(), filters=_filters()
    ) == expected


@pytest.mark.parametrize("row_id", ["0", "abc", "1.5", ""])
def test_homolog_cursor_rejects_non_numeric_sort_keys(row_id: str) -> None:
    with pytest.raises(ValidationError):
        _decode_cursor(
            _cursor(row_id), release_context=_context(), filters=_filters()
        )


def test_homolog_cursor_rejects_a_tampered_token():
    cursor = _cursor("42")
    tampered = cursor[:-4] + ("aaaa" if not cursor.endswith("aaaa") else "bbbb")

    with pytest.raises(ValidationError):
        _decode_cursor(tampered, release_context=_context(), filters=_filters())


def test_homolog_cursor_rejects_replay_under_another_release():
    with pytest.raises(ValidationError):
        _decode_cursor(
            _cursor("42", release_id=7),
            release_context=_context(release_id=8),
            filters=_filters(),
        )


def test_homolog_cursor_rejects_replay_under_another_filter_set():
    with pytest.raises(ValidationError):
        _decode_cursor(
            _cursor("42"),
            release_context=_context(),
            filters=_filters(gene_id="Glyma.02G000200"),
        )


def test_homolog_cursor_does_not_expose_the_row_id():
    cursor = _cursor("918273")
    assert "918273" not in cursor
