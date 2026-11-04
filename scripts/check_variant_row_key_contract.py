#!/usr/bin/env python3
"""Guard the variants table row key against a source+test co-regression.

A stale-base branch once carried both an older row key AND the shorter test file
that matches it. Vitest stayed green (2/2) and the OpenAPI contract gate had
nothing to say about frontend source, so no gate reported the revert.

This guard reads the committed sources and pins the invariants that the deleted
tests asserted, independently of whether the test file is present:

- the key uses JSON.stringify so ``null`` and ``""`` stay distinct and ``:``
  cannot splice a neighbour's key;
- the regression suite still covers the absent-vs-empty and duplicate-bucket
  cases, so deleting tests cannot make the gate greener.

It is a source guard, not a runtime proof: vitest still exercises the rendered
table. Run with ``--sources-dir``/``--test-path`` to point at a synthetic tree
in the self-test below.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "apps/web/src/routes/variants/index.tsx"
DEFAULT_TEST = ROOT / "apps/web/src/routes/variants/row-key.test.tsx"

MIN_TESTS = 4
REQUIRED_CASES = (
    "separates an absent assembly from an empty one",
    "keeps rows that agree on identifier and assembly",
)


def strip_comments(text: str) -> str:
    return re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", text)


def inspect(source: str, test: str) -> list[str]:
    failures: list[str] = []
    body = strip_comments(source)
    key = re.search(r"\browKey\s*=\s*\{([\s\S]*?)\}", body)
    if not key:
        failures.append("variants table has no rowKey expression")
    else:
        expression = key.group(1)
        if "JSON.stringify" not in expression:
            failures.append(
                "rowKey must use JSON.stringify([...]) so null/\"\" and ':' cannot collide"
            )
        elif not re.search(r"assembly\s*\?\?\s*null", expression):
            failures.append("rowKey must keep the nullable assembly as null, not \"\"")

    cases = re.findall(r"\bit\(\s*[\"']([^\"']+)[\"']", strip_comments(test))
    if len(cases) < MIN_TESTS:
        failures.append(
            f"row-key regression suite has {len(cases)} cases, expected >= {MIN_TESTS}"
        )
    for name in REQUIRED_CASES:
        if not any(name in case for case in cases):
            failures.append(f"row-key regression suite is missing case: {name}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-path", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--test-path", type=Path, default=DEFAULT_TEST)
    args = parser.parse_args(argv)
    if not args.source_path.is_file() or not args.test_path.is_file():
        print("variant row-key contract failed: source or test file is missing", file=sys.stderr)
        return 1
    failures = inspect(
        args.source_path.read_text(encoding="utf-8"),
        args.test_path.read_text(encoding="utf-8"),
    )
    if failures:
        print("variant row-key contract failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("variant row-key contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
