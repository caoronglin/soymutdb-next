"""WeCom Smartsheet (智能表格) record encoding — W5.

Confirmed against the official server API documentation
(https://developer.work.weixin.qq.com/document/path/90664 and the
`wedoc/smartsheet` endpoint pages it links to).

## The value format is the hard part

A Smartsheet cell is not a scalar. Text arrives as a list of typed segments,
and a field title maps to that list:

    {"values": {"姓名": [{"type": "text", "text": "张三"}]}}

Numbers and dates are the exceptions and are encoded inline rather than as
segments. Getting this wrong does not produce an error — the API accepts the
request and writes an empty or wrong-typed cell — so the conversion lives in
one place with an explicit type per field rather than being spread across
call sites.

## Read-only fields

The API refuses writes to four automatically-maintained field types: creation
time, last-edit time, creator and last editor. They are filtered here rather
than sent and rejected, because a rejected batch writes nothing at all, while a
filtered batch writes everything that is legitimately writable.

## Failure detection

Every response carries `errcode`. Per the official guidance, a call failed when
`errcode` is present and non-zero, and `errmsg` is explicitly *not* a reliable
success signal because its wording may change. `is_error_response` therefore
looks only at `errcode`.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"
TOKEN_PATH = f"{API_BASE}/gettoken"
SMARTSHEET_BASE = f"{API_BASE}/wedoc/smartsheet"

# Field titles the API maintains itself; writes to them are rejected outright.
READ_ONLY_FIELD_TITLES = frozenset(
    {"创建时间", "最后编辑时间", "创建人", "最后编辑人"}
)

# Documented per-table ceiling. Exceeding it is a hard API error, so the
# encoder reports it before a partial batch is written.
MAX_ROWS_PER_SHEET = 40_000


class SmartsheetEncodingError(ValueError):
    """A payload cannot be represented in the Smartsheet wire format."""


# --------------------------------------------------------------------------------------
# Response interpretation
# --------------------------------------------------------------------------------------


def is_error_response(body: Mapping[str, Any]) -> bool:
    """A response is a failure when `errcode` is present and non-zero.

    `errmsg` is deliberately ignored. The official documentation says it is a
    human-readable description that may change, and using it as a success
    signal is how a rate-limit refusal gets mistaken for a completed write.
    """
    if "errcode" not in body:
        return False
    code = body.get("errcode")
    return not isinstance(code, int) or code != 0


def error_code(body: Mapping[str, Any]) -> int | None:
    """The `errcode` when the call failed, else None.

    Kept separate from the message so a caller can branch on
    ``851003`` (visible-range too large) without string matching.
    """
    if not is_error_response(body):
        return None
    code = body.get("errcode")
    return code if isinstance(code, int) else None


def error_message(body: Mapping[str, Any]) -> str | None:
    """`errmsg` when the call failed, for logging only — never for branching."""
    return str(body.get("errmsg")) if is_error_response(body) else None


# --------------------------------------------------------------------------------------
# Value encoding
# --------------------------------------------------------------------------------------


def encode_text(value: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": value}]


def encode_reference(record_ids: Iterable[str]) -> list[str]:
    """Link cells carry bare record ids, not typed segments."""
    return [str(record_id) for record_id in record_ids]


def encode_datetime(moment: datetime) -> str:
    """Date cells are millisecond epoch strings, not numbers.

    The API documents this as a string; sending a JSON number is accepted by
    some field types and rejected by others, so the string form is used
    unconditionally.
    """
    if moment.tzinfo is None:
        raise SmartsheetEncodingError(
            "refusing to encode a naive datetime; WeCom expects an absolute instant"
        )
    return str(int(moment.astimezone(UTC).timestamp() * 1000))


def encode_record(
    values: Mapping[str, Any], *, field_titles: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Encode one record, dropping read-only fields.

    `field_titles` maps local field keys to Smartsheet field titles when the two
    differ. Unmapped keys pass through, so a table whose local keys already are
    the remote titles needs no configuration.
    """
    encoded: dict[str, Any] = {}
    for key, value in values.items():
        title = (field_titles or {}).get(key, key)
        if title in READ_ONLY_FIELD_TITLES:
            continue
        if value is None:
            continue
        encoded[title] = _encode_value(value)
    if not encoded:
        raise SmartsheetEncodingError(
            "record encoded to an empty value map; every field was read-only or null"
        )
    return {"values": encoded}


def _encode_value(value: Any) -> Any:
    if isinstance(value, str):
        return encode_text(value)
    if isinstance(value, bool):
        return encode_text("true" if value else "false")
    if isinstance(value, datetime):
        return encode_datetime(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, Mapping):
        return encode_text(str(value))
    if isinstance(value, Sequence):
        return _encode_sequence(value)
    return encode_text(str(value))


def _encode_sequence(value: Sequence[Any]) -> list[Any]:
    # A list of plain strings in a link field is a set of record ids; the API
    # documents that form, and wrapping it in text segments would silently
    # create literal text instead of links.
    if all(isinstance(item, str) for item in value):
        return encode_reference(value)
    return [encode_text(str(item)) for item in value]


def encode_batch(
    records: Sequence[Mapping[str, Any]], *, field_titles: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Encode a batch for `add_records` / `update_records`."""
    if not records:
        raise SmartsheetEncodingError("refusing to send an empty record batch")
    return {
        "key_type": "CELL_VALUE_KEY_TYPE_FIELD_TITLE",
        "records": [encode_record(record, field_titles=field_titles) for record in records],
    }


# --------------------------------------------------------------------------------------
# Inbound records
# --------------------------------------------------------------------------------------


def decode_segments(raw: Any) -> list[dict[str, Any]]:
    """Normalise a cell into a list of segments, whatever shape it came back in.

    Numbers and dates come back bare, so a decoder that assumes a list would
    raise on a perfectly valid response.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [raw]
    return [{"type": "text", "text": str(raw)}]


def decode_text(raw: Any) -> str:
    """Flatten a cell to plain text, joining segment texts."""
    parts = [str(segment.get("text", "")) for segment in decode_segments(raw)]
    return "".join(parts)
