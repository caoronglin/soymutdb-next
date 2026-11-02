"""Read-only legacy fact source over the ClickHouse HTTP interface.

The legacy driver this migration was written against (``clickhouse-connect``)
declares ``requires-python < 3.15``, so no version of it may be installed on
this worker's runtime. The historical backfill therefore reads the frozen
legacy store through the documented HTTP interface using :mod:`urllib` alone,
which keeps the module importable and testable on the production interpreter
without the driver ever entering the image.

Every statement this module issues is a single-parameter ``SELECT`` sent with
``readonly=1``; it never issues a mutating statement, never writes, and never
opens a second connection. Credentials travel in headers only, TLS is verified
with the platform trust store, and redirects are refused rather than followed so
an ``Authorization``-bearing request is never replayed to another origin.
"""

from __future__ import annotations

import json
import math
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from .tasks.variant_finalize import BASE_COLUMNS

UINT64_MAX = 18446744073709551615
UINT32_MAX = 4294967295

# A base fact row is a few hundred bytes. The cap is a memory guard against a
# broken or hostile peer that never sends a newline, not a size expectation.
MAX_ROW_BYTES = 1 << 20
READ_CHUNK_BYTES = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 60.0

_UINT64_COLUMNS = frozenset({"variant_id", "position"})
_UINT32_COLUMNS = frozenset(
    {"length", "gene_surrogate_id", "mutant_line_surrogate_id", "consequence_id", "read_depth"}
)
_FLOAT_COLUMNS = frozenset({"quality_score", "allele_frequency"})
_EXPECTED_FIELDS = frozenset(BASE_COLUMNS)


class LegacySourceError(RuntimeError):
    """A legacy read failed. Messages never carry credentials or the URL."""


def build_query() -> str:
    """The one read-only statement this module is allowed to send."""
    return (
        "SELECT "
        + ", ".join(BASE_COLUMNS)
        + " FROM variant_facts WHERE release_key = {release:String}"
        + " ORDER BY variant_id FORMAT JSONEachRow"
    )


@dataclass(frozen=True)
class LegacySourceConfig:
    """Operator-supplied connection settings. Nothing here has a default."""

    url: str
    database: str
    user: str
    password: str
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        parts = urllib.parse.urlsplit(self.url)
        loopback_http = parts.scheme == "http" and parts.hostname in {"127.0.0.1", "::1"}
        if not parts.netloc or (parts.scheme != "https" and not loopback_http):
            raise LegacySourceError(
                "Legacy fact source requires HTTPS or a literal loopback HTTP URL"
            )
        if "@" in parts.netloc:
            raise LegacySourceError("Legacy fact source URL must not carry credentials")
        if parts.query or parts.fragment:
            raise LegacySourceError("Legacy fact source URL must not carry a query string")
        if not self.database or not self.user:
            raise LegacySourceError("Legacy fact source requires an explicit database and user")
        if isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float)) \
                or not math.isfinite(self.timeout) or self.timeout <= 0:
            raise LegacySourceError("Legacy fact source timeout must be a positive number")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LegacySourceConfig:
        """Read explicit ``BACKFILL_*`` configuration; absent settings fail loudly.

        There is no default source, database, user or password, so an omitted
        operator setting can never quietly point this migration at a database
        the operator did not name.
        """
        source = os.environ if env is None else env
        required = (
            "BACKFILL_CLICKHOUSE_URL",
            "BACKFILL_CLICKHOUSE_DATABASE",
            "BACKFILL_CLICKHOUSE_USER",
            "BACKFILL_CLICKHOUSE_PASSWORD",
        )
        missing = sorted(name for name in required if name not in source)
        if missing:
            raise LegacySourceError(
                "Missing required legacy source configuration: " + ", ".join(missing)
            )
        raw_timeout = source.get("BACKFILL_CLICKHOUSE_TIMEOUT")
        try:
            timeout = float(raw_timeout) if raw_timeout is not None else DEFAULT_TIMEOUT_SECONDS
        except ValueError as exc:
            raise LegacySourceError("BACKFILL_CLICKHOUSE_TIMEOUT must be a number") from exc
        return cls(
            url=source["BACKFILL_CLICKHOUSE_URL"],
            database=source["BACKFILL_CLICKHOUSE_DATABASE"],
            user=source["BACKFILL_CLICKHOUSE_USER"],
            password=source["BACKFILL_CLICKHOUSE_PASSWORD"],
            timeout=timeout,
        )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so credentials are never replayed to another origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _NoRedirectHandler(),
    )


def build_request(config: LegacySourceConfig, source_version: str) -> urllib.request.Request:
    """Build the POST request: SQL in the body, parameters in the query string.

    The release key travels as a bound ``param_release`` value, never as text
    spliced into the statement, so a hostile release string cannot alter the
    query. ``output_format_json_quote_64bit_integers=0`` keeps UInt64 columns
    unquoted; :func:`parse_fact_row` still rejects a quoted identity rather than
    handing a string to a PostgreSQL integer column.
    """
    if not source_version:
        raise LegacySourceError("A source release version is required")
    params = urllib.parse.urlencode(
        {
            "database": config.database,
            "readonly": "1",
            "max_block_size": "1000",
            "output_format_json_quote_64bit_integers": "0",
            "param_release": source_version,
        }
    )
    return urllib.request.Request(
        config.url + "?" + params,
        data=build_query().encode("utf-8"),
        method="POST",
        headers={
            "X-ClickHouse-User": config.user,
            "X-ClickHouse-Key": config.password,
            "Content-Type": "text/plain; charset=utf-8",
        },
    )


def _finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def _integer(payload: Mapping[str, Any], column: str, maximum: int) -> int:
    value = payload[column]
    if isinstance(value, bool) or not isinstance(value, int):
        raise LegacySourceError(f"Legacy fact column {column} is not an integer")
    if not 0 <= value <= maximum:
        raise LegacySourceError(f"Legacy fact column {column} is outside its unsigned range")
    return value


def _real(payload: Mapping[str, Any], column: str) -> float:
    value = payload[column]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LegacySourceError(f"Legacy fact column {column} is not a number")
    number = float(value)
    if not _finite(number):
        raise LegacySourceError(f"Legacy fact column {column} is not a finite number")
    return number


def parse_fact_row(payload: Mapping[str, Any]) -> tuple:
    """Validate one decoded row and return it in ``BASE_COLUMNS`` order.

    The field set must match exactly and every value must carry the type the
    authoritative PostgreSQL column expects. Anything else stops the transfer
    rather than reaching an insert that would fail or coerce silently.
    """
    if not isinstance(payload, dict):
        raise LegacySourceError("Legacy fact row is not a JSON object")
    fields = frozenset(payload)
    if fields != _EXPECTED_FIELDS:
        missing = sorted(_EXPECTED_FIELDS - fields)
        unexpected = sorted(fields - _EXPECTED_FIELDS)
        raise LegacySourceError(
            "Legacy fact row does not match the fixed column set"
            f" (missing={missing}, unexpected={unexpected})"
        )
    values: list[Any] = []
    for column in BASE_COLUMNS:
        if column in _UINT64_COLUMNS:
            values.append(_integer(payload, column, UINT64_MAX))
        elif column in _UINT32_COLUMNS:
            values.append(_integer(payload, column, UINT32_MAX))
        elif column in _FLOAT_COLUMNS:
            values.append(_real(payload, column))
        else:
            value = payload[column]
            if not isinstance(value, str):
                raise LegacySourceError(f"Legacy fact column {column} is not a string")
            values.append(value)
    return tuple(values)


def iter_bounded_lines(stream: Any, *, max_row_bytes: int = MAX_ROW_BYTES) -> Iterator[bytes]:
    """Yield newline-delimited rows without ever buffering an unbounded row."""
    if max_row_bytes <= 0:
        raise LegacySourceError("A positive maximum row size is required")
    reader = getattr(stream, "read1", None) or stream.read
    buffer = bytearray()
    while True:
        chunk = reader(READ_CHUNK_BYTES)
        if not chunk:
            break
        buffer.extend(chunk)
        start = 0
        while True:
            index = buffer.find(b"\n", start)
            if index < 0:
                break
            line = bytes(buffer[start:index])
            start = index + 1
            if len(line) > max_row_bytes:
                raise LegacySourceError(f"Legacy fact row exceeds the {max_row_bytes} byte limit")
            yield line
        if start:
            del buffer[:start]
        if len(buffer) > max_row_bytes:
            raise LegacySourceError(f"Legacy fact row exceeds the {max_row_bytes} byte limit")
    if buffer.strip():
        # Bytes after the last newline mean the stream stopped mid-row.
        raise LegacySourceError("Legacy fact source ended with an incomplete row")


def iter_fact_rows(stream: Any, *, max_row_bytes: int = MAX_ROW_BYTES) -> Iterator[tuple]:
    for line in iter_bounded_lines(stream, max_row_bytes=max_row_bytes):
        if not line.strip():
            continue
        try:
            payload = json.loads(line.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise LegacySourceError("Legacy fact row is not valid UTF-8") from exc
        except json.JSONDecodeError as exc:
            raise LegacySourceError("Legacy fact row is not valid JSONEachRow output") from exc
        yield parse_fact_row(payload)


def http_fact_source(
    config: LegacySourceConfig,
    source_version: str,
    *,
    max_row_bytes: int = MAX_ROW_BYTES,
    opener: Callable[..., Any] | None = None,
) -> Callable[[], Iterable[tuple]]:
    """Return a factory that streams one fresh, ordered snapshot per call.

    ``opener`` exists so tests can substitute a transport; production uses a
    verifying HTTPS opener that refuses redirects.
    """
    open_request = opener if opener is not None else _default_opener().open

    def rows() -> Iterator[tuple]:
        request = build_request(config, source_version)
        try:
            response = open_request(request, timeout=config.timeout)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise LegacySourceError(
                    f"Legacy fact source refused to follow an HTTP {exc.code} redirect;"
                    " credentials were not forwarded"
                ) from None
            raise LegacySourceError(
                f"Legacy fact source query failed with HTTP {exc.code}"
            ) from None
        except (urllib.error.URLError, OSError):
            raise LegacySourceError("Legacy fact source transport failed") from None
        try:
            yield from iter_fact_rows(response, max_row_bytes=max_row_bytes)
        finally:
            response.close()

    return rows


__all__ = [
    "LegacySourceConfig",
    "LegacySourceError",
    "MAX_ROW_BYTES",
    "UINT64_MAX",
    "build_query",
    "build_request",
    "http_fact_source",
    "iter_fact_rows",
    "parse_fact_row",
]
