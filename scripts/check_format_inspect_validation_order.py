#!/usr/bin/env python3
"""Pin request-validation-before-engine ordering in /tools/sequence/inspect.

``inspect()`` decodes base64 and enforces the 1 MiB size budget in Python,
then requires the compiled Rust kernel. If ``bridge.require()`` moves back to
the top of the function, a malformed or oversized request answers 503 (engine
unavailable) instead of 422 (client input) on a deployment without the wheel.
Both fail closed, but a 422 tells the caller to fix the request while a 503
tells it to retry later. The regression tests assert 422 with ``require()``
stubbed to raise 503; if validation is moved after the engine check they can
never reach that assertion -- the same co-revert blind spot the interval
visibility guard was written for.

Reads committed source bytes via AST rather than importing the API package
(which needs Python 3.15). Source contract, not a runtime proof; the pytest
suite exercises the behaviour.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERVICE = ROOT / "apps/api/app/services/format_inspect_service.py"
DEFAULT_TEST = ROOT / "apps/api/tests/test_format_inspect_validation_order.py"

REQUIRED_TEST = "test_malformed_base64_422_wins_over_missing_engine"


def inspect(service: str, test: str) -> list[str]:
    failures: list[str] = []
    try:
        tree = ast.parse(service)
    except SyntaxError as exc:
        return [f"format_inspect_service.py is not parseable: {exc}"]

    fn = next(
        (n for n in tree.body
         if isinstance(n, ast.AsyncFunctionDef) and n.name == "inspect"),
        None,
    )
    if fn is None:
        return ["inspect() is missing from format_inspect_service.py"]

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

    decode = calls("_decode")
    require = calls("require")
    if not decode:
        failures.append("inspect() never calls _decode() (request validation is gone)")
    if not require:
        failures.append("inspect() never calls bridge.require() (fail-closed is gone)")
    if decode and require and require[0] < decode[0]:
        failures.append(
            "bridge.require() runs before _decode(): a missing wheel masks "
            "the 422 as a 503"
        )

    if REQUIRED_TEST not in test:
        failures.append(
            f"regression test {REQUIRED_TEST} is missing from "
            "test_format_inspect_validation_order.py"
        )
    if "_unavailable" not in test or "status_code == 422" not in test:
        failures.append(
            "the regression tests no longer stub a missing engine and assert 422"
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-path", type=Path, default=DEFAULT_SERVICE)
    parser.add_argument("--test-path", type=Path, default=DEFAULT_TEST)
    args = parser.parse_args(argv)
    if not args.service_path.is_file() or not args.test_path.is_file():
        print("format inspect validation order failed: service or test file is missing",
              file=sys.stderr)
        return 1
    failures = inspect(
        args.service_path.read_text(encoding="utf-8"),
        args.test_path.read_text(encoding="utf-8"),
    )
    if failures:
        print("format inspect validation order failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("format inspect validation order passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
