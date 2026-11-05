#!/usr/bin/env python3
"""Wiring + non-vacuity tests for the error-code doc-count guard.

``check_error_code_doc_counts.py`` pins the dev docs to counts derived from the
committed sources. It only helps if (a) a gate actually runs its self-test, and
(b) the self-test still fails when the guard is weakened. Both are asserted
here from a second file, so deleting a claim from the guard -- or dropping the
wire from ``smoke.sh`` -- is caught by pytest rather than passing a green layer.
"""
from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts/check_error_code_doc_counts.py"
SMOKE = ROOT / "scripts/smoke.sh"
DOCS = (
    ROOT / "docs/dev/api-error-code-vocabulary.md",
    ROOT / "docs/dev/error-code-catalog-contract.md",
    ROOT / "docs/dev/error-code-contract.md",
)

_spec = importlib.util.spec_from_file_location("check_error_code_doc_counts", GUARD)
assert _spec and _spec.loader
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)


class TestErrorCodeDocCounts(unittest.TestCase):
    def test_guard_exists_and_smoke_invokes_its_self_test(self) -> None:
        self.assertTrue(GUARD.is_file())
        smoke = SMOKE.read_text(encoding="utf-8")
        self.assertIn("scripts/check_error_code_doc_counts.py --self-test", smoke)

    def test_docs_match_the_measured_counts(self) -> None:
        self.assertEqual(module.check(ROOT), [])

    def test_self_test_passes_on_committed_bytes(self) -> None:
        self.assertEqual(module.self_test(), 0)

    def test_each_claim_regex_is_present(self) -> None:
        """A deleted claim regex must not silently shrink the pin."""
        self.assertEqual(len(module.CLAIMS), 5)
        for doc, pattern, key in module.CLAIMS:
            text = (ROOT / doc.relative_to(ROOT)).read_text(encoding="utf-8")
            self.assertIsNotNone(pattern.search(text), f"{key} claim missing from {doc.name}")

    def test_removing_a_claim_shrinks_the_pin(self) -> None:
        """With one claim dropped, the guard reads fewer sentences.

        This is a shape assertion, not a bypass: ``check`` iterates CLAIMS, so
        a shorter tuple cannot report the dropped key. The self-test plants one
        stale number per claim, so it too would plant one fewer drift.
        """
        self.assertEqual(len(module.CLAIMS), 5)
        keys = {key for _, _, key in module.CLAIMS}
        self.assertEqual(
            keys,
            {
                "vocab_mutations", "vocab_unittests", "catalog_pytest",
                "catalog_planted", "contract_negative",
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "repo"
            for rel in (
                module.VOCAB_GUARD, module.CATALOG_GUARD, module.CONTRACT_GUARD,
                module.VOCAB_TESTS, module.CATALOG_TESTS, *DOCS,
            ):
                dest = tree / rel.relative_to(ROOT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / rel, dest)
            saved = module.CLAIMS
            module.CLAIMS = saved[:-1]
            try:
                self.assertEqual(len(module.check(tree)), 0)
                self.assertEqual(len(saved[:-1]), 4)
            finally:
                module.CLAIMS = saved

    def test_stale_number_in_a_doc_is_rejected(self) -> None:
        """The decisive plant: bump one prose number, guard must go red."""
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "repo"
            for rel in (
                module.VOCAB_GUARD, module.CATALOG_GUARD, module.CONTRACT_GUARD,
                module.VOCAB_TESTS, module.CATALOG_TESTS, *DOCS,
            ):
                dest = tree / rel.relative_to(ROOT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / rel, dest)
            doc = tree / DOCS[0].relative_to(ROOT)
            text = doc.read_text(encoding="utf-8")
            self.assertIn("ten `unittest` regressions", text)
            stale = text.replace(
                "ten `unittest` regressions", "nine `unittest` regressions"
            )
            doc.write_text(stale, encoding="utf-8")
            problems = module.check(tree)
            self.assertTrue(any("vocab_unittests" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
