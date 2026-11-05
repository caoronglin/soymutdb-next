#!/usr/bin/env python3
"""Keep the published error-code guards wired into a gate that actually runs.

``check_api_error_code_vocabulary.py`` (#179) and ``check_error_code_catalog.py``
(#136) were both wired into ``check-contract.sh``, which the frontend gate runs
behind ``SOYMUTDB_CI_SKIP_CONTRACT``. That gate re-exports the backend with the
API venv and never ran in the affected CI window (the runner died at ``Prepare``
on quota). The contracts smoke layer -- the layer that *does* run on a clean
checkout -- did not invoke either guard, and no assertion named them. So a
coordinated rename of a public ``error.code`` in the source plus both generated
artifacts left the whole collected layer green while the vocabulary guard went
red on its own.

This guard pins the other half of the contract: both error-code checks must be
invoked as standalone ``|| rc=$?`` calls in ``smoke_contracts()``, and the
vocabulary check must still fail on the decisive co-rename. It reads committed
bytes only; ``--self-test`` plants each ablation on a copy of the tree and
asserts the check reports it by name, so weakening the guard cannot make it
pass vacuously.

Usage:
    python3 scripts/check_error_code_gate_wiring.py [--self-test]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VOCAB = "scripts/check_api_error_code_vocabulary.py"
CATALOG = "scripts/check_error_code_catalog.py"
EXCEPTIONS = Path("apps/api/app/core/exceptions.py")
CATALOG_JSON = Path("packages/api-client/error-codes.json")
OPENAPI = Path("packages/api-client/openapi.json")
GOLDEN = Path("packages/api-client/error-codes.golden.json")
GENERATOR = Path("packages/api-client/scripts/generate-api-client.sh")
CONTRACT_SH = Path("packages/api-client/scripts/check-contract.sh")

# A standalone call must be a bare statement ending in `|| rc=$?`: a piped,
# chained, backgrounded or commented-out invocation lets the layer stay green
# while the guard's failure is swallowed.
WIRES = (VOCAB, CATALOG)
WIRE_RE = {
    rel: re.compile(
        r'^[ \t]*"\$\{PYTHON_BIN\}"[ \t]+' + re.escape(rel) + r'[ \t]*\|\|[ \t]*rc=\$\?[ \t]*$',
        re.MULTILINE,
    )
    for rel in WIRES
}

OLD, NEW = "settings_version_conflict", "settings_version_conflictx"

COPY_FILES = (
    "scripts/smoke.sh",
    VOCAB,
    CATALOG,
    str(EXCEPTIONS),
    str(CATALOG_JSON),
    str(OPENAPI),
    str(GOLDEN),
    str(GENERATOR),
    str(CONTRACT_SH),
)


def contracts_body(root: Path) -> str:
    text = (root / "scripts/smoke.sh").read_text(encoding="utf-8")
    marker = "smoke_contracts() {"
    if marker not in text:
        return ""
    return text.split(marker, 1)[1].split("\n}\n", 1)[0]


def check(root: Path) -> list[str]:
    problems: list[str] = []
    body = contracts_body(root)
    if not body:
        return ["scripts/smoke.sh no longer defines smoke_contracts()"]
    for rel in WIRES:
        if not WIRE_RE[rel].search(body):
            problems.append(
                f"{rel} is not wired as a standalone `|| rc=$?` call in "
                "smoke_contracts(); the contracts layer would stop consuming it"
            )
    return problems


def _copy_tree(tree: Path) -> None:
    for rel in COPY_FILES:
        dest = tree / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)


def _plant_co_rename(tree: Path) -> None:
    """Regenerate-shaped rename of one public code in source + both artifacts."""
    p = tree / EXCEPTIONS
    s = p.read_text(encoding="utf-8")
    assert f'error_code = "{OLD}"' in s
    p.write_text(s.replace(f'error_code = "{OLD}"', f'error_code = "{NEW}"'), encoding="utf-8")
    p = tree / CATALOG_JSON
    d = json.loads(p.read_text(encoding="utf-8"))
    d[NEW] = d.pop(OLD)
    p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    p = tree / OPENAPI
    s = p.read_text(encoding="utf-8")
    assert f'"{OLD}"' in s
    p.write_text(s.replace(f'"{OLD}"', f'"{NEW}"', 1), encoding="utf-8")


def _self_test() -> int:
    clean = check(ROOT)
    if clean:
        print(f"SELF-TEST FAIL: committed tree is already unwired: {clean}", file=sys.stderr)
        return 1

    ablations = {
        "drop the vocabulary wire": lambda t: _drop_wire(t, VOCAB),
        "drop the catalog wire": lambda t: _drop_wire(t, CATALOG),
        "drop both wires": lambda t: (_drop_wire(t, VOCAB), _drop_wire(t, CATALOG)),
        "comment out the vocabulary wire": lambda t: _comment_wire(t, VOCAB),
        "chain the catalog wire behind `|| true`": lambda t: _neutralise(t, CATALOG),
    }
    failures = 0
    for label, plant in ablations.items():
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "repo"
            _copy_tree(tree)
            plant(tree)
            problems = check(tree)
            if not problems:
                print(f"SELF-TEST FAIL: planted {label!r} was NOT caught", file=sys.stderr)
                failures += 1
            else:
                print(f"  ok: planted {label!r} -> caught ({len(problems)} problem(s))")

    # The decisive negative: on a clean-but-co-renamed tree, the vocabulary
    # guard must be RED. Prove the wired gate has a real signal to consume.
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "repo"
        _copy_tree(tree)
        _plant_co_rename(tree)
        result = subprocess.run(
            [sys.executable, str(tree / VOCAB)], capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(
                "SELF-TEST FAIL: a co-rename of source + both artifacts did not "
                "redden the vocabulary guard; the wired gate has no real signal",
                file=sys.stderr,
            )
            failures += 1
        else:
            print(f"  ok: co-rename -> vocabulary guard rc={result.returncode} (red, gate has signal)")

    if failures:
        print(f"SELF-TEST FAIL: {failures} case(s) escaped", file=sys.stderr)
        return 1
    print(f"SELF-TEST PASS: {len(ablations) + 1} wiring cases each failed the guard")
    return 0


def _drop_wire(tree: Path, rel: str) -> None:
    p = tree / "scripts/smoke.sh"
    text = p.read_text(encoding="utf-8")
    line = f'  "${{PYTHON_BIN}}" {rel} || rc=$?\n'
    assert line in text, rel
    p.write_text(text.replace(line, "", 1), encoding="utf-8")


def _comment_wire(tree: Path, rel: str) -> None:
    p = tree / "scripts/smoke.sh"
    text = p.read_text(encoding="utf-8")
    line = f'  "${{PYTHON_BIN}}" {rel} || rc=$?'
    assert line in text, rel
    p.write_text(text.replace(line, "  # " + line.strip(), 1), encoding="utf-8")


def _neutralise(tree: Path, rel: str) -> None:
    p = tree / "scripts/smoke.sh"
    text = p.read_text(encoding="utf-8")
    line = f'  "${{PYTHON_BIN}}" {rel} || rc=$?'
    assert line in text, rel
    p.write_text(text.replace(line, line + " || true", 1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    problems = check(ROOT)
    if problems:
        for problem in problems:
            print(f"error-code gate wiring: FAIL: {problem}", file=sys.stderr)
        return 1
    print("error-code gate wiring: OK (both guards are consumed by the contracts layer)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
