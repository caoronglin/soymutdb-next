"""The kernel code set is a public contract, not a derived echo of errors.rs.

``scripts/check_kernel_error_golden.py`` binds ``errors.rs`` to a hand-written
lock file. This suite proves the guard is load-bearing: a rename that moves
``errors.rs`` and every co-derived consumer together must still turn a gate
red, because the lock file is not derived from any of them.

It reads committed bytes only -- no wheel, no Rust toolchain, no API venv --
and uses stdlib ``unittest`` so it runs on a bare interpreter. pytest collects
the same ``TestCase`` classes in CI, where the whole ``python_tests`` directory
is already collected by both the bio-core and api-tests stages.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
GUARD_PATH = ROOT / "scripts/check_kernel_error_golden.py"
ERRORS_RS = ROOT / "packages/bio-core/src/errors.rs"
GOLDEN = ROOT / "packages/bio-core/errors.golden.json"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("kernel_error_golden_guard", GUARD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KernelErrorGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.guard = _load_guard()

    def test_clean_tree_has_no_golden_drift(self) -> None:
        self.assertEqual(self.guard.check(ROOT), [])

    def test_guard_self_test_passes(self) -> None:
        self.assertEqual(self.guard.self_test(), 0)

    def test_lock_file_is_hand_written_not_generated(self) -> None:
        """The anchor must stay independent of any generator."""
        text = GOLDEN.read_text(encoding="utf-8")
        self.assertNotIn("generated", text.lower())
        self.assertTrue(json.loads(text))

    def test_every_kernel_code_is_frozen(self) -> None:
        codes, failures = self.guard.parse_errors_rs(
            ERRORS_RS.read_text(encoding="utf-8")
        )
        self.assertEqual(failures, [])
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(set(codes), set(golden))
        self.assertEqual(codes, golden)

    def test_coordinated_rename_still_fails(self) -> None:
        """deepseek's killing mutation, reproduced against the golden.

        #134's guard compares ``errors.rs`` with a table mirrored from
        ``errors.rs``; renaming both is green. Here the lock file is an
        independent anchor, so the same coordinated rename stays red.
        """
        errors = ERRORS_RS.read_text(encoding="utf-8")
        golden = GOLDEN.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "packages/bio-core/src").mkdir(parents=True)
            (root / "packages/bio-core/src/errors.rs").write_text(
                errors.replace('"EMPTY_SEQUENCE"', '"EMPTY_SEQUENCX"'),
                encoding="utf-8",
            )
            (root / "packages/bio-core/errors.golden.json").write_text(
                golden, encoding="utf-8"
            )
            # A co-derived mirror that also renamed its key is irrelevant:
            # this guard reads neither the bridge nor any regression file.
            (root / "packages/bio-core/src/bio_core_bridge.py").write_text(
                '"EMPTY_SEQUENCX": "empty sequence"', encoding="utf-8"
            )
            found = self.guard.check(root)
        self.assertTrue(
            any(
                "no longer raises" in item or "needs a reviewed entry" in item
                for item in found
            ),
            f"a coordinated rename must not pass a value-level golden: {found}",
        )

    def test_rename_in_all_three_sources_still_fails(self) -> None:
        """Even the full mutation set (errors.rs + bridge + gutted tests) is red."""
        errors = ERRORS_RS.read_text(encoding="utf-8")
        golden = GOLDEN.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "packages/bio-core/src").mkdir(parents=True)
            (root / "apps/api/tests").mkdir(parents=True)
            (root / "packages/bio-core/src/errors.rs").write_text(
                errors.replace('"EMPTY_SEQUENCE"', '"EMPTY_SEQUENCX"'),
                encoding="utf-8",
            )
            (root / "packages/bio-core/errors.golden.json").write_text(
                golden, encoding="utf-8"
            )
            (root / "apps/api/app/services").mkdir(parents=True, exist_ok=True)
            (root / "apps/api/app/services/bio_core_bridge.py").write_text(
                '"EMPTY_SEQUENCX": "empty sequence"', encoding="utf-8"
            )
            (root / "apps/api/tests/test_sequence_tools_error_codes.py").write_text(
                "# derived from errors.rs\n", encoding="utf-8"
            )
            found = self.guard.check(root)
        self.assertTrue(found, "the full drift set must not be green")


if __name__ == "__main__":
    unittest.main()
