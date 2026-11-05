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

This guard reads both scanners' committed bytes and pins **two axes**:

* the reviewed token floors on each side -- ``SHARED`` in both scanners plus
  the two production-only surfaces (``PATTERNS`` / ``LOOPBACK_PATTERNS``);
* both scanners' **corpora** -- the two ``smoke.sh`` ``--include`` sets, the
  production scanner's whole-tree ``scan_pattern()`` and its narrower
  ``scan_loopback()`` excludes. The corpora are not equal: ``smoke_static()``
  never reads ``_headers``, while ``scan_pattern()`` reads every file type.
  That is the documented division of labour, not parity; the corpora are
  pinned as reviewed literals so a silent corpus change is a divergence.

``--self-test`` plants each one-sided drift on copies of the bytes and asserts
it is caught, so a weakened pin cannot pass vacuously. Stdlib only: no build,
no node_modules, no API venv.

Pinned bytes are not proof that the scanner *fires*. Adding
``--exclude='*'`` to the decision grep keeps the token floor and the
``--include`` corpus green (both are pinned independently) while matching no
file at all: a published artifact baking ``jbrowse.example.com`` then passes
the static layer. ``witness()`` runs the real ``--profile static`` layer on a
temp tree with the committed ``smoke.sh`` -- a clean control must be green,
then each shared marker planted into ``app.js`` must turn it red. A broken
clean control aborts the witness, so a partial temp tree cannot read as
"four drifts caught".

Usage:
    python3 scripts/check_static_placeholder_scan.py
    python3 scripts/check_static_placeholder_scan.py --self-test
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
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

# The one-sided token surfaces are TWO, not one. ``PATTERNS`` blocks a baked
# API loopback (``localhost:8000``) that ``smoke.sh`` never had; the separate
# ``LOOPBACK_PATTERNS`` array blocks the bare ``localhost`` / ``127.0.0.1``
# binds via ``scan_loopback()``. Both are behaviourally guarded by
# ``test_production_artifact_scan.py``, so they are reviewed differences, not
# phantoms -- but dropping either is still a regression. "Identical pattern"
# is true of the four SHARED tokens and of nothing else. Any OTHER extra on
# either side is a divergence and fails closed until reviewed in the same commit.
PRODUCTION_ONLY: frozenset[str] = frozenset({"localhost:8000"})
LOOPBACK_ONLY: frozenset[str] = frozenset({r"localhost", r"127\.0\.0\.1"})

# Reviewed corpora. ``smoke_static()`` restricts its grep to these suffixes;
# ``check-production-artifact.sh`` instead scans the whole tree with
# ``scan_pattern()`` (no --include) and a narrower ``scan_loopback()`` that
# excludes emitted JS. These are DIFFERENT BY DESIGN: built ``_headers`` (the
# CSP line rewritten with the configured API origin by finalize-csp.ts) is
# read only by the production scanner. Pin each as a literal so a corpus flip
# -- including adding ``--include='_headers'`` to smoke.sh -- needs a reviewed
# edit here instead of blessing an equality that is already false on main.
SMOKE_CORPUS: tuple[str, ...] = ("*.html", "*.js", "*.json")
PRODUCTION_CORPUS: frozenset[str] = frozenset()  # scan_pattern(): no --include
PRODUCTION_SCAN_EXCLUDES: frozenset[str] = frozenset({"manifest.json", "SHA256SUMS"})
PRODUCTION_LOOPBACK_EXCLUDES: tuple[str, ...] = (
    "manifest.json", "SHA256SUMS", "*.js", "*.mjs", "*.map",
)

# ``smoke.sh`` invokes the same grep twice: once to decide, once to print the
# offending lines. Both must carry the identical pattern and identical includes.
SMOKE_GREP = re.compile(
    r"grep -RInE '([^']+)' \\\n\s+\"\$\{dir\}\" ((?:--include='[^']+' ?)+)",
    re.MULTILINE,
)
INCLUDE = re.compile(r"--include='([^']+)'")
PROD_ARRAY = re.compile(r"^PATTERNS=\(\n(.*?)^\)", re.MULTILINE | re.DOTALL)
LOOPBACK_ARRAY = re.compile(
    r"^LOOPBACK_PATTERNS=\(\n(.*?)^\)", re.MULTILINE | re.DOTALL,
)
PROD_ENTRY = re.compile(r"^\s*'([^']+)'", re.MULTILINE)


def smoke_greps(smoke: str) -> list[tuple[str, tuple[str, ...]]]:
    """(pattern, --include suffixes) of each static-layer grep, in order."""
    return [(pat, tuple(INCLUDE.findall(tail))) for pat, tail in SMOKE_GREP.findall(smoke)]


def array_entries(source: str, pattern: re.Pattern[str]) -> list[str]:
    """Entries of a named bash array literal (``PATTERNS`` / ``LOOPBACK_PATTERNS``)."""
    match = pattern.search(source)
    if not match:
        return []
    return PROD_ENTRY.findall(match.group(1))


def excluded_suffixes(source: str, function: str) -> tuple[str, ...] | None:
    """The ``--exclude`` suffixes of one scanner function, or None if unreadable."""
    start = source.find(f"{function}() {{")
    if start < 0:
        return None
    rest = source[start:]
    end = rest.find("\n}\n")
    body = rest[:end] if end >= 0 else rest
    return tuple(re.findall(r"--exclude='([^']+)'", body))


def tokens(pattern: str) -> set[str]:
    return set(pattern.split("|"))


def witness(smoke: str | None = None) -> list[str]:
    """Prove the committed static layer actually rejects every shared marker.

    ``check()`` reads tokens and corpora as bytes; this runs behaviour. Both
    are needed: a scanner whose pinned bytes are intact but whose decision
    branch never matches ships a placeholder origin in the artifact.
    """
    text = smoke if smoke is not None else SMOKE.read_text(encoding="utf-8")
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "tree"
        (tree / "scripts").mkdir(parents=True)
        (tree / "scripts" / "smoke.sh").write_text(text, encoding="utf-8")
        static_dir = Path(tmp) / "artifact"
        static_dir.mkdir()
        (static_dir / "index.html").write_text(
            "<!doctype html><title>Smoke</title>", encoding="utf-8"
        )
        planted = static_dir / "app.js"
        argv = [
            "bash", str(tree / "scripts" / "smoke.sh"),
            "--profile", "static", "--static-dir", str(static_dir),
        ]

        def run() -> tuple[int, str]:
            try:
                result = subprocess.run(
                    argv, capture_output=True, text=True, cwd=tree,
                    timeout=60, check=False,
                )
                return result.returncode, result.stdout + result.stderr
            except (OSError, subprocess.TimeoutExpired) as exc:
                return 2, f"could not run the static layer: {exc}"

        planted.write_text('const endpoint = "https://api.example.org/v1";\n',
                           encoding="utf-8")
        rc, output = run()
        if rc != 0:
            # A broken clean control proves nothing. Do not report planted
            # markers as "uncaught" from a layer that never ran to completion.
            return [f"clean control is not green (rc={rc}): {output[-300:]}"]
        for marker in SHARED:
            literal = marker.replace(r"\.", ".")
            planted.write_text(f'const endpoint = "{literal}";\n', encoding="utf-8")
            rc, _ = run()
            if rc == 0:
                problems.append(
                    f"static layer stayed green on planted {literal!r} "
                    "(placeholder origin would ship in a published artifact)"
                )
    return problems


def check(
    smoke: str | None = None,
    production: str | None = None,
    behaviour: str | None = None,
    *,
    witness_scan: bool = True,
) -> list[str]:
    s = smoke if smoke is not None else SMOKE.read_text(encoding="utf-8")
    p = production if production is not None else PRODUCTION.read_text(encoding="utf-8")
    b = behaviour if behaviour is not None else BEHAVIOUR.read_text(encoding="utf-8")
    errors: list[str] = []
    expected = set(SHARED)

    greps = smoke_greps(s)
    if len(greps) != 2:
        errors.append(
            f"smoke.sh static layer has {len(greps)} placeholder grep calls, "
            "expected exactly 2 (decide + report)"
        )
    else:
        if greps[0][0] != greps[1][0]:
            errors.append("the two smoke.sh placeholder greps disagree")
        for i, (pattern, includes) in enumerate(greps, 1):
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
            if includes != SMOKE_CORPUS:
                errors.append(
                    f"smoke.sh placeholder grep #{i} corpus drifted: "
                    f"--include set is {list(includes)}, reviewed subset is "
                    f"{list(SMOKE_CORPUS)} (divergence)"
                )

    prod = set(array_entries(p, PROD_ARRAY))
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

    loopback = set(array_entries(p, LOOPBACK_ARRAY))
    if not loopback:
        errors.append(
            "could not read check-production-artifact.sh LOOPBACK_PATTERNS=()"
        )
    else:
        dropped = LOOPBACK_ONLY - loopback
        if dropped:
            errors.append(
                "check-production-artifact.sh LOOPBACK_PATTERNS=() dropped "
                f"documented patterns (divergence): {sorted(dropped)}"
            )
        unreviewed = loopback - LOOPBACK_ONLY
        if unreviewed:
            errors.append(
                "check-production-artifact.sh LOOPBACK_PATTERNS=() carries "
                f"unreviewed extra patterns (divergence): {sorted(unreviewed)}"
            )

    prod_excludes = excluded_suffixes(p, "scan_pattern")
    loop_excludes = excluded_suffixes(p, "scan_loopback")
    if prod_excludes is None:
        errors.append("could not read check-production-artifact.sh scan_pattern()")
    else:
        if set(prod_excludes) != PRODUCTION_SCAN_EXCLUDES:
            errors.append(
                "check-production-artifact.sh scan_pattern() corpus drifted: "
                f"--exclude set is {list(prod_excludes)}, reviewed is "
                f"{list(PRODUCTION_SCAN_EXCLUDES)} (divergence)"
            )
        # The whole-tree scanner must stay unfiltered: an --include here would
        # make it miss _headers, the file finalize-csp.ts rewrites with the API
        # origin. Any --include is a divergence from PRODUCTION_CORPUS.
        prod_includes = tuple(
            INCLUDE.findall(
                p[p.find("scan_pattern() {"):].split("\n}\n", 1)[0]
            )
        )
        if set(prod_includes) != PRODUCTION_CORPUS:
            errors.append(
                "check-production-artifact.sh scan_pattern() narrowed its "
                f"corpus with --include {list(prod_includes)} (divergence): "
                "built _headers must stay readable"
            )
    if loop_excludes is None:
        errors.append("could not read check-production-artifact.sh scan_loopback()")
    elif loop_excludes != PRODUCTION_LOOPBACK_EXCLUDES:
        errors.append(
            "check-production-artifact.sh scan_loopback() corpus drifted: "
            f"--exclude set is {list(loop_excludes)}, reviewed is "
            f"{list(PRODUCTION_LOOPBACK_EXCLUDES)} (divergence)"
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
    if witness_scan:
        errors.extend(witness(s))
    return errors


def self_test() -> int:
    s = SMOKE.read_text(encoding="utf-8")
    p = PRODUCTION.read_text(encoding="utf-8")
    b = BEHAVIOUR.read_text(encoding="utf-8")
    clean = check(s, p, b, witness_scan=False)
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
    includes = "--include='*.html' --include='*.js' --include='*.json'"
    assert s.count(includes) == 2, "smoke.sh --include spelling changed"
    assert "  'localhost'\n  '127\\.0\\.0\\.1'\n" in p, (
        "production LOOPBACK_PATTERNS spelling changed"
    )

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
        # 8. The §4b corpus drift: widen smoke.sh's --include set with
        # `_headers`. The pin must call this a divergence, not pass silently.
        (
            "smoke.sh widens its corpus to _headers without a reviewed edit",
            s.replace(includes, includes + " --include='_headers'"),
            p, b, "corpus drifted",
        ),
        # 9. Dropping the second one-sided token surface is caught too.
        (
            "the production scanner drops a LOOPBACK_PATTERNS entry",
            s, p.replace("  '127\\.0\\.0\\.1'\n", "", 1), b,
            "LOOPBACK_PATTERNS=() dropped",
        ),
        # 10. scan_loopback() narrowing its corpus is a divergence.
        (
            "scan_loopback() changes its --exclude corpus",
            s,
            p.replace("      --exclude='*.map' \\\n", "", 1),
            b, "corpus drifted",
        ),
        # 11. scan_pattern() adding an --include would blind the production
        # scanner to _headers -- the file the static layer cannot read.
        (
            "scan_pattern() narrows the whole-tree corpus with --include",
            s,
            p.replace(
                "files=$(grep -rIl --exclude='manifest.json'",
                "files=$(grep -rIl --include='*.js' --exclude='manifest.json'",
                1,
            ),
            b, "narrowed its corpus",
        ),
    ]

    # 12/13. Byte pins cannot prove the scanner fires. A decision grep with
    # an added --exclude='*' keeps every pinned token and --include intact.
    blind = s.replace(
        " --include='*.json' >/dev/null 2>&1; then",
        " --include='*.json' --exclude='*' >/dev/null 2>&1; then",
        1,
    )
    assert blind != s, "blind plant changed nothing"
    assert check(blind, p, b, witness_scan=False) == [], (
        "the byte pin must be green for the witness plant to prove anything"
    )
    witness_cases: list[tuple[str, bool]] = [
        ("clean tree fires on every marker", not witness(s)),
        ("a byte-intact but blind scanner is caught",
         any("stayed green" in e for e in witness(blind))),
    ]
    for label, ok in witness_cases:
        print(f"{'PASS' if ok else 'FAIL'} self-test: {label}")
        if not ok:
            return 1

    results = 0
    for label, ms, mp, mb, expected in plants:
        errors = check(ms, mp, mb, witness_scan=False)
        caught = any(expected in e for e in errors)
        print(f"{'PASS' if caught else 'FAIL'} self-test: {label} -> {expected}")
        results += 1
        if not caught:
            print(f"FAIL self-test: {label} was NOT caught: {errors}", file=sys.stderr)
            return 1
    print(f"self-test: {results + len(witness_cases)} cases, 0 failure(s)")
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
    print(
        "static placeholder scan: OK "
        "(two scanners pinned: tokens + corpora, 4 markers witnessed)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
