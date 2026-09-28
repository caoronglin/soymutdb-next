#!/usr/bin/env python3
"""Visible-text contract: user-visible strings must come from the i18n catalog.

The portal and the admin console share one en/zh catalog. A hardcoded sentence
in a template renders in only one language (or no language at all), which is
the regression this gate stops: the migration added whole pages whose text never
reached the catalog, and once a string is hardcoded it never shows up in a
translation review.

The heuristic is deliberately conservative. It flags letters in:

  * text nodes inside `<template>` (outside `<script>`, `<style>`, comments and
    `{{ interpolation }}`);
  * literal `placeholder`, `title`, `aria-label` and `alt` attributes.

Technical vocabulary is allowlisted: gene identifiers, chromosome names, allele
types, short status/abbreviation tokens and punctuation-only text are not
translated. Everything else is a hit.

The remaining hits are tracked in ``visible-i18n-baseline.json``: the count per
file may fall but never rise, and a new file with hits fails outright. Entries
are removed as pages are translated, so the backlog stays explicit instead of
being hidden by a blanket ignore.

Usage:
    python3 scripts/check_visible_i18n.py
    python3 scripts/check_visible_i18n.py --update-baseline
    python3 scripts/check_visible_i18n.py --self-test
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = Path(__file__).resolve().parent / "visible-i18n-baseline.json"

SCAN_ROOTS: tuple[tuple[str, str], ...] = (
    ("portal", "apps/web/src"),
    ("admin", "apps/admin/src"),
)

SCRIPT = re.compile(r"<script\b.*?</script>", re.S | re.I)
STYLE = re.compile(r"<style\b.*?</style>", re.S | re.I)
COMMENT = re.compile(r"<!--.*?-->", re.S)
INTERPOLATION = re.compile(r"\{\{.*?\}\}", re.S)
TEXT_NODE = re.compile(r">([^<>]+)<")
ATTRIBUTE = re.compile(r'(?<!:)\b(placeholder|title|aria-label|alt)="([^"]*)"')
HAS_WORDS = re.compile(r"[A-Za-z\u4e00-\u9fff]")

# Exact strings that are product/brand/technical vocabulary, never translated.
ALLOWED_EXACT = frozenset(
    {
        "SoyMutDB",
        "JBrowse",
        "JBrowse 2",
        "BLAST",
        "BLASTn",
        "NCBI",
        "UniProt",
        "Ensembl",
        "EBI",
        "SHA-256",
        "SNP",
        "INS",
        "DEL",
        "MNV",
        "SV",
        "HIGH",
        "MODERATE",
        "LOW",
        "MODIFIER",
        "EN",
        "中文",
        # Keyboard-shortcut glyphs: key names, not prose. The command palette
        # shows the accelerator next to its trigger in every locale.
        "⌘K",
        "Esc",
        # Identifier field names rendered as column labels. They are contract
        # vocabulary (public_id / internal_id), never translated.
        "public_id",
        "internal_id",
        "N",
        "T",
        "—",
        "·",
        "×",
        "→",
    }
)

# A short lowercase/technical token list instead of a permissive length rule:
# "bp" and "q" are units, "Open" and "gene" are words that must be translated.
ALLOWED_SHORT = frozenset(
    {
        "bp",
        "kb",
        "Mb",
        "Gb",
        "kb",
        "CDS",
        "UTR",
        "TPM",
        "FPKM",
        "ID",
        "URL",
        "API",
        "Tm",
        "GC",
        "p",
        "q",
        "EMS",
        "TSV",
        "CSV",
        "F",
        "R",
        "C",
        # Keyboard accelerator keys shown inside <kbd> (⌘K tokenises to "K").
        "K",
        "v",
        "true",
        "false",
    }
)

# Identifier-shaped strings: accessions/coordinates contain a digit, and
# all-caps tokens are abbreviations. A sentence has untranslated words.
ALLOWED_PATTERNS = (
    re.compile(r"^[\W\d_]+$"),
    re.compile(r"^(Chr|chr)[0-9A-Za-z._]+$"),
    re.compile(r"^[A-Za-z0-9._:+-]*[0-9][A-Za-z0-9._:+-]*$"),
    re.compile(r"^[A-Z]{2,}$"),
)

# A text node is checked token by token: "SoyMutDB · :" is product name plus
# punctuation, while "Gene structure" is two untranslated words. Multi-word
# scientific names are handled by their own entries.
WORD = re.compile(r"[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff._:+-]*")


def _word_allowed(word: str) -> bool:
    if word in ALLOWED_EXACT or word in ALLOWED_SHORT:
        return True
    return any(pattern.match(word) for pattern in ALLOWED_PATTERNS)


def is_allowed(text: str) -> bool:
    words = [match.group(0) for match in WORD.finditer(text)]
    if not words:
        return True
    return all(_word_allowed(word) for word in words)


def count_hits(source: str) -> int:
    """Count visible-text hits in one SFC source."""
    if "<template>" not in source:
        return 0
    body = SCRIPT.sub("", source)
    body = STYLE.sub("", body)
    body = COMMENT.sub("", body)
    body = INTERPOLATION.sub("", body)

    hits = 0
    for match in TEXT_NODE.finditer(body):
        text = match.group(1)
        if HAS_WORDS.search(text) and not is_allowed(text):
            hits += 1
    for match in ATTRIBUTE.finditer(body):
        value = match.group(2)
        if HAS_WORDS.search(value) and not is_allowed(value):
            hits += 1
    return hits


def collect(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _, relative in SCAN_ROOTS:
        directory = root / relative
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.vue")):
            hits = count_hits(path.read_text(encoding="utf-8"))
            if hits:
                counts[str(path.relative_to(root))] = hits
    return counts


def load_baseline(path: Path) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    counts = data.get("counts", data)
    return {str(key): int(value) for key, value in counts.items()}


def check(counts: dict[str, int], baseline: dict[str, int]) -> list[str]:
    failures: list[str] = []
    for path, hits in sorted(counts.items()):
        allowed = baseline.get(path, 0)
        if hits > allowed:
            failures.append(f"{path}: {hits} hardcoded string(s), baseline {allowed}")
    return failures


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "apps/web/src/views/Demo.vue"
        source.parent.mkdir(parents=True)
        source.write_text(
            '<template><h1>Translate me</h1><p>{{ t("x") }}</p>'
            '<img alt="Chr01" /><a aria-label="Open gene {{ id }}"></a></template>',
            encoding="utf-8",
        )
        counts = collect(root)
        # "Translate me" and the literal "Open gene" are text; Chr01 and the
        # interpolated value are allowlisted/skipped.
        assert counts == {"apps/web/src/views/Demo.vue": 2}, counts
        assert check(counts, {}) == [
            "apps/web/src/views/Demo.vue: 2 hardcoded string(s), baseline 0"
        ]
        assert check(counts, {"apps/web/src/views/Demo.vue": 2}) == []

        source.write_text(
            '<template><h1>Two hardcoded strings here</h1><p>And another one</p></template>',
            encoding="utf-8",
        )
        counts = collect(root)
        assert counts["apps/web/src/views/Demo.vue"] == 2, counts
    print("visible i18n self-test passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    counts = collect(ROOT)
    if args.update_baseline:
        payload = {
            "comment": (
                "Hardcoded visible strings per Vue file. The count may fall but must "
                "never rise; remove an entry once the page is translated."
            ),
            "counts": counts,
        }
        args.baseline.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        total = sum(counts.values())
        print(f"baseline written: {len(counts)} file(s), {total} string(s)")
        return 0

    if not args.baseline.is_file():
        print(f"missing baseline: {args.baseline}", file=sys.stderr)
        return 1
    failures = check(counts, load_baseline(args.baseline))
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        print(
            "move the string into packages/i18n-core (en+zh) or, if it is "
            "technical vocabulary, extend the allowlist with a reason.",
            file=sys.stderr,
        )
        return 1
    print(f"visible i18n OK ({sum(counts.values())} tracked string(s) in {len(counts)} file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
