"""Self-test for scripts/check_i18n_interpolation.py.

The guard only earns a CI slot if it fails closed on the bug class it was
written for. Each case below is a small synthetic workspace: valid calls pass,
and a missing/shorthand/multiline interpolation fails with the exact file:line.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "scripts" / "check_i18n_interpolation.py"

EN = {
    "summary": "{{genes}} genes × {{conditions}} conditions.",
    "hint": "Maximum {{max}} items.",
    "plain": "No placeholders here.",
    "plural": {"one": "{{count}} item", "other": "{{count}} items"},
}
ZH = {
    "summary": "{{genes}} 个基因 × {{conditions}} 个条件。",
    "hint": "最多 {{max}} 项。",
    "plain": "没有占位符。",
    "plural": {"one": "{{count}} 项", "other": "{{count}} 项"},
}


def build_workspace(tmp: Path, source: str, *, en: dict | None = None, zh: dict | None = None) -> tuple[Path, Path]:
    locales = tmp / "locales"
    for lang, catalog in (("en", en or EN), ("zh", zh or ZH)):
        directory = locales / lang
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "common.json").write_text(json.dumps(catalog), encoding="utf-8")
    source_dir = tmp / "src"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "page.tsx").write_text(source, encoding="utf-8")
    return locales, source_dir


def run_guard(locales: Path, source: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), "--locales-dir", str(locales), "--source", str(source)],
        capture_output=True,
        text=True,
        timeout=120,
    )


class InterpolationGuardTests(unittest.TestCase):
    def test_valid_calls_pass_including_shorthand_and_plural_count(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            locales, source = build_workspace(
                tmp,
                """
                const a = t("summary", { genes: 2, conditions: 3 });
                const b = t("hint", { max: 50, defaultValue: "fallback" });
                const c = t("plural", { count: 2 });
                const d = t("plain");
                const e = t("siteContent.key", { whatever: 1 });
                const f = t("summary", { genes: 2, ...rest });
                """,
                en={"summary": EN["summary"], "hint": EN["hint"], "plural": EN["plural"], "plain": "x"},
            )
            completed = run_guard(locales, source)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_missing_placeholder_fails_with_file_and_line(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            locales, source = build_workspace(
                tmp,
                """const first = t("summary", { genes: 2, conds: 3 });
                const second = t("summary", { genes: 2, conditions: 3 });
                """,
            )
            completed = run_guard(locales, source)
            self.assertEqual(completed.returncode, 1, completed.stdout)
            self.assertIn("page.tsx:1", completed.stdout)
            self.assertIn("conditions", completed.stdout)
            self.assertNotIn("page.tsx:2", completed.stdout)

    def test_shorthand_interpolation_counts_as_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            locales, source = build_workspace(
                tmp,
                "const hint = t('hint', { max });",
                en={"hint": EN["hint"]},
            )
            # Default-locale keys only; the zh catalog intentionally lacks it.
            completed = run_guard(locales, source)
            self.assertEqual(completed.returncode, 0, completed.stdout)

    def test_zh_only_placeholder_is_also_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            locales, source = build_workspace(
                tmp,
                'const hint = t("hint", { maximum: 10 });',
                en={"hint": "Up to ten."},
                zh={"hint": "最多 {{max}} 项。"},
            )
            completed = run_guard(locales, source)
            self.assertEqual(completed.returncode, 1, completed.stdout)
            self.assertIn("max", completed.stdout)

    def test_multiline_object_literal_is_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            locales, source = build_workspace(
                tmp,
                """const label = t("summary", {
                  genes: 2,
                  conditions: 3,
                });""",
            )
            completed = run_guard(locales, source)
            self.assertEqual(completed.returncode, 0, completed.stdout)

    def test_reported_bug_shape_fails(self) -> None:
        """The exact shipped bug: `conds` supplied where `{{conditions}}` expected."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            locales, source = build_workspace(
                tmp,
                't("summary", { genes: data.genes.length, conds: data.conditions.length });',
            )
            completed = run_guard(locales, source)
            self.assertEqual(completed.returncode, 1, completed.stdout)
            # The report names the supplied option so `conds` vs `conditions` is
            # obvious to a reviewer, not just "missing placeholder".
            self.assertIn("conds", completed.stdout)
            self.assertIn("conditions", completed.stdout)


if __name__ == "__main__":
    unittest.main()
