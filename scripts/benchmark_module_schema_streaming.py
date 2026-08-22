#!/usr/bin/env python3
"""Measure bounded streaming module-schema validation without fixture files.

Examples:
    python scripts/benchmark_module_schema_streaming.py --rows 100000
    python scripts/benchmark_module_schema_streaming.py --rows 2000000

The input source creates each row only when the parser asks for it.  This
keeps the reported peak RSS focused on streaming parsing and unique-key
tracking rather than a pre-materialised benchmark payload.  It is deliberately
outside pytest so the 2M-row acceptance run remains opt-in.
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
JOBS_SOURCE = PROJECT_ROOT / "packages" / "jobs-py" / "src"
if str(JOBS_SOURCE) not in sys.path:
    sys.path.insert(0, str(JOBS_SOURCE))

from soymutdb_jobs.module_schema import iter_module_rows_from_stream  # noqa: E402


class GeneratedGenesSource:
    """Yield a valid genes TSV lazily and reject unbounded ``read()`` calls."""

    def __init__(self, rows: int) -> None:
        self._rows = rows
        self._next_row = 0
        self._pending = b"gene_id\tchromosome\tstart\tend\n"
        self.bytes_emitted = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            raise AssertionError("stream consumer requested an unbounded read")
        output = bytearray()
        while len(output) < size:
            if self._pending:
                remaining = size - len(output)
                output.extend(self._pending[:remaining])
                self._pending = self._pending[remaining:]
                continue
            if self._next_row >= self._rows:
                break
            self._next_row += 1
            self._pending = f"G{self._next_row}\tChr01\t1\t1\n".encode("ascii")
        self.bytes_emitted += len(output)
        return bytes(output)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100_000, help="valid rows to validate")
    parser.add_argument(
        "--max-seconds",
        type=float,
        help="optional wall-clock acceptance threshold; omitted by default",
    )
    parser.add_argument(
        "--max-peak-rss-mib",
        type=float,
        help="optional Linux peak-RSS acceptance threshold; omitted by default",
    )
    args = parser.parse_args(argv)
    if args.rows < 1:
        parser.error("--rows must be at least one")
    if args.max_seconds is not None and args.max_seconds <= 0:
        parser.error("--max-seconds must be positive")
    if args.max_peak_rss_mib is not None and args.max_peak_rss_mib <= 0:
        parser.error("--max-peak-rss-mib must be positive")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    source = GeneratedGenesSource(args.rows)
    started = time.perf_counter()
    accepted = 0
    errors = 0
    for row, error in iter_module_rows_from_stream("genes", "genes.tsv", source):
        accepted += row is not None
        errors += error is not None
    elapsed_seconds = time.perf_counter() - started
    peak_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = {
        "rows_requested": args.rows,
        "rows_accepted": accepted,
        "errors": errors,
        "input_bytes": source.bytes_emitted,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "peak_rss_kib": peak_rss_kib,
    }
    print(json.dumps(result, sort_keys=True))

    if accepted != args.rows or errors:
        return 1
    if args.max_seconds is not None and elapsed_seconds > args.max_seconds:
        return 1
    peak_rss_mib = peak_rss_kib / 1024
    if args.max_peak_rss_mib is not None and peak_rss_mib > args.max_peak_rss_mib:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
