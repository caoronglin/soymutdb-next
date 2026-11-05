"""Regression coverage for the OpenAPI auth-surface non-admin floor.

The guard is stdlib-only and runs before pytest is guaranteed (it is wired
into ``smoke.sh`` as a ``--self-test``). These tests exercise ``failures()``
on synthetic snapshots so the exact failure directions are pinned without
depending on a 3.15 venv, an API import, or the live app.

The decisive negative control: on the unmodified guard, stripping ``security``
from EVERY non-admin protected operation keeps ``protected == len(admin)`` and
the old ``protected < len(admin)`` bound green. The literal floor must turn
that co-revert red, and must stay a hand-written lock (not re-derived from the
snapshot it checks).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "scripts" / "check_openapi_auth_surface.py"

spec = importlib.util.spec_from_file_location(
    "check_openapi_auth_surface", GUARD_PATH
)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def _base():
    return guard._load()


def _mutate_snapshot(base, fn):
    doc = json.loads(base[0])
    fn(doc)
    return (json.dumps(doc),) + base[1:]


def _strip_all_non_admin(doc):
    for path, item in doc["paths"].items():
        if path.startswith("/api/v1/admin/"):
            continue
        for method, op in item.items():
            if method in guard.METHODS and isinstance(op, dict):
                op.pop("security", None)


class NonAdminProtectedFloorTests(unittest.TestCase):
    def test_clean_snapshot_passes(self):
        self.assertEqual(guard.failures(*_base()), [])

    def test_baseline_is_a_literal_not_derived_from_snapshot(self):
        """A floor re-computed from openapi.json would be self-referential."""
        self.assertIsInstance(guard.NON_ADMIN_PROTECTED, frozenset)
        self.assertEqual(len(guard.NON_ADMIN_PROTECTED), 48)
        # The guard must declare the set as source literals, not json.load it
        # from the very artifact it checks.
        src = GUARD_PATH.read_text(encoding="utf-8")
        self.assertIn("NON_ADMIN_PROTECTED = frozenset({", src)
        block = src.split("NON_ADMIN_PROTECTED = frozenset({", 1)[1].split(
            "})", 1
        )[0]
        self.assertEqual(
            block.count('    ("/api/v1/'), len(guard.NON_ADMIN_PROTECTED)
        )

    def test_strip_all_non_admin_security_is_caught(self):
        """The co-revert the old vacuous lower bound could never fire on."""
        mutant = _mutate_snapshot(_base(), _strip_all_non_admin)
        failures = guard.failures(*mutant)
        self.assertTrue(
            any("pinned non-admin operations" in f for f in failures),
            failures,
        )

    def test_dropping_one_non_admin_operation_is_caught(self):
        target = sorted(guard.NON_ADMIN_PROTECTED)[0]

        def drop_one(doc):
            doc["paths"][target[0]][target[1]].pop("security", None)

        failures = guard.failures(*_mutate_snapshot(_base(), drop_one))
        self.assertTrue(
            any("pinned non-admin operations" in f for f in failures),
            failures,
        )

    def test_phantom_non_admin_operation_is_caught(self):
        """An unreviewed addition must not silently widen the published surface."""

        def add_phantom(doc):
            doc["paths"]["/api/v1/assemblies"]["get"]["security"] = [
                {"HTTPBearer": []}
            ]

        failures = guard.failures(*_mutate_snapshot(_base(), add_phantom))
        self.assertTrue(
            any("not in the reviewed floor" in f for f in failures),
            failures,
        )

    def test_admin_surface_still_gated_independently(self):
        """Dropping admin security must still be caught by check 2, not check 3."""

        def drop_admin(doc):
            for path, item in doc["paths"].items():
                if path.startswith("/api/v1/admin/"):
                    for method, op in item.items():
                        if method in guard.METHODS and isinstance(op, dict):
                            op.pop("security", None)

        failures = guard.failures(*_mutate_snapshot(_base(), drop_admin))
        self.assertTrue(
            any("does not require HTTPBearer" in f for f in failures),
            failures,
        )

    def test_self_test_lists_the_co_revert_ablation(self):
        """The reported count must cover the new ablations, not a stale constant."""
        src = GUARD_PATH.read_text(encoding="utf-8")
        for kind in (
            "strip_non_admin_security",
            "drop_one_non_admin_security",
            "phantom_non_admin_security",
        ):
            self.assertIn(f'"{kind}"', src)


if __name__ == "__main__":
    unittest.main()
