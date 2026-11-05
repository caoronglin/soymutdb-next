#!/usr/bin/env python3
"""Freeze the *values* of the public API domain error-code vocabulary.

``packages/api-client/error-codes.json`` and the ``x-error-codes`` extension in
``openapi.json`` are generated from ``app.core.exceptions.error_code_catalog()``
by ``generate-api-client.sh``. Every existing guard for them derives its
expectations from that same source:

* ``check-contract.sh`` proves a *fresh export* equals the committed snapshot;
* ``check_error_code_catalog.py`` (PR #136) re-derives the catalog from the
  exception hierarchy via ``ast``;
* ``check_error_code_contract.py`` (PR #152) executes the source functions and
  compares their output, pinning three status codes by hand.

So a coordinated change that renames a code in the source *and* re-runs
``generate:api-client`` leaves all of them green: the snapshots agree with the
export, and the guards agree with the source. The published code values -- what
a client actually branches on -- have no independent anchor. This is the same
blind spot ``packages/bio-core/errors.golden.json`` closes for the Rust kernel
codes, one layer up.

``error-codes.golden.json`` is hand-written and is NOT an input to any
generator. The regeneration chain writes exactly three files (``openapi.json``,
``error-codes.json``, ``openapi.d.ts``); the lock is a fourth, so a routine
co-revert cannot update it. Adding, removing or renaming a public code requires
a reviewed edit to the lock, which is the point: the vocabulary is a public
contract, not a derived echo.

Reads committed bytes only: no API import, no 3.15 venv, no wheel, no database.

Usage:
    python3 scripts/check_api_error_code_vocabulary.py [--root <tree>] [--self-test]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path("packages/api-client/error-codes.golden.json")
CATALOG = Path("packages/api-client/error-codes.json")
OPENAPI = Path("packages/api-client/openapi.json")
EXCEPTIONS = Path("apps/api/app/core/exceptions.py")
# The lock must never be produced by the generator. Pin that fact so a future
# refactor cannot quietly turn it into another derived artifact.
GENERATOR = Path("packages/api-client/scripts/generate-api-client.sh")
EXPORT = Path("packages/api-client/scripts/export_contract.py")


def _load_json(path: Path) -> dict:
    """Parse an object-shaped JSON file, failing closed on duplicate keys."""
    def reject(pairs):
        seen = set()
        out = {}
        for key, value in pairs:
            if key in seen:
                raise ValueError(f"duplicate key {key!r}")
            seen.add(key)
            out[key] = value
        return out

    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path.as_posix()} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{path.as_posix()} must be a non-empty JSON object")
    return data


def source_codes(root: Path) -> set[str]:
    """Read the code literals the runtime hierarchy actually declares.

    This is deliberately a *source* read, not an import: the guard must run on a
    bare interpreter with no API dependencies installed. It is only used to
    check the lock against the source, never as the source of truth for the
    lock's contents.

    ``error_code_catalog()`` also publishes one code with no ``SoyMutDBError``
    subclass: the generic HTTPException fallback bound by the module-level
    ``HTTP_ERROR_CODE`` constant and added via ``catalog[HTTP_ERROR_CODE] = ...``.
    Both parts must be present for the fallback to count as declared, so a
    dropped catalog entry cannot lean on a leftover constant.
    """
    import ast

    tree = ast.parse((root / EXCEPTIONS).read_text(encoding="utf-8"))
    codes: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            # Collected below, and only when the catalog entry is also there:
            # reading the constant here made the fallback count as declared
            # from the leftover constant alone.
            # (a later `HTTP_ERROR_CODE = "http_error"` literal must not leak in)
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            value = None
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "error_code" for t in stmt.targets
            ):
                value = stmt.value
            elif (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id == "error_code"
            ):
                value = stmt.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                codes.add(value.value)

    const_value: str | None = None
    catalog_entry = False
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "HTTP_ERROR_CODE"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                const_value = node.value.value
    if const_value is not None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "catalog"
                and isinstance(target.slice, ast.Name)
                and target.slice.id == "HTTP_ERROR_CODE"
            ):
                catalog_entry = True
                break
    # Both halves, not either: a leftover constant with the catalog entry
    # deleted still advertises nothing, so it must not count as declared.
    if const_value is not None and catalog_entry:
        codes.add(const_value)
    return codes


def check(root: Path) -> list[str]:
    """Return the list of contract violations (empty means the tree is clean)."""
    failures: list[str] = []
    try:
        golden = _load_json(root / GOLDEN)
    except ValueError as exc:
        return [str(exc)]

    for key, value in golden.items():
        if not isinstance(key, str) or not key or not key.islower() or " " in key:
            failures.append(f"golden key {key!r} is not a lowercase snake_case token")
        if not isinstance(value, str):
            failures.append(f"golden[{key!r}] must be a description string")

    generated = {CATALOG, OPENAPI}
    for generator in (GENERATOR, EXPORT):
        text = (root / generator).read_text(encoding="utf-8")
        if GOLDEN.name in text:
            failures.append(
                f"{generator.as_posix()} mentions {GOLDEN.name}: the lock must not be "
                "an input or output of the generation chain"
            )

    try:
        catalog = _load_json(root / CATALOG)
        document = _load_json(root / OPENAPI)
    except ValueError as exc:
        failures.append(str(exc))
        return failures

    published = document.get("x-error-codes")
    if not isinstance(published, dict):
        failures.append("openapi.json no longer publishes an x-error-codes object")
        published = {}

    for label, actual in (("error-codes.json", catalog), ("x-error-codes", published)):
        for code in sorted(set(actual) - set(golden)):
            failures.append(f"{label} publishes {code!r}, which the lock does not freeze")
        for code in sorted(set(golden) - set(actual)):
            failures.append(f"{label} no longer publishes frozen code {code!r}")
        for code in sorted(set(golden) & set(actual)):
            if golden[code] != actual[code]:
                failures.append(
                    f"{label}[{code!r}] description is {actual[code]!r}; "
                    f"the lock freezes {golden[code]!r}"
                )

    try:
        declared = source_codes(root)
    except (OSError, SyntaxError) as exc:
        failures.append(f"cannot read the runtime error hierarchy: {exc}")
        return failures

    for code in sorted(declared - set(golden)):
        failures.append(
            f"exceptions.py declares {code!r}: a new public code needs a reviewed "
            "entry in error-codes.golden.json"
        )
    for code in sorted(set(golden) - declared):
        failures.append(
            f"error-codes.golden.json freezes {code!r}, which exceptions.py no "
            "longer declares: renaming a code is a breaking contract change"
        )

    return failures


def _self_test() -> int:
    """Prove each invariant fails on its own plant, on a copy of the clean tree."""
    clean = check(ROOT)
    if clean:
        print(f"SELF-TEST FAIL: committed tree is already dirty: {clean}", file=sys.stderr)
        return 1

    def plant(kind: str, tree: Path) -> None:
        if kind == "rename a code everywhere but the lock":
            old, new = "settings_version_conflict", "settings_version_conflictx"
            p = tree / EXCEPTIONS
            p.write_text(p.read_text().replace(f'error_code = "{old}"', f'error_code = "{new}"'))
            p = tree / CATALOG
            d = json.loads(p.read_text()); d[new] = d.pop(old)
            p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
            p = tree / OPENAPI
            d = json.loads(p.read_text()); d["x-error-codes"][new] = d["x-error-codes"].pop(old)
            p.write_text(json.dumps(d, indent=2) + "\n")
        elif kind == "drop a code from the published artifacts":
            for rel in (CATALOG,):
                p = tree / rel
                d = json.loads(p.read_text()); d.pop("conflict", None)
                p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
        elif kind == "change a frozen description":
            p = tree / CATALOG
            d = json.loads(p.read_text()); d["internal_error"] = "tampered"
            p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
        elif kind == "turn the lock into a generated artifact":
            p = tree / GENERATOR
            p.write_text(p.read_text() + f"\n# writes {GOLDEN.name}\n")
        elif kind == "invent a code in the source":
            p = tree / EXCEPTIONS
            s = p.read_text().replace(
                '    error_code = "validation_error"',
                '    error_code = "validation_error"\n\nclass _Phantom(SoyMutDBError):\n    error_code = "phantom_code"',
            )
            p.write_text(s)
        elif kind == "rename the http fallback in the source":
            p = tree / EXCEPTIONS
            p.write_text(
                p.read_text().replace(
                    'HTTP_ERROR_CODE = "http_error"',
                    'HTTP_ERROR_CODE = "http_error_renamed"',
                )
            )
        elif kind == "empty the lock":
            (tree / GOLDEN).write_text("{}\n")
        elif kind == "duplicate a key in the lock":
            p = tree / GOLDEN
            s = p.read_text().rstrip().rstrip("}").rstrip()
            p.write_text(s + ', "phantom_code": ""}\n')
            # object_pairs_hook only fires on true duplicates; plant one.
            p.write_text(p.read_text().replace('"conflict": "",', '"conflict": "",\n  "conflict": "",'))
        else:
            raise AssertionError(kind)

    cases = (
        "rename a code everywhere but the lock",
        "drop a code from the published artifacts",
        "change a frozen description",
        "turn the lock into a generated artifact",
        "invent a code in the source",
        "rename the http fallback in the source",
        "empty the lock",
        "duplicate a key in the lock",
    )
    failures = 0
    for kind in cases:
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "repo"
            for rel in (GOLDEN, CATALOG, OPENAPI, EXCEPTIONS, GENERATOR, EXPORT):
                dest = tree / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / rel, dest)
            plant(kind, tree)
            problems = check(tree)
            if not problems:
                print(f"SELF-TEST FAIL: planted {kind!r} was NOT caught", file=sys.stderr)
                failures += 1
            else:
                print(f"  ok: planted {kind!r} -> caught ({len(problems)} problem(s))")
    if failures:
        print(f"SELF-TEST FAIL: {failures} case(s) escaped", file=sys.stderr)
        return 1
    print(f"SELF-TEST PASS: {len(cases)} mutations each failed the guard")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="tree to check (default: repo)")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    problems = check(args.root)
    if problems:
        for problem in problems:
            print(f"api error-code vocabulary: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"api error-code vocabulary: OK ({len(_load_json(args.root / GOLDEN))} codes frozen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
