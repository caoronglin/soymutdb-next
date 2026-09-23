"""Database engine port for the import finalize protocol (ADR-0005 / P2-3).

The import writer/verifier/finalizer must behave identically wherever it runs,
but its ClickHouse semantics (MergeTree append, SummingMergeTree double-count on
duplicate insert, MV firing, partition drop leaving summaries stale) are exactly
what needs real verification. This module defines a tiny engine port so the
protocol can be accepted against a *real* ClickHouse engine:

- ``HttpClickHouseEngine`` — production; wraps the clickhouse-connect client.
- ``ChdbEngine`` — acceptance; wraps chdb's embedded ClickHouse (a real
  single-node engine, not a mock) so retry/finalize/visibility behaviour is
  proven without a server or Docker in CI.

The port intentionally exposes only what the protocol needs; it is NOT a general
ClickHouse client.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ClickHouseEngine(Protocol):
    """The minimal imperative surface the import finalize protocol relies on."""

    def execute(self, sql: str) -> Any:
        """Run a DDL/DML statement (CREATE / ALTER / INSERT / DELETE)."""
        ...

    def insert_rows(
        self, table: str, rows: list[tuple], column_names: list[str]
    ) -> None:
        """Append ``rows`` to ``table`` (column order = ``column_names``)."""
        ...

    def scalar(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        """Return the first cell of the first row of ``sql`` (or None)."""
        ...

    def query_rows(self, sql: str, params: dict[str, Any] | None = None) -> list[tuple]:
        """Return every row of ``sql`` as tuples, in result order."""
        ...


# ---------------------------------------------------------------------------
# Production adapter (HTTP)
# ---------------------------------------------------------------------------


class HttpClickHouseEngine:
    """ClickHouse engine backed by a clickhouse-connect client."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def execute(self, sql: str) -> Any:
        return self._client.command(sql)

    def insert_rows(
        self, table: str, rows: list[tuple], column_names: list[str]
    ) -> None:
        if not rows:
            return
        self._client.insert(table, data=rows, column_names=column_names)

    def scalar(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        result = self._client.query(sql, parameters=params or {})
        rows = result.result_rows
        if not rows or not rows[0]:
            return None
        return rows[0][0]

    def query_rows(self, sql: str, params: dict[str, Any] | None = None) -> list[tuple]:
        result = self._client.query(sql, parameters=params or {})
        return [tuple(row) for row in result.result_rows]


# ---------------------------------------------------------------------------
# Acceptance adapter (embedded real ClickHouse)
# ---------------------------------------------------------------------------


def sql_literal(value: Any) -> str:
    """Render a Python scalar as a ClickHouse SQL literal (test-engine only)."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


class ChdbEngine:
    """ClickHouse engine backed by chdb's embedded single-node ClickHouse.

    Used by acceptance tests to run the finalize protocol against a real engine
    (real MergeTree, SummingMergeTree and materialized views). Not for
    production; the production path uses ``HttpClickHouseEngine``.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    @classmethod
    def open(cls, path: str) -> ChdbEngine:
        from chdb.session import Session

        return cls(Session(path=path))

    def execute(self, sql: str) -> Any:
        self._session.query(sql, "CSV")
        return None

    def insert_rows(
        self, table: str, rows: list[tuple], column_names: list[str]
    ) -> None:
        if not rows:
            return
        columns = ", ".join(column_names)
        # Chunked to keep any single statement bounded on large inputs.
        for start in range(0, len(rows), 1000):
            chunk = rows[start : start + 1000]
            values = ", ".join(
                "(" + ", ".join(sql_literal(cell) for cell in row) + ")"
                for row in chunk
            )
            self._session.query(
                f"INSERT INTO {table} ({columns}) VALUES {values}", "CSV"
            )

    def scalar(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        result = self._session.query(sql, "CSV", params=params or {})
        text = result.bytes().decode("utf-8").strip()
        if not text:
            return None
        first_line = text.splitlines()[0]
        cell = first_line.split(",")[0]
        return _parse_csv_scalar(cell)

    def query_rows(self, sql: str, params: dict[str, Any] | None = None) -> list[tuple]:
        result = self._session.query(sql, "CSV", params=params or {})
        text = result.bytes().decode("utf-8").strip()
        if not text:
            return []
        return [_parse_csv_row(line) for line in text.splitlines()]


def _parse_csv_scalar(cell: str) -> Any:
    if cell == "" or cell == "\\N":
        return None
    if cell.startswith('"') and cell.endswith('"'):
        return cell[1:-1].replace('""', '"')
    try:
        return int(cell)
    except ValueError:
        pass
    try:
        return float(cell)
    except ValueError:
        return cell


def _parse_csv_row(line: str) -> tuple:
    # Adequate for the acceptance queries (simple LowCardinality tokens without
    # embedded commas). The embedded engine is test-only; production reads use
    # clickhouse-connect's typed result parsing.
    return tuple(_parse_csv_scalar(cell) for cell in line.split(","))
