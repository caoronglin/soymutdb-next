from fastapi import HTTPException
import pytest

from app.api.v1.homolog import _decode_id_cursor


@pytest.mark.parametrize("cursor, expected", [("1", 1), ("42", 42)])
def test_homolog_keyset_cursor_decodes_positive_ids(cursor: str, expected: int) -> None:
    assert _decode_id_cursor(cursor) == expected


@pytest.mark.parametrize("cursor", ["0", "-1", "abc", "1.5"])
def test_homolog_keyset_cursor_rejects_invalid_values(cursor: str) -> None:
    with pytest.raises(HTTPException) as error:
        _decode_id_cursor(cursor)
    assert error.value.status_code == 422
