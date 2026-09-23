"""Standard-library tests for the framework-neutral seam guard (Phase C)."""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts import check_framework_neutral_packages as checker

ROOT = Path(__file__).resolve().parents[1]


class FrameworkNeutralPackageTests(unittest.TestCase):
    def test_repo_seam_is_currently_clean(self) -> None:
        """The declared neutral packages must have zero framework imports now."""
        violations = checker.find_violations(ROOT)
        self.assertEqual(
            violations,
            [],
            "framework-neutral packages must not import react/vue/antd; "
            f"got {len(violations)} violation(s)",
        )

    def test_declared_packages_are_present(self) -> None:
        available = checker._package_dirs(ROOT / "packages")
        for name in checker.FRAMEWORK_NEUTRAL_PACKAGES:
            self.assertIn(name, available, f"{name} is declared but not present under packages/")

    def test_banned_classifier(self) -> None:
        for banned in (
            "react",
            "react-dom",
            "react-hook-form",
            "react-i18next",
            "antd",
            "@ant-design/icons",
            "@tanstack/react-query",
            "@tanstack/vue-query",
            "vue",
            "vue-router",
            "pinia",
            "echarts",
            "@vue/reactivity",
        ):
            self.assertTrue(checker.is_banned(banned), banned)
        for allowed in (
            "zod",
            "@soymutdb/shared",
            "i18next",
            "nanoid",
            "reactable",  # must not be caught by the "react-" style guard logic
            "vuesax-free",  # must not be caught by the "vue-" style guard logic
        ):
            self.assertFalse(
                checker.is_banned(allowed),
                f"{allowed} must not be treated as a framework import",
            )

    def test_self_test_guards_detection(self) -> None:
        # Must not raise; the checker asserts its own dirty/clean/missing cases.
        checker.self_test()


if __name__ == "__main__":
    unittest.main()
