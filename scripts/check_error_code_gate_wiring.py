#!/usr/bin/env python3
"""Keep the published error-code guards wired into a gate that actually runs.

``check_api_error_code_vocabulary.py`` (#179) and ``check_error_code_catalog.py``
(#136) were both wired into ``check-contract.sh``, reached through the frontend
gate's ``check:contract``. No CI caller may set ``SOYMUTDB_CI_SKIP_CONTRACT``
(``test_ci_job_contracts.py`` forbids the name outright), so that gate is not
skipped in CI -- but it re-exports the backend with the API 3.15 venv, and every
verify stage is skipped while the org CPU-quota pre-freeze fails. The contracts
smoke layer -- the layer that runs on a clean checkout with no venv -- invoked
neither guard, and no assertion named them. So a coordinated rename of a public
``error.code`` in the source plus both generated artifacts left the whole
collected layer green while the vocabulary guard went red on its own.

This guard pins the other half of the contract: both error-code checks must be
invoked as standalone ``|| rc=$?`` calls in ``smoke_contracts()``, and the
vocabulary guard's ``--self-test`` must be wired too -- a plain call alone can
be green while its decisive ablation plants never run. It reads committed bytes
only; ``--self-test`` plants each ablation on a copy of the tree and asserts
the check reports it by name, so weakening the guard cannot make it pass
vacuously.

The decisive negative is a *differential* probe, not a bare exit status: a
clean copy must print ``OK`` and exit 0, and only then may the co-renamed copy
be judged red -- with named ``FAIL:`` diagnostics and no traceback. A copied
tree that omits a file the vocabulary guard reads (``export_contract.py`` was
the first one) would otherwise crash on the clean copy too and be mistaken for
a caught co-rename.

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
EXPORT = Path("packages/api-client/scripts/export_contract.py")
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
# The guard's own `--self-test` plants the decisive ablations. The plain wire
# alone can be green while a weakening of `source_codes()` goes unnoticed, so
# this second call is a required wire too.
SELF_TEST_RE = re.compile(
    r'^[ \t]*"\$\{PYTHON_BIN\}"[ \t]+' + re.escape(VOCAB)
    + r'[ \t]+--self-test[ \t]*\|\|[ \t]*rc=\$\?[ \t]*$',
    re.MULTILINE,
)

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
    str(EXPORT),
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
    if not SELF_TEST_RE.search(body):
        problems.append(
            f"{VOCAB} --self-test is not wired as a standalone `|| rc=$?` call "
            "in smoke_contracts(); the decisive ablation plants would stop running"
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
        "drop the vocabulary self-test wire": lambda t: _drop_wire(t, VOCAB, "--self-test"),
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

    # The decisive negative is differential: a clean copy must be green, and a
    # co-renamed copy must be red with NAMED contract diagnostics. Judging only
    # the mutated copy's exit status lets a broken harness pass -- an incomplete
    # COPY_FILES makes the clean copy crash too (rc=1, bare traceback, zero
    # FAIL lines), which used to read as "the co-rename was caught".
    for label, plant in (("clean control", None), ("co-rename", _plant_co_rename)):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "repo"
            _copy_tree(tree)
            if plant is not None:
                plant(tree)
            result = subprocess.run(
                [sys.executable, str(tree / VOCAB)], capture_output=True, text=True,
            )
        if label == "clean control":
            if result.returncode != 0 or "OK (" not in result.stdout:
                print(
                    "SELF-TEST FAIL: the clean control is not green; the copied "
                    "tree is missing a file the vocabulary guard reads, so the "
                    f"co-rename probe would be a false positive: {result.stderr.strip()[:300]}",
                    file=sys.stderr,
                )
                failures += 1
            else:
                print(f"  ok: clean control -> {result.stdout.strip()}")
        else:
            named = result.stderr.count("FAIL:")
            if result.returncode == 0 or named == 0 or "Traceback" in result.stderr:
                print(
                    "SELF-TEST FAIL: the co-rename did not produce named contract "
                    f"FAILs (rc={result.returncode}, FAIL lines={named}); a crash "
                    "or a silent pass is not a gate signal",
                    file=sys.stderr,
                )
                failures += 1
            else:
                print(f"  ok: co-rename -> rc={result.returncode} / {named} named FAILs (gate has signal)")

    if failures:
        print(f"SELF-TEST FAIL: {failures} case(s) escaped", file=sys.stderr)
        return 1
    print(f"SELF-TEST PASS: {len(ablations) + 2} wiring cases each failed the guard")
    return 0


def _drop_wire(tree: Path, rel: str, flag: str = "") -> None:
    p = tree / "scripts/smoke.sh"
    text = p.read_text(encoding="utf-8")
    suffix = f" {flag}" if flag else ""
    line = f'  "${{PYTHON_BIN}}" {rel}{suffix} || rc=$?\n'
    assert line in text, (rel, flag)
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
