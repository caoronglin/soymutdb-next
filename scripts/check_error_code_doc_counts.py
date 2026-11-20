#!/usr/bin/env python3
"""Pin the error-code dev docs to counts measured from the committed sources.

The three error-code guards and their regression suites grew in steps (#136,
#152, #179, #206, #212). Each step added a case or a test and edited the dev
docs by hand. Those docs state counts in prose ("eight ``unittest``
regressions", "10 planted negative cases", "eleven negative shapes"), and every
gate reads only source/artifact bytes -- none reads the docs. So a merge that
adds a test but forgets the sentence ships a green contracts layer with a stale
number. The merged tree of live ``main`` and PR #215 is a concrete instance:
it has 10 unittest regressions / 11 planted catalog cases while the docs still
say eight / 10.

This guard derives each count from the thing it measures (AST of the committed
Python files) and asserts the prose still carries that number as a word or a
digit. It reads no generated artifact and needs no Python 3.15 venv, API
import, wheel, database or workspace install, so it runs before the expensive
build. ``--self-test`` plants stale-number drifts on copies of the docs and
asserts each is caught, so weakening a regex cannot make the guard pass
vacuously.

Each claim must also match exactly one sentence. Taking the first hit would let
a decoy paragraph carrying the right number satisfy the claim while the
sentence that actually documents the suite went stale, and a value comparison
alone cannot see that; ambiguity is reported instead of read. The self-test
plants such a decoy as its last case.

Usage:
    python3 scripts/check_error_code_doc_counts.py
    python3 scripts/check_error_code_doc_counts.py --self-test
"""
from __future__ import annotations

import argparse
import ast
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VOCAB_GUARD = ROOT / "scripts/check_api_error_code_vocabulary.py"
CATALOG_GUARD = ROOT / "scripts/check_error_code_catalog.py"
CONTRACT_GUARD = ROOT / "scripts/check_error_code_contract.py"
VOCAB_TESTS = ROOT / "packages/api-client/python_tests/test_api_error_code_vocabulary.py"
CATALOG_TESTS = ROOT / "scripts/test_error_code_catalog_contract.py"
VOCAB_DOC = ROOT / "docs/dev/api-error-code-vocabulary.md"
CATALOG_DOC = ROOT / "docs/dev/error-code-catalog-contract.md"
CONTRACT_DOC = ROOT / "docs/dev/error-code-contract.md"

ONES = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
    12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
    16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen",
    20: "twenty",
}


def _literal_case_count(path: Path, var: str = "cases") -> int:
    """Count elements of a top-level ``cases = {...}`` / ``cases = (...)``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    counts: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == var for t in node.targets):
            continue
        value = node.value
        if isinstance(value, ast.Dict):
            counts.append(len(value.keys))
        elif isinstance(value, (ast.Tuple, ast.List)):
            counts.append(len(value.elts))
    if len(counts) != 1:
        raise ValueError(f"{path.name}: expected one {var} literal, found {counts}")
    return counts[0]


def _unittest_count(path: Path) -> int:
    """Count ``def test_*`` methods/functions in a unittest-style file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    )


def _pytest_collected_count(path: Path) -> int:
    """Count collected cases, expanding ``@pytest.mark.parametrize`` rows."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    total = 0
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test"):
            continue
        rows = 1
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            if dec.func.attr != "parametrize" or len(dec.args) < 2:
                continue
            values = dec.args[1]
            if isinstance(values, (ast.List, ast.Tuple)):
                rows = len(values.elts)
        total += rows
    return total


def _self_test_cases_count(path: Path) -> int:
    """Count cases appended to ``cases`` in a dynamically-built self-test."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    total = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "append":
            continue
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "cases":
            total += 1
    if total == 0:
        raise ValueError(f"{path.name}: no cases.append() calls found")
    return total


def measured(root: Path) -> dict[str, int]:
    """Derive every pinned count from the committed bytes under ``root``."""
    return {
        "vocab_mutations": _literal_case_count(root / VOCAB_GUARD.relative_to(ROOT)),
        "vocab_unittests": _unittest_count(root / VOCAB_TESTS.relative_to(ROOT)),
        "catalog_planted": _literal_case_count(root / CATALOG_GUARD.relative_to(ROOT)),
        "catalog_pytest": _pytest_collected_count(root / CATALOG_TESTS.relative_to(ROOT)),
        "contract_negative": _self_test_cases_count(root / CONTRACT_GUARD.relative_to(ROOT)),
    }


# Each claim is a regex with a named ``num`` group. The number is part of a
# reviewed sentence; pinning the *sentence shape* (not a bare word) keeps an
# unrelated "ten" elsewhere in the doc from satisfying the claim.
CLAIMS = (
    (
        VOCAB_DOC,
        re.compile(r"`--self-test` plants (?P<num>\w+) independent defects"),
        "vocab_mutations",
    ),
    (VOCAB_DOC, re.compile(r"provides\s+(?P<num>\w+) `unittest` regressions"), "vocab_unittests"),
    (
        CATALOG_DOC,
        re.compile(r"regression suite:\s*(?P<num>\w+)\s+pytest cases"),
        "catalog_pytest",
    ),
    (CATALOG_DOC, re.compile(r"\((?P<num>\w+) planted\s+negative cases\)"), "catalog_planted"),
    (
        CONTRACT_DOC,
        re.compile(r"`--self-test` proves (?P<num>\w+) negative shapes"),
        "contract_negative",
    ),
)


def _number_token(value: int, style: str) -> str:
    return str(value) if style == "digit" else ONES.get(value, str(value))


def _number_value(token: str) -> int | None:
    token = token.lower()
    word_to_int = {v: k for k, v in ONES.items()}
    if token in word_to_int:
        return word_to_int[token]
    return int(token) if token.isdigit() else None


def check(root: Path) -> list[str]:
    problems: list[str] = []
    try:
        counts = measured(root)
    except (ValueError, OSError, SyntaxError) as exc:
        return [f"cannot measure the error-code counts: {exc}"]

    for doc, pattern, key in CLAIMS:
        text = (root / doc.relative_to(ROOT)).read_text(encoding="utf-8")
        want = counts[key]
        matches = list(pattern.finditer(text))
        if not matches:
            problems.append(f"{doc.name}: missing claim sentence for {key}")
            continue
        if len(matches) > 1:
            # ``search`` would take the first hit, so a second sentence with the
            # same shape could satisfy the claim while the real one went stale.
            # Refuse the ambiguity instead of guessing which sentence is real.
            problems.append(
                f"{doc.name}: {key} claim is ambiguous, matches {len(matches)} sentences"
            )
            continue
        match = matches[0]
        got = _number_value(match.group("num"))
        if got != want:
            problems.append(
                f"{doc.name}: {key} is {want}, but prose states {match.group('num')!r}"
            )
    return problems


def duplicate_sentence(shape: str) -> str:
    """A second paragraph carrying the claim's shape and its number verbatim."""
    return "A decoy paragraph repeats: " + shape.replace("\n", " ") + ".\n\n"


def self_test() -> int:
    """Plant a stale number in each claim sentence and assert it is caught."""
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "repo"
        files = [
            VOCAB_GUARD, CATALOG_GUARD, CONTRACT_GUARD, VOCAB_TESTS,
            CATALOG_TESTS, VOCAB_DOC, CATALOG_DOC, CONTRACT_DOC,
        ]
        for rel in files:
            dest = tree / rel.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, dest)

        counts = measured(tree)
        failures = 0
        cases = 0
        for doc, pattern, key in CLAIMS:
            doc_path = tree / doc.relative_to(ROOT)
            original = doc_path.read_text(encoding="utf-8")
            want = counts[key]
            match = pattern.search(original)
            if not match:
                print(f"SELF-TEST FAIL: claim {key} missing from {doc.name}", file=sys.stderr)
                failures += 1
                continue
            wrong = want + 1
            token = _number_token(wrong, "word")
            stale = (
                original[: match.start("num")]
                + token
                + original[match.end("num") :]
            )
            doc_path.write_text(stale, encoding="utf-8")
            problems = check(tree)
            if not any(key in p for p in problems):
                print(f"SELF-TEST FAIL: planted stale {key} was NOT caught", file=sys.stderr)
                failures += 1
            else:
                print(f"  ok: planted stale {key} -> caught")
            cases += 1
            doc_path.write_text(original, encoding="utf-8")

        # A second sentence with the same shape would let ``search`` read the
        # decoy while the real sentence went stale. Planting one decoy carrying
        # the *correct* number must still be refused, and so must a broken real
        # sentence hidden behind it.
        cases += 1
        doc_path = tree / CATALOG_DOC.relative_to(ROOT)
        original = doc_path.read_text(encoding="utf-8")
        match = next(pat for doc, pat, key in CLAIMS if key == "catalog_pytest").search(original)
        if match is None:
            print("SELF-TEST FAIL: catalog_pytest claim missing from catalog doc", file=sys.stderr)
            failures += 1
        else:
            # Second sentence, a separate paragraph, carrying the *correct*
            # number. It must be refused as ambiguous, not accepted as the
            # reading of the sentence that actually documents the suite.
            decoy_line = duplicate_sentence(match.group(0))
            shadowed = original.replace(match.group(0), decoy_line + match.group(0), 1)
            doc_path.write_text(shadowed, encoding="utf-8")
            problems = check(tree)
            if not any("catalog_pytest" in p and "ambiguous" in p for p in problems):
                print("SELF-TEST FAIL: duplicate claim sentence was NOT refused", file=sys.stderr)
                failures += 1
            else:
                print("  ok: duplicate claim sentence -> refused")
            doc_path.write_text(original, encoding="utf-8")

        clean = check(tree)
        if clean:
            print("SELF-TEST FAIL: clean copy did not pass:", clean, file=sys.stderr)
            failures += 1
        if failures:
            return 1
        print(
            f"error-code doc counts self-test passed "
            f"({cases} plants incl. one duplicate-sentence decoy + clean copy)"
        )
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="plant stale numbers")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    problems = check(ROOT)
    if problems:
        print("error-code doc counts: FAIL", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("error-code doc counts: OK (docs match the measured counts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
