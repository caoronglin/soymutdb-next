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

``rowKey`` may be an inline JSX arrow or a named ``const`` function whose name
is passed as ``rowKey={rowKey}``. PR #99 moved the shipped table to the named
form to keep a comment out of the JSX attribute area; the guard used to read
only the inline form and went red on live main even though the key itself was
correct. ``--self-test`` pins both shapes.

It is a source guard, not a runtime proof: vitest still exercises the rendered
table. Run with ``--source-path``/``--test-path`` to point at a synthetic tree.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
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


def case_bodies(test: str) -> list[tuple[str, str]]:
    """Return (case name, body text) for every it(...) in the stripped source."""
    stripped = strip_comments(test)
    found: list[tuple[str, str]] = []
    for match in re.finditer(r"\bit\(\s*[\"']([^\"']+)[\"']", stripped):
        brace = stripped.find("{", match.end())
        if brace == -1:
            found.append((match.group(1), ""))
            continue
        depth = 0
        end = brace
        while end < len(stripped):
            if stripped[end] == "{":
                depth += 1
            elif stripped[end] == "}":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        found.append((match.group(1), stripped[brace:end]))
    return found


def _row_key_expression(source: str) -> str | None:
    """Return the expression that computes a row key, for either JSX shape.

    The shipped table uses a named function::

        const rowKey = (row) => JSON.stringify([...]);
        <Table rowKey={rowKey} />

    An inline arrow is equally valid and is what the regression fixtures use::

        <Table rowKey={(row) => JSON.stringify([...])} />

    Both must be read from the *definition*, not from the JSX attribute: a
    ``rowKey={rowKey}`` reference carries no ``JSON.stringify`` of its own.
    """
    body = strip_comments(source)
    attribute = re.search(r"\browKey\s*=\s*\{([\s\S]*?)\}", body)
    if attribute:
        value = attribute.group(1).strip()
        # A reference such as `rowKey={rowKey}` carries no key logic of its own;
        # resolve it to the named definition instead. Reading only the named
        # definition would let a good `const` mask a regressed inline attribute.
        if re.fullmatch(r"[A-Za-z_$][\w$]*", value):
            named = re.search(
                r"\bconst\s+" + re.escape(value) + r"\s*=\s*\([^)]*\)\s*=>\s*([^;]+);",
                body,
            )
            return named.group(1) if named else None
        return value
    return None


def inspect(source: str, test: str) -> list[str]:
    failures: list[str] = []
    body = strip_comments(source)
    expression = _row_key_expression(body)
    if expression is None:
        failures.append("variants table has no rowKey expression")
    else:
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

    # Counting names is not enough: an emptied body still reports 4 green cases.
    for name, body in case_bodies(test):
        if not re.search(r"\bexpect\s*\(", body):
            failures.append(f"row-key case asserts nothing: {name}")
    return failures


#: Four cases with a real assertion each -- the minimum the guard accepts.
_GOOD_TEST = """
it("separates rows that share an identifier and differ in assembly", () => {
  expect(keyOf(row("1", "v4"))).not.toBe(keyOf(row("1", "v5")));
});
it("separates an absent assembly from an empty one under a shared identifier", () => {
  expect(keyOf(row("1", null))).not.toBe(keyOf(row("1", "")));
});
it("keeps rows that agree on identifier and assembly in one bucket", () => {
  expect(keyOf(row("1", "v4"))).toBe(keyOf(row("1", "v4")));
});
it("renders duplicate identifiers without a React duplicate-key warning", () => {
  expect(seenKeys.size).toBe(rows.length);
});
"""

_NAMED_GOOD = """
const rowKey = (row: VariantSummary) => JSON.stringify([row.variant_id, row.assembly ?? null]);
<Table rowKey={rowKey} />
"""

_INLINE_GOOD = """
<Table rowKey={(row) => JSON.stringify([row.variant_id, row.assembly ?? null])} />
"""

_CASES: tuple[tuple[str, str, bool], ...] = (
    ("named const, correct key", _NAMED_GOOD, True),
    ("inline arrow, correct key", _INLINE_GOOD, True),
    # A named definition whose key regresses must still be caught: the JSX
    # attribute alone (rowKey={rowKey}) would look like a valid reference.
    (
        "named const with a separator-joined key",
        'const rowKey = (row) => `${row.assembly ?? ""}:${row.variant_id}`;\n'
        "<Table rowKey={rowKey} />",
        False,
    ),
    (
        "named const with a quoted-empty assembly",
        'const rowKey = (row) => JSON.stringify([row.variant_id, row.assembly ?? ""]);\n'
        "<Table rowKey={rowKey} />",
        False,
    ),
    ("no rowKey at all", "<Table dataSource={rows} />", False),
    # A good named const must not mask a regressed inline attribute, and an
    # unused named definition must not stand in for a missing rowKey.
    (
        "good named const masking a bad inline attribute",
        'const rowKey = (row) => JSON.stringify([row.variant_id, row.assembly ?? null]);\n'
        '<Table rowKey={(row) => `${row.assembly ?? ""}:${row.variant_id}`} />',
        False,
    ),
    (
        "named const never passed as rowKey",
        'const rowKey = (row) => JSON.stringify([row.variant_id, row.assembly ?? null]);\n'
        "<Table dataSource={rows} />",
        False,
    ),
)


def self_test() -> int:
    """Prove both JSX shapes are read, and every regressed shape is rejected."""
    clean = inspect(
        DEFAULT_SOURCE.read_text(encoding="utf-8"),
        DEFAULT_TEST.read_text(encoding="utf-8"),
    )
    if clean:
        print(f"SELF-TEST FAIL: committed tree is out of sync: {clean}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory():
        failures = 0
        for name, source, should_pass in _CASES:
            passed = inspect(source, _GOOD_TEST) == []
            ok = passed is should_pass
            print(f"  {'ok' if ok else 'FAIL'}: {name} -> {'accepted' if passed else 'rejected'}")
            failures += not ok
        if failures:
            print(f"SELF-TEST FAIL: {failures} case(s) escaped", file=sys.stderr)
            return 1
    print(f"SELF-TEST PASS: {len(_CASES)} shapes each behaved as pinned")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-path", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--test-path", type=Path, default=DEFAULT_TEST)
    parser.add_argument(
        "--self-test", action="store_true", help="prove the guard on synthetic shapes"
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
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
