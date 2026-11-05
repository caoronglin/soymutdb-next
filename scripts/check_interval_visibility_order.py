#!/usr/bin/env python3
"""Pin the interval-overlap visibility-before-engine ordering in source bytes.

``overlap()`` resolves the assembly and chromosome from PostgreSQL against the
published ReleaseContext, and only then requires the compiled Rust kernel. If
``bridge.require()`` moves back to the top, an unpublished assembly or unknown
chromosome returns 503 (engine unavailable) instead of 404 (release boundary).
Both are "fail closed", but from a client's point of view they are different
facts: 404 means "this assembly is not published", 503 means "try later". The
unit test that asserts 404 cannot reach its own assertion when the wheel is
absent, so it silently degrades into a 503 assertion -- the same co-revert
blind spot the variants row-key guard was written for.

This guard reads the committed service and test sources rather than importing
them (the API package needs Python 3.15). It is a source contract, not a
runtime proof; the pytest suite still exercises the behaviour.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERVICE = ROOT / "apps/api/app/services/interval_overlap_service.py"
DEFAULT_TEST = ROOT / "apps/api/tests/test_interval_overlap.py"

REQUIRED_TEST = "test_unpublished_assembly_404_wins_over_missing_engine"


def inspect(service: str, test: str) -> list[str]:
    failures: list[str] = []
    try:
        tree = ast.parse(service)
    except SyntaxError as exc:
        return [f"interval_overlap_service.py is not parseable: {exc}"]

    fn = next(
        (n for n in tree.body
         if isinstance(n, ast.AsyncFunctionDef) and n.name == "overlap"),
        None,
    )
    if fn is None:
        return ["overlap() is missing from interval_overlap_service.py"]

    # Line numbers of the three load-bearing calls inside overlap().
    def calls(name: str) -> list[int]:
        found = []
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if (isinstance(f, ast.Attribute) and f.attr == name) or (
                isinstance(f, ast.Name) and f.id == name
            ):
                found.append(node.lineno)
        return sorted(found)

    require = calls("require")
    not_found = calls("NotFoundError")
    if not require:
        failures.append("overlap() never calls bridge.require()")
    if len(not_found) < 2:
        failures.append(
            f"overlap() has {len(not_found)} NotFoundError raises, expected >= 2 "
            "(assembly + chromosome visibility)"
        )
    if require and not_found:
        first_404 = min(not_found)
        if require[0] < first_404:
            failures.append(
                "bridge.require() runs before the first visibility decision: "
                "a missing wheel masks the 404 as a 503"
            )
        last_404 = max(not_found)
        if require[0] < last_404:
            failures.append(
                "bridge.require() must come after BOTH assembly and chromosome "
                "lookups, not just the first"
            )

    if REQUIRED_TEST not in test:
        failures.append(
            f"regression test {REQUIRED_TEST} is missing from "
            "test_interval_overlap.py"
        )
    if "db.calls == 1" not in test:
        failures.append(
            "the regression test no longer asserts the DB lookup precedes the "
            "engine check"
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-path", type=Path, default=DEFAULT_SERVICE)
    parser.add_argument("--test-path", type=Path, default=DEFAULT_TEST)
    args = parser.parse_args(argv)
    if not args.service_path.is_file() or not args.test_path.is_file():
        print("interval visibility order failed: service or test file is missing",
              file=sys.stderr)
        return 1
    failures = inspect(
        args.service_path.read_text(encoding="utf-8"),
        args.test_path.read_text(encoding="utf-8"),
    )
    if failures:
        print("interval visibility order failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("interval visibility order passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
