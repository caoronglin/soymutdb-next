#!/usr/bin/env python3
"""Second-file coverage for ``scripts/check_published_route_manifest.py``.

The guard pins the external build's ``routes.json`` and ``robots.txt`` to two
hand-written literals. Every assertion that proves the pins are load-bearing
would otherwise live in one file: an edit could weaken the digest comparison,
re-arm the literal to whatever the artifact happens to say, and keep the whole
contracts layer green while publishing a manifest nobody reviewed.

These cases are therefore written from outside the guard:

* the literals are module-level 64-character strings, read from nowhere;
* a same-count rotation is caught by the digest and **not** by the count doors
  (the decisive shape -- an identical route multiset, only the order moves);
* the emitted ``robots.txt`` is a pinned surface of its own, so reverting
  ``Allow: /`` to ``Disallow: /`` reddens the guard;
* the guard is wired into ``smoke.sh`` and into both registry floors, so
  dropping the call, the pin or the self-test fails here instead of shipping.

Stdlib only: collected by the contracts layer's ``tests=()`` array.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "check_published_route_manifest.py"
SMOKE = ROOT / "scripts" / "smoke.sh"
REGISTRY = ROOT / "scripts" / "check_contracts_registry_collection.py"
TEETH = ROOT / "scripts" / "check_contracts_self_test_teeth.py"

_spec = importlib.util.spec_from_file_location("check_published_route_manifest", GUARD)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

ROWS = (
    {"path": "/", "title": "Home", "description": None, "includeInSitemap": True},
    {"path": "/genes", "title": "Genes", "description": None, "includeInSitemap": True},
    {"path": "/login", "title": "Login", "description": None, "includeInSitemap": False},
)
ROBOTS = "User-agent: *\nAllow: /\nSitemap: https://soymutdb.invalid/sitemap.xml\n"
ORIGIN = "https://soymutdb.invalid"


def _tree(rows=ROWS, robots=ROBOTS, **overrides) -> Path:
    tmp = Path(tempfile.mkdtemp())
    external = tmp / "external"
    external.mkdir(parents=True)
    document = {"siteVariant": "external", "origin": ORIGIN, "entries": list(rows)}
    document.update(overrides)
    (external / "routes.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    (external / "robots.txt").write_text(robots, encoding="utf-8")
    return external


class LiteralIsIndependent(unittest.TestCase):
    def test_both_literals_are_module_level_hex_strings(self) -> None:
        for name in ("_MANIFEST_DIGEST", "_ROBOTS_DIGEST"):
            value = getattr(guard, name)
            self.assertIsInstance(value, str, f"{name} must be a literal, not derived")
            self.assertEqual(len(value), 64, name)
            int(value, 16)  # raises if it is not hex

    def test_the_literals_match_the_committed_artifact(self) -> None:
        """The reviewed pin and the committed bytes must agree on main."""
        self.assertEqual(guard.check(), [])

    def test_a_literal_derived_from_the_artifact_is_rejected_as_a_shape(self) -> None:
        """Re-deriving the pin would make it self-referential: the module text
        must not compute either literal from the file it audits."""
        source = GUARD.read_text(encoding="utf-8")
        self.assertNotIn("_MANIFEST_DIGEST = manifest_digest(", source)
        self.assertNotIn("_ROBOTS_DIGEST = robots_digest(", source)


class RotationIsTheDecisiveShape(unittest.TestCase):
    def _rotation(self) -> tuple[Path, list[str]]:
        rotated = [ROWS[1], ROWS[0], ROWS[2]]
        external = _tree(rows=rotated)
        problems = guard.check(
            external,
            manifest_literal=guard.manifest_digest({"entries": list(ROWS), "origin": ORIGIN}),
            robots_literal=guard.robots_digest(ROBOTS),
            expected_routes=len(ROWS),
            expected_indexable=2,
        )
        return external, problems

    def test_a_same_count_rotation_is_caught_by_the_digest_alone(self) -> None:
        external, problems = self._rotation()
        try:
            self.assertEqual(len(problems), 1, problems)
            self.assertIn("_MANIFEST_DIGEST", problems[0])
            # The count doors are identical on both sides, so nothing else may
            # claim the rotation -- otherwise the digest would be untested.
            self.assertNotIn("reviewed floor", problems[0])
        finally:
            shutil.rmtree(external.parent, ignore_errors=True)

    def test_the_crawl_policy_digest_is_a_separate_door(self) -> None:
        deindexed = "User-agent: *\nDisallow: /\n"
        external = _tree(robots=deindexed)
        try:
            problems = guard.check(
                external,
                manifest_literal=guard.manifest_digest({"entries": list(ROWS), "origin": ORIGIN}),
                robots_literal=guard.robots_digest(ROBOTS),
                expected_routes=len(ROWS),
                expected_indexable=2,
            )
        finally:
            shutil.rmtree(external.parent, ignore_errors=True)
        self.assertTrue(any("_ROBOTS_DIGEST" in problem for problem in problems), problems)

    def test_a_reviewed_repin_of_both_halves_is_green(self) -> None:
        """The legitimate action, not a whitelist: a re-pin of the reviewed
        value clears the digest door."""
        external = _tree(rows=[ROWS[1], ROWS[0], ROWS[2]])
        try:
            document, policy = guard._read(external)
            problems = guard.check(
                external,
                manifest_literal=guard.manifest_digest(document),
                robots_literal=guard.robots_digest(policy),
                expected_routes=3,
                expected_indexable=2,
            )
        finally:
            shutil.rmtree(external.parent, ignore_errors=True)
        self.assertEqual(problems, [])

    def test_an_unarmed_literal_is_reported(self) -> None:
        external = _tree()
        try:
            problems = guard.check(
                external,
                manifest_literal=None,
                robots_literal=guard.robots_digest(ROBOTS),
            )
        finally:
            shutil.rmtree(external.parent, ignore_errors=True)
        self.assertTrue(any("not armed" in problem for problem in problems), problems)


class SelfTestHasASignal(unittest.TestCase):
    def test_the_self_test_reports_its_cases_and_exits_zero(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = guard.main(["--self-test"])
        out = buffer.getvalue()
        self.assertEqual(rc, 0, out)
        emitted = [line for line in out.splitlines() if line.startswith("PASS self-test: ")]
        reported = [line for line in out.splitlines() if line.startswith("self-test: ")]
        self.assertEqual(len(reported), 1, out)
        self.assertEqual(reported[0], f"self-test: {len(emitted)} cases, 0 failure(s)")

    def test_a_gutted_self_test_would_be_caught_by_the_teeth_guard(self) -> None:
        """The teeth guard must have a plant for this guard, or a no-op
        ``self_test()`` would stay green in the contracts layer."""
        spec = importlib.util.spec_from_file_location("teeth", TEETH)
        assert spec and spec.loader
        teeth = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(teeth)
        self.assertIn("scripts/check_published_route_manifest.py", teeth._WIRED_SELF_TESTS)
        self.assertIn("scripts/check_published_route_manifest.py", teeth._DRIFT_COVERED)
        self.assertIn("scripts/check_published_route_manifest.py", teeth._GUT_COVERED)


class WiringIsPinned(unittest.TestCase):
    def test_the_layer_runs_both_forms(self) -> None:
        smoke = SMOKE.read_text(encoding="utf-8")
        body = smoke.split("smoke_contracts() {", 1)[1].split("\n}\n", 1)[0]
        self.assertIn(
            'scripts/check_published_route_manifest.py --self-test || rc=$?', body
        )
        self.assertIn("scripts/check_published_route_manifest.py || rc=$?", body)

    def test_both_registry_floors_carry_the_call(self) -> None:
        spec = importlib.util.spec_from_file_location("registry", REGISTRY)
        assert spec and spec.loader
        registry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(registry)
        self.assertIn(
            "scripts/check_published_route_manifest.py", registry.REQUIRED_GUARD_CALLS
        )


if __name__ == "__main__":
    unittest.main()
