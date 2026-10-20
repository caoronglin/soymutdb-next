#!/usr/bin/env python3
"""Fail when a known-deprecated API gains a new occurrence.

The API test configuration blanket-ignores ``DeprecationWarning`` and
``PendingDeprecationWarning`` (``apps/api/pytest.ini`` and the ``filterwarnings``
block in ``apps/api/pyproject.toml``), so an upstream deprecation is invisible in
CI until it becomes a runtime break.  This guard closes that loop with a
*ratchet*: every rule has a checked-in budget in
``scripts/deprecated-api-baseline.json``; the guard fails only when a rule's
observed count exceeds its budget, and each entry records why the occurrence is
still there and what removing it costs.

The ratchet direction matters.  Fixing a deprecation lowers the count and passes.
Raising a budget to unblock a build is not possible without editing the baseline
deliberately, which is the reviewable step this guard is meant to force.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "scripts/deprecated-api-baseline.json"
SCANNED_SUFFIXES = (".py", ".ini", ".toml", ".cfg")
GENERATED_DIRS = {"__pycache__", ".venv", "node_modules"}


def load_baseline(path: Path = BASELINE) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("budgets"), dict) or not data["budgets"]:
        raise ValueError(f"{path} has no budgets")
    return data


def iter_files(root: Path, paths: list[str]):
    for relative in paths:
        base = root / relative
        if base.is_file():
            yield base
            continue
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix in SCANNED_SUFFIXES:
                if any(part in GENERATED_DIRS for part in path.parts):
                    continue
                yield path


def occurrences(root: Path, rule: dict) -> list[str]:
    pattern = re.compile(rule["pattern"])
    hits: list[str] = []
    for path in iter_files(root, rule["paths"]):
        source = path.read_text(encoding="utf-8", errors="ignore")
        for number, line in enumerate(source.splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(root).as_posix()}:{number}")
    return hits


def check(root: Path, baseline: dict | None = None) -> list[str]:
    data = baseline if baseline is not None else load_baseline()
    failures: list[str] = []
    for name, rule in sorted(data["budgets"].items()):
        limit = rule["max_occurrences"]
        hits = occurrences(root, rule)
        if len(hits) > limit:
            failures.append(
                f"{name}: {len(hits)} occurrence(s) exceed the budget of {limit}\n"
                + "\n".join(f"    {item}" for item in hits)
                + "\n"
                + "  budget: " + rule.get("why", "")
            )
    return failures


def summary(root: Path, baseline: dict | None = None) -> str:
    data = baseline if baseline is not None else load_baseline()
    lines = []
    for name, rule in sorted(data["budgets"].items()):
        hits = occurrences(root, rule)
        lines.append(f"  {name:38s} {len(hits):>3d} / {rule['max_occurrences']:<3d} budget")
    return "\n".join(lines)


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "apps/api/app").mkdir(parents=True)
        (root / "apps/api/tests").mkdir(parents=True)
        module = root / "apps/api/app/main.py"
        tests = root / "apps/api/tests/conftest.py"

        module.write_text("from fastapi.responses import ORJSONResponse\n", encoding="utf-8")
        tests.write_text(
            "from testcontainers.postgres import PostgresContainer\n", encoding="utf-8"
        )

        baseline = {
            "budgets": {
                "fastapi-orjson-response": {
                    "paths": ["apps/api/app"],
                    "pattern": "\\bORJSONResponse\\b",
                    "max_occurrences": 1,
                    "why": "self-test",
                },
                "testcontainers-legacy-postgres-import": {
                    "paths": ["apps/api/tests"],
                    "pattern": "from\\s+testcontainers\\.postgres\\s+import",
                    "max_occurrences": 1,
                    "why": "self-test",
                },
            }
        }

        # At budget: passes.
        assert check(root, baseline) == [], check(root, baseline)

        # Shrinking the debt must keep passing.
        module.write_text("# ORJSONResponse removed\n", encoding="utf-8")
        assert check(root, baseline) == [], check(root, baseline)

        # A new occurrence must fail.
        module.write_text(
            "from fastapi.responses import ORJSONResponse\n"
            "app = FastAPI(default_response_class=ORJSONResponse)\n",
            encoding="utf-8",
        )
        results = check(root, baseline)
        assert len(results) == 1 and "fastapi-orjson-response" in results[0], results

        # A second occurrence of the second rule must fail too.
        module.write_text("app = 1\n", encoding="utf-8")
        tests.write_text(
            "from testcontainers.postgres import PostgresContainer\n"
            "from testcontainers.postgres import PostgresContainer\n",
            encoding="utf-8",
        )
        results = check(root, baseline)
        assert len(results) == 1 and "testcontainers" in results[0], results

        # Generated and virtualenv trees are not scanned.
        (root / "apps/api/app/__pycache__").mkdir(parents=True)
        (root / "apps/api/app/__pycache__/main.py").write_text(
            "ORJSONResponse ORJSONResponse\n", encoding="utf-8"
        )
        tests.write_text("", encoding="utf-8")
        assert check(root, baseline) == [], check(root, baseline)

    # The checked-in baseline must describe the live tree without failures.
    failures = check(ROOT)
    assert not failures, "\n".join(failures)

    print("deprecated-API ratchet self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    failures = check(args.root)
    if failures:
        print("Deprecated-API ratchet exceeded its budget:", file=sys.stderr)
        for item in failures:
            print(" - " + item, file=sys.stderr)
        return 1
    print("Deprecated-API ratchet OK:\n" + summary(args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
