#!/usr/bin/env python3
"""Pin the static-layer placeholder scan against the production scanner.

The placeholder-origin regex is committed twice, in two scanners:

* ``scripts/smoke.sh`` ``smoke_static()`` greps built ``*.html|*.js|*.json``
  for ``api\\.example\\.com|jbrowse\\.example\\.com|change-me|CHANGE_ME``;
* ``scripts/check-production-artifact.sh`` holds the same four tokens plus
  ``localhost:8000`` in its ``PATTERNS=()`` array and scans every file type.

Only the second scanner is read back: ``scripts/test_production_artifact_scan.py``
plants those origins into a temp ``app.js`` and asserts the scanner exits 1.
Nothing parses ``smoke.sh``'s copy. Measured on live ``main``: deleting
``jbrowse\\.example\\.com`` from both ``smoke.sh`` grep lines leaves
``check-production-artifact.sh``'s behavioural suite, the registry guard, the
teeth guard and ``smoke.sh --profile contracts`` all GREEN -- the static layer
simply stops looking for that origin. Deepseek recorded this as §4a of PR #206
(count 0 readers, two copies, one guarded); it still holds on live main.

This guard reads both scanners' committed bytes, requires the reviewed shared
floor to be present and byte-identical in each, requires both ``smoke.sh`` grep
lines to carry the identical pattern, and requires the behavioural suite to
still plant every shared token. ``--self-test`` plants each one-sided drift on
copies of the bytes and asserts it is caught, so a weakened pin cannot pass
vacuously. Stdlib only: no build, no node_modules, no API venv.

Usage:
    python3 scripts/check_static_placeholder_scan.py
    python3 scripts/check_static_placeholder_scan.py --self-test
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts" / "smoke.sh"
PRODUCTION = ROOT / "scripts" / "check-production-artifact.sh"
BEHAVIOUR = ROOT / "scripts" / "test_production_artifact_scan.py"

# Reviewed floor: the origins/markers BOTH scanners must reject. A new token
# added to only one scanner is a real divergence and is reported; adding a
# token to both is the reviewed edit (update this set in the same commit).
SHARED: tuple[str, ...] = (
    r"api\.example\.com",
    r"jbrowse\.example\.com",
    "change-me",
    "CHANGE_ME",
)

# The production scanner blocks one extra always-on surface that ``smoke.sh``
# deliberately does not: a baked API loopback. It is guarded behaviourally by
# ``test_production_artifact_scan.py``, so it is an allowed, reviewed difference
# -- but dropping it is still a regression. Any OTHER extra on either side is a
# divergence and fails closed until this file is reviewed in the same commit.
PRODUCTION_ONLY: frozenset[str] = frozenset({"localhost:8000"})

# ``smoke.sh`` invokes the same grep twice: once to decide, once to print the
# offending lines. Both must carry the identical pattern.
SMOKE_GREP = re.compile(
    r"grep -RInE '([^']+)' \\\n\s+\"\$\{dir\}\" --include='\*\.html'",
    re.MULTILINE,
)
PROD_ARRAY = re.compile(r"^PATTERNS=\(\n(.*?)^\)", re.MULTILINE | re.DOTALL)
PROD_ENTRY = re.compile(r"^\s*'([^']+)'", re.MULTILINE)


def smoke_patterns(smoke: str) -> list[str]:
    """The regex in each of the two static-layer grep calls, in order."""
    return SMOKE_GREP.findall(smoke)


def production_patterns(production: str) -> list[str]:
    """The always-blocked ``PATTERNS=()`` entries (demo/loopback excluded)."""
    match = PROD_ARRAY.search(production)
    if not match:
        return []
    return PROD_ENTRY.findall(match.group(1))


def tokens(pattern: str) -> set[str]:
    return set(pattern.split("|"))


def check(
    smoke: str | None = None,
    production: str | None = None,
    behaviour: str | None = None,
) -> list[str]:
    s = smoke if smoke is not None else SMOKE.read_text(encoding="utf-8")
    p = production if production is not None else PRODUCTION.read_text(encoding="utf-8")
    b = behaviour if behaviour is not None else BEHAVIOUR.read_text(encoding="utf-8")
    errors: list[str] = []
    expected = set(SHARED)

    greps = smoke_patterns(s)
    if len(greps) != 2:
        errors.append(
            f"smoke.sh static layer has {len(greps)} placeholder grep calls, "
            "expected exactly 2 (decide + report)"
        )
    else:
        if greps[0] != greps[1]:
            errors.append("the two smoke.sh placeholder greps disagree")
        for i, pattern in enumerate(greps, 1):
            found = tokens(pattern)
            missing = expected - found
            extra = found - expected
            if missing:
                errors.append(
                    f"smoke.sh placeholder grep #{i} is missing reviewed "
                    f"patterns: {sorted(missing)}"
                )
            if extra:
                errors.append(
                    f"smoke.sh placeholder grep #{i} carries unreviewed extra "
                    f"patterns (divergence): {sorted(extra)}"
                )

    prod = set(production_patterns(p))
    if not prod:
        errors.append("could not read check-production-artifact.sh PATTERNS=()")
    else:
        missing = expected - prod
        if missing:
            errors.append(
                "check-production-artifact.sh PATTERNS=() is missing reviewed "
                f"patterns: {sorted(missing)}"
            )
        unreviewed = prod - expected - PRODUCTION_ONLY
        if unreviewed:
            errors.append(
                "check-production-artifact.sh PATTERNS=() carries unreviewed "
                f"extra patterns (divergence): {sorted(unreviewed)}"
            )
        dropped = PRODUCTION_ONLY - prod
        if dropped:
            errors.append(
                "check-production-artifact.sh dropped its documented extra "
                f"patterns: {sorted(dropped)}"
            )

    # Read-back floor: the behavioural suite must plant every shared token as a
    # literal (the .example.com ones without their regex escaping), so a token
    # cannot be dropped from the scanner's signal silently.
    planted = set(re.findall(r'"([a-zA-Z0-9_.:-]+)"', b))
    literals = {t.replace(r"\.", ".") for t in SHARED}
    for literal in sorted(literals - planted):
        errors.append(
            f"test_production_artifact_scan.py no longer plants {literal!r}"
        )
    return errors


def self_test() -> int:
    s = SMOKE.read_text(encoding="utf-8")
    p = PRODUCTION.read_text(encoding="utf-8")
    b = BEHAVIOUR.read_text(encoding="utf-8")
    clean = check(s, p, b)
    if clean:
        print(f"FAIL self-test: clean tree drifts: {clean}")
        return 1

    jbrowse = r"jbrowse\.example\.com"
    api = r"api\.example\.com"
    full = r"api\.example\.com|jbrowse\.example\.com|change-me|CHANGE_ME"
    assert s.count(full) == 2, "smoke.sh pattern spelling changed"
    assert s.count(jbrowse) == 2
    assert f"  '{jbrowse}'\n" in p, "production array spelling changed"
    assert '"jbrowse.example.com"' in b

    plants: list[tuple[str, str, str, str, str]] = [
        # 1. Drop one origin from BOTH smoke.sh greps (the §4a ablation).
        (
            "the static layer stops looking for jbrowse.example.com",
            s.replace(r"|" + jbrowse, ""), p, b, "missing reviewed patterns",
        ),
        # 2. Drop the same origin from the production scanner's array.
        (
            "the production scanner drops jbrowse.example.com",
            s, p.replace(f"  '{jbrowse}'\n", "", 1), b,
            "missing reviewed patterns",
        ),
        # 3. Make the two smoke.sh greps disagree (decide vs report).
        (
            "the two static greps disagree",
            s.replace(full, r"jbrowse\.example\.com|change-me|CHANGE_ME", 1),
            p, b, "disagree",
        ),
        # 4. Weakening the behavioural suite's plant list is caught.
        (
            "the behavioural suite stops planting jbrowse.example.com",
            s, p, b.replace('"jbrowse.example.com", ', "", 1),
            "no longer plants",
        ),
        # 5. A new token added to the production scanner alone diverges.
        (
            "a token is added to the production scanner alone",
            s,
            p.replace(
                f"  '{api}'\n",
                f"  '{api}'\n  'extra-origin'\n",
                1,
            ),
            b, "divergence",
        ),
        # 6. A new token added to smoke.sh alone diverges too.
        (
            "a token is added to the static layer alone",
            s.replace(full, full + "|extra-origin", 1),
            p, b, "divergence",
        ),
        # 7. Dropping the documented production-only loopback is caught.
        (
            "the production scanner drops its loopback pattern",
            s,
            p.replace(
                "  'localhost:8000' # A deployment must not bake an API "
                "loopback into JS.\n",
                "",
                1,
            ),
            b, "documented extra",
        ),
    ]

    results = 0
    for label, ms, mp, mb, expected in plants:
        errors = check(ms, mp, mb)
        caught = any(expected in e for e in errors)
        print(f"{'PASS' if caught else 'FAIL'} self-test: {label} -> {expected}")
        results += 1
        if not caught:
            print(f"FAIL self-test: {label} was NOT caught: {errors}", file=sys.stderr)
            return 1
    print(f"self-test: {results} cases, 0 failure(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    errors = check()
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("static placeholder scan: OK (two scanners pinned, read back)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
