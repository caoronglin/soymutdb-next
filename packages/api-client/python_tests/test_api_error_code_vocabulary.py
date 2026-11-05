"""The public API error-code vocabulary is a contract, not a derived echo.

``scripts/check_api_error_code_vocabulary.py`` binds the published catalog to
a hand-written lock file. This suite proves the guard is load-bearing: a rename
that moves ``exceptions.py`` and every co-derived consumer together must still
turn a gate red, because the lock is not one of the generated artifacts.

Reads committed bytes only -- no API import, no 3.15 venv, no wheel, no PG --
and uses stdlib ``unittest`` so it runs on a bare interpreter. The frontend
contract gate collects this directory via ``check-contract.sh``.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
GUARD_PATH = ROOT / "scripts" / "check_api_error_code_vocabulary.py"
GOLDEN = ROOT / "packages" / "api-client" / "error-codes.golden.json"
CATALOG = ROOT / "packages" / "api-client" / "error-codes.json"
OPENAPI = ROOT / "packages" / "api-client" / "openapi.json"
EXCEPTIONS = ROOT / "apps" / "api" / "app" / "core" / "exceptions.py"
GENERATOR = ROOT / "packages" / "api-client" / "scripts" / "generate-api-client.sh"
EXPORT = ROOT / "packages" / "api-client" / "scripts" / "export_contract.py"

FILES = (GOLDEN, CATALOG, OPENAPI, EXCEPTIONS, GENERATOR, EXPORT)


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("api_error_code_vocabulary", GUARD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ApiErrorVocabularyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.guard = _load_guard()

    def _tree(self, root: Path) -> Path:
        tree = root / "repo"
        for rel in FILES:
            dest = tree / rel.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(rel.read_bytes())
        return tree

    def test_clean_tree_has_no_golden_drift(self) -> None:
        self.assertEqual(self.guard.check(ROOT), [])

    def test_guard_self_test_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # _self_test() reads ROOT's own files; it is exercised directly in CI
            # via --self-test, here we assert its return contract on a clean tree.
            self.assertEqual(self.guard._self_test(), 0)

    def test_lock_file_is_hand_written_not_generated(self) -> None:
        self.assertTrue(GOLDEN.is_file())
        for generator in (GENERATOR, EXPORT):
            self.assertNotIn(GOLDEN.name, generator.read_text(encoding="utf-8"))

    def test_every_declared_code_is_frozen(self) -> None:
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(set(golden), self.guard.source_codes(ROOT))

    def test_coordinated_rename_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tree = self._tree(Path(tmp))
            old, new = "settings_version_conflict", "settings_version_conflictx"
            p = tree / EXCEPTIONS.relative_to(ROOT)
            p.write_text(p.read_text().replace(f'error_code = "{old}"', f'error_code = "{new}"'))
            p = tree / CATALOG.relative_to(ROOT)
            d = json.loads(p.read_text()); d[new] = d.pop(old)
            p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
            p = tree / OPENAPI.relative_to(ROOT)
            d = json.loads(p.read_text()); d["x-error-codes"][new] = d["x-error-codes"].pop(old)
            p.write_text(json.dumps(d, indent=2) + "\n")
            problems = self.guard.check(tree)
            self.assertTrue(any("lock does not freeze" in p for p in problems))
            self.assertTrue(any("breaking contract change" in p for p in problems))

    def test_rename_in_all_three_generated_artifacts_still_fails(self) -> None:
        """Even a full regenerate cannot update the hand-written lock."""
        with tempfile.TemporaryDirectory() as tmp:
            tree = self._tree(Path(tmp))
            old, new = "plugin_disabled", "plugin_disabledx"
            for rel in (EXCEPTIONS, CATALOG, OPENAPI):
                p = tree / rel.relative_to(ROOT)
                if rel == EXCEPTIONS:
                    p.write_text(p.read_text().replace(f'error_code = "{old}"', f'error_code = "{new}"'))
                else:
                    d = json.loads(p.read_text())
                    target = d if rel == CATALOG else d["x-error-codes"]
                    target[new] = target.pop(old)
                    p.write_text(json.dumps(d, indent=2, sort_keys=(rel == CATALOG)) + "\n")
            self.assertNotEqual(self.guard.check(tree), [])

    def test_a_weakened_guard_is_detected(self) -> None:
        """Deleting the lock's content must fail, not silently pass."""
        with tempfile.TemporaryDirectory() as tmp:
            tree = self._tree(Path(tmp))
            (tree / GOLDEN.relative_to(ROOT)).write_text("{}\n")
            self.assertNotEqual(self.guard.check(tree), [])


if __name__ == "__main__":
    unittest.main()
