"""Regression coverage for the contracts-layer registry/collection guard.

The guard itself is stdlib-only and runs before pytest is guaranteed. These
tests are collected by the contracts layer (and by a plain pytest run over
scripts/) and prove the guard's failure directions on synthetic input,
without depending on the real tree's exact suite count.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "scripts" / "check_contracts_registry_collection.py"

spec = importlib.util.spec_from_file_location(
    "check_contracts_registry_collection", GUARD_PATH
)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

REQUIRED = sorted(guard.REQUIRED_GUARD_CALLS)


def _smoke(entries: list[str], calls: list[str]) -> str:
    lines = ["smoke_contracts() {", "  local tests=("]
    lines += [f"    {e}" for e in entries]
    lines.append("  )")
    for call in calls:
        lines.append('  "${PYTHON_BIN}" ' + call + ' || rc=$?')
    lines.append('  "${PYTHON_BIN}" -m pytest "${tests[@]}" -q || rc=$?')
    lines += ["}", ""]
    return "\n".join(lines)


def _files() -> dict[str, str]:
    return {c: "# guard\n" for c in REQUIRED}


class RegistryCollectionGuardTests(unittest.TestCase):
    def test_clean_registry_passes(self) -> None:
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        self.assertEqual(guard.check(smoke, files), [])

    def test_phantom_entry_is_caught(self) -> None:
        smoke = _smoke(
            ["scripts/test_example.py", "scripts/test_phantom.py"], REQUIRED
        )
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        files["scripts/test_phantom.py"] = "def helper():\n    return 1\n"
        failures = guard.check(smoke, files)
        self.assertTrue(any("no collectible test" in f for f in failures), failures)

    def test_missing_registry_file_is_caught(self) -> None:
        smoke = _smoke(["scripts/test_gone.py"], REQUIRED)
        failures = guard.check(smoke, _files())
        self.assertTrue(any("does not exist" in f for f in failures), failures)

    def test_duplicate_entry_is_caught(self) -> None:
        smoke = _smoke(
            ["scripts/test_example.py", "scripts/test_example.py"], REQUIRED
        )
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        failures = guard.check(smoke, files)
        self.assertTrue(any("duplicate" in f for f in failures), failures)

    def test_dropped_guard_call_is_caught(self) -> None:
        smoke = _smoke(
            ["scripts/test_example.py"], ["scripts/check-toolchain-pins.py"]
        )
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        failures = guard.check(smoke, files)
        self.assertTrue(any("was dropped" in f for f in failures), failures)

    def test_guard_call_without_file_is_caught(self) -> None:
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        files.pop("scripts/check_nginx_security_headers.py")
        failures = guard.check(smoke, files)
        self.assertTrue(any("does not exist" in f for f in failures), failures)

    def test_driver_registry_failure_must_propagate(self) -> None:
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        body = _smoke(["scripts/test_example.py"], REQUIRED)
        prefix = (
            guard.DRIVER_MARKER
            + "\n"
            + '  "${PYTHON_BIN}" scripts/check_contracts_registry_collection.py '
        )
        suffix = "\n  run_layer contracts smoke_contracts\nfi\n\n"
        swallowed = guard.check(prefix + "|| rc=$?" + suffix + body, files)
        self.assertTrue(any("not propagated" in f for f in swallowed), swallowed)
        propagated = guard.check(
            prefix + '|| FAILED+=("contracts registry")' + suffix + body, files
        )
        self.assertEqual(propagated, [])

    def test_unittest_style_suite_counts_as_collectible(self) -> None:
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        files = _files()
        files["scripts/test_example.py"] = (
            "import unittest\n\nclass T(unittest.TestCase):\n"
            "    def test_case(self):\n        self.assertTrue(True)\n"
        )
        failures = guard.check(smoke, files)
        self.assertFalse(
            any("no collectible test" in f for f in failures), failures
        )


if __name__ == "__main__":
    unittest.main()
