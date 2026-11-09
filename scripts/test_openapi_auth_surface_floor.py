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

The second half covers ``_SECURITY_PROJECTION_DIGEST``: the *whole* 276-row
projection, not the 50-row floor. The generated client drops ``security`` by
design, so no other guard can see a snapshot-only edit and no count-preserving
move between protected and public moves any count at all. These tests pin the
literal, the count doors, and the non-duplication with the neighbouring
guards so a later change cannot quietly retarget this pin onto a surface
``NON_ADMIN_PROTECTED`` or the response-surface guard already owns.
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
        self.assertEqual(len(guard.NON_ADMIN_PROTECTED), 50)
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


class SecurityProjectionPinTests(unittest.TestCase):
    """The 276-row projection pin, its count doors and its non-duplication."""

    def test_clean_snapshot_passes(self):
        self.assertEqual(guard.failures(*_base()), [])

    def test_the_digest_is_an_independent_literal(self):
        src = GUARD_PATH.read_text(encoding="utf-8")
        self.assertIn("_SECURITY_PROJECTION_DIGEST = (", src)
        block = src.split("_SECURITY_PROJECTION_DIGEST = (", 1)[1].split(")", 1)[0]
        literal = block.strip().strip('"')
        self.assertEqual(len(literal), 64)
        # Not derived: the guard must not compute the pinned value from the
        # snapshot it checks.
        self.assertNotIn("_SECURITY_PROJECTION_DIGEST = _projection_digest", src)

    def test_the_literal_matches_the_committed_bytes(self):
        """A re-pin must move the literal, not the measurement."""
        doc = json.loads(_base()[0])
        self.assertEqual(
            guard._projection_digest(guard._projection_rows(doc)),
            guard._SECURITY_PROJECTION_DIGEST,
        )

    def test_dropping_the_whole_projection_is_named_by_the_digest(self):
        """Every count, operationId and response survives; only the pin moves."""

        def drop_all(doc):
            for item in doc["paths"].values():
                if not isinstance(item, dict):
                    continue
                for method, op in item.items():
                    if method in guard.METHODS and isinstance(op, dict):
                        op.pop("security", None)

        before = len(json.loads(_base()[0])["paths"])
        mutant = _mutate_snapshot(_base(), drop_all)
        self.assertEqual(len(json.loads(mutant[0])["paths"]), before)
        failures = guard.failures(*mutant)
        self.assertTrue(
            any("security projection drifted" in f for f in failures), failures
        )
        self.assertTrue(any("_EXPECTED_PROJECTED" in f for f in failures), failures)
        self.assertTrue(any("_EXPECTED_HIDDEN_OPS" in f for f in failures), failures)

    def test_a_count_preserving_move_is_caught_only_by_the_digest(self):
        """One leaf leaves the protected set, another enters: counts do not move."""
        doc = json.loads(_base()[0])
        admin = sorted(
            (p, m)
            for p, m, o in guard._operations(doc)
            if p.startswith("/api/v1/admin/")
        )
        public = sorted(
            (p, m)
            for p, m, o in guard._operations(doc)
            if not guard._bearer(o)
            and (p, m) not in guard.PUBLIC_AUTH
            and not p.startswith("/api/v1/")
        )
        self.assertTrue(admin and public, "setup is not a control")
        doc["paths"][admin[0][0]][admin[0][1]].pop("security", None)
        doc["paths"][public[0][0]][public[0][1]]["security"] = [{"HTTPBearer": []}]
        failures = guard.failures(json.dumps(doc), *_base()[1:])
        self.assertTrue(
            any("security projection drifted" in f for f in failures), failures
        )
        # The count doors must stay silent: this is a permutation, not a resized
        # surface, and conflating the two would make the pin a count check.
        self.assertFalse(any("_EXPECTED_PROJECTED" in f for f in failures), failures)
        self.assertFalse(any("_EXPECTED_HIDDEN_OPS" in f for f in failures), failures)

    def test_the_count_doors_hold_on_the_committed_bytes(self):
        doc = json.loads(_base()[0])
        rows = guard._projection_rows(doc)
        projected = sum(1 for row in rows if row[3] == "True")
        self.assertEqual(projected, guard._EXPECTED_PROJECTED)
        self.assertEqual(len(rows) - projected, guard._EXPECTED_HIDDEN_OPS)
        self.assertEqual(len(rows), guard._EXPECTED_PROJECTED + guard._EXPECTED_HIDDEN_OPS)

    def test_the_floor_only_covers_non_admin_protected_operations(self):
        """The two pins must not converge: the floor is 50 rows, the pin is 276."""
        self.assertEqual(len(guard.NON_ADMIN_PROTECTED), 50)
        self.assertEqual(guard._EXPECTED_PROJECTED, 178)
        self.assertEqual(guard._EXPECTED_HIDDEN_OPS, 98)
        doc = json.loads(_base()[0])
        rows = guard._projection_rows(doc)
        admin_rows = [row for row in rows if row[1].startswith("/api/v1/admin/")]
        # 128 admin + 50 reviewed non-admin = the 178 published requirements.
        self.assertEqual(len(admin_rows) + 50, guard._EXPECTED_PROJECTED)

    def test_the_pin_does_not_duplicate_the_response_surface_guard(self):
        """The response-surface guard walks operations and never reads security."""
        src = (ROOT / "scripts" / "check_openapi_response_surface.py").read_text(
            encoding="utf-8"
        )
        for field in ('"security"', "'security'", "get(\"security\")"):
            self.assertNotIn(
                field,
                src,
                "the response-surface guard now reads security: retarget this pin "
                "or state why the two surfaces are still distinct",
            )

    def test_the_pin_does_not_duplicate_the_behavior_contracts_suite(self):
        """That suite reads x-idempotent / x-pagination / 429 / 500, not this."""
        src = (ROOT / "scripts" / "test_openapi_behavior_contracts.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("x-idempotent", src)
        self.assertIn("_PAGINATION_BASELINE", src)
        self.assertNotIn('operation["security"]', src)
        self.assertNotIn("_bearer(", src)

    def test_self_test_lists_the_projection_ablations(self):
        src = GUARD_PATH.read_text(encoding="utf-8")
        for kind in ("drop_all_security", "move_one_protected_operation"):
            self.assertIn(f'"{kind}"', src)


class SecurityRequirementPinTests(unittest.TestCase):
    """The published ``security`` requirement *content*, pinned independently.

    The projection digest collapses each requirement to a boolean, ``_bearer()``
    reads only the scheme name, and ``NON_ADMIN_PROTECTED`` pins a 50-row floor.
    A scope injection, an OR-alternative, or a same-count scope rotation changes
    the published contract while all of them stay silent. ``openapi-typescript``
    drops ``security`` entirely, so there is no generated half to disagree.
    """

    def test_the_literals_are_module_level_and_pinned(self):
        src = GUARD_PATH.read_text(encoding="utf-8")
        for needle in (
            "_SECURITY_REQUIREMENT_DIGEST = (",
            "actual_requirement != _SECURITY_REQUIREMENT_DIGEST",
            "_EXPECTED_SECURITY_REQUIREMENT_ROWS",
            "_EXPECTED_PROTECTED_REQUIREMENTS",
            "_requirement_digest(requirement_rows)",
        ):
            self.assertIn(needle, src)
        self.assertEqual(guard._EXPECTED_SECURITY_REQUIREMENT_ROWS, 276)
        self.assertEqual(guard._EXPECTED_PROTECTED_REQUIREMENTS, 178)

    def test_the_digest_is_recomputed_from_committed_bytes(self):
        document, _, _, _, _ = _base()
        rows = guard._requirement_rows(json.loads(document))
        self.assertEqual(len(rows), 276)
        self.assertEqual(
            guard._requirement_digest(rows), guard._SECURITY_REQUIREMENT_DIGEST
        )

    def test_a_scope_injection_is_named_by_the_content_door(self):
        document, _, _, _, _ = _base()
        doc = json.loads(document)
        doc["paths"]["/api/v1/admin/seed-requests"]["get"]["security"] = [
            {"HTTPBearer": ["release:read"]}
        ]
        found = guard.failures(json.dumps(doc), *_base()[1:])
        self.assertTrue(
            any("_SECURITY_REQUIREMENT_DIGEST" in f for f in found), found
        )
        self.assertFalse(
            any("security projection drifted" in f for f in found), found
        )

    def test_an_or_alternative_is_named_by_the_content_door(self):
        doc = json.loads(_base()[0])
        doc["paths"]["/api/v1/admin/seed-requests"]["get"]["security"] = [
            {"HTTPBearer": []},
            {"refreshCookie": []},
        ]
        found = guard.failures(json.dumps(doc), *_base()[1:])
        self.assertTrue(
            any("_SECURITY_REQUIREMENT_DIGEST" in f for f in found), found
        )

    def test_the_boolean_projection_stays_silent_on_a_scope_change(self):
        """Positive control: only the content door owns this drift."""
        clean_rows = guard._projection_rows(json.loads(_base()[0]))
        doc = json.loads(_base()[0])
        doc["paths"]["/api/v1/admin/seed-requests"]["get"]["security"] = [
            {"HTTPBearer": ["release:read"]}
        ]
        drifted_rows = guard._projection_rows(doc)
        self.assertEqual(clean_rows, drifted_rows)

    def test_a_same_count_scope_rotation_is_rejected(self):
        doc = json.loads(_base()[0])
        doc["paths"]["/api/v1/admin/seed-requests"]["get"]["security"] = [
            {"HTTPBearer": ["release:read"]}
        ]
        doc["paths"]["/api/v1/admin/features"]["get"]["security"] = [
            {"HTTPBearer": ["seed:read"]}
        ]
        found = guard.failures(json.dumps(doc), *_base()[1:])
        self.assertTrue(
            any("_SECURITY_REQUIREMENT_DIGEST" in f for f in found), found
        )
        self.assertFalse(
            any("security-requirement row" in f for f in found), found
        )

    def test_the_self_test_lists_the_content_ablations(self):
        src = GUARD_PATH.read_text(encoding="utf-8")
        for kind in (
            "inject_scope",
            "or_alternative",
            "same_count_scope_rotation",
            "drop_one_requirement_content",
        ):
            self.assertIn(f'"{kind}"', src)


class SecuritySchemeDescriptionPinTests(unittest.TestCase):
    """The two published securityScheme descriptions, pinned independently.

    openapi-typescript drops ``securitySchemes`` entirely, so this surface has
    no generated half. These tests pin the literal, the count door, the source
    cross-check and the non-duplication with the scheme-shape check 1.
    """

    def test_clean_snapshot_passes(self):
        self.assertEqual(guard.failures(*_base()), [])

    def test_the_digest_is_an_independent_literal(self):
        src = GUARD_PATH.read_text(encoding="utf-8")
        self.assertIn("_SECURITY_SCHEME_DESCRIPTION_DIGEST = (", src)
        block = src.split("_SECURITY_SCHEME_DESCRIPTION_DIGEST = (", 1)[1].split(
            ")", 1
        )[0]
        literal = block.strip().strip('"')
        self.assertEqual(len(literal), 64)
        self.assertNotIn(
            "_SECURITY_SCHEME_DESCRIPTION_DIGEST = _scheme_description_digest", src
        )

    def test_the_literal_matches_the_committed_bytes(self):
        doc = json.loads(_base()[0])
        self.assertEqual(
            guard._scheme_description_digest(
                guard._scheme_description_rows(doc)
            ),
            guard._SECURITY_SCHEME_DESCRIPTION_DIGEST,
        )
        self.assertEqual(
            len(guard._scheme_description_rows(doc)),
            guard._EXPECTED_SECURITY_SCHEME_DESCRIPTIONS,
        )

    def test_a_single_byte_rewrite_is_caught_and_names_the_digest(self):
        def drift(doc):
            schemes = doc["components"]["securitySchemes"]
            schemes["HTTPBearer"]["description"] = schemes["HTTPBearer"][
                "description"
            ].replace("JWT access token", "JWT access tokeX")

        failures = guard.failures(*_mutate_snapshot(_base(), drift))
        self.assertTrue(
            any("securityScheme descriptions drifted" in f for f in failures),
            failures,
        )
        self.assertTrue(
            any("_SECURITY_SCHEME_DESCRIPTION_DIGEST" in f for f in failures),
            failures,
        )

    def test_a_same_count_rotation_is_caught_only_by_the_digest(self):
        """Swapping the two prose values moves neither count nor shape check."""

        def swap(doc):
            schemes = doc["components"]["securitySchemes"]
            bearer = schemes["HTTPBearer"]["description"]
            schemes["HTTPBearer"]["description"] = schemes["refreshCookie"][
                "description"
            ]
            schemes["refreshCookie"]["description"] = bearer

        failures = guard.failures(*_mutate_snapshot(_base(), swap))
        self.assertTrue(
            any("securityScheme descriptions drifted" in f for f in failures),
            failures,
        )
        self.assertFalse(
            any("_EXPECTED_SECURITY_SCHEME_DESCRIPTIONS" in f for f in failures),
            failures,
        )

    def test_dropping_a_description_is_named_by_the_count_door(self):
        def drop(doc):
            doc["components"]["securitySchemes"]["HTTPBearer"].pop("description")

        failures = guard.failures(*_mutate_snapshot(_base(), drop))
        self.assertTrue(
            any("_EXPECTED_SECURITY_SCHEME_DESCRIPTIONS" in f for f in failures),
            failures,
        )

    def test_the_source_literals_are_pinned(self):
        base = _base()
        src = base[1].replace(
            '"JWT access token. Obtain one via POST /api/v1/auth/login "',
            '"JWT access tokeX. Obtain one via POST /api/v1/auth/login "',
        )
        failures = guard.failures(base[0], src, *base[2:])
        self.assertTrue(
            any("reviewed securityScheme description literal" in f for f in failures),
            failures,
        )

    def test_the_co_revert_is_caught_by_both_doors(self):
        """Snapshot + source drift together, with no generated half to disagree."""
        base = _base()
        doc = json.loads(base[0])
        doc["components"]["securitySchemes"]["HTTPBearer"]["description"] = doc[
            "components"
        ]["securitySchemes"]["HTTPBearer"]["description"].replace(
            "JWT access token", "JWT access tokeX"
        )
        src = base[1].replace(
            '"JWT access token. Obtain one via POST /api/v1/auth/login "',
            '"JWT access tokeX. Obtain one via POST /api/v1/auth/login "',
        )
        failures = guard.failures(json.dumps(doc), src, *base[2:])
        self.assertTrue(
            any("securityScheme descriptions drifted" in f for f in failures),
            failures,
        )
        self.assertTrue(
            any("reviewed securityScheme description literal" in f for f in failures),
            failures,
        )

    def test_the_shape_check_still_does_not_read_descriptions(self):
        """Check 1 pins type/scheme/name; the new door owns the prose."""
        src = GUARD_PATH.read_text(encoding="utf-8")
        self.assertIn('_SCHEME_DESCRIPTION_LITERALS = (', src)
        self.assertEqual(len(guard._SCHEME_DESCRIPTION_LITERALS), 2)
        self.assertIn('bearer.get("scheme")', src)

    def test_self_test_lists_the_scheme_description_ablations(self):
        src = GUARD_PATH.read_text(encoding="utf-8")
        for kind in (
            "drift_bearer_description",
            "drift_cookie_description",
            "swap_scheme_descriptions",
            "drop_scheme_description",
            "co_revert_scheme_description_source",
        ):
            self.assertIn(f'"{kind}"', src)


class ExtensionKeySetSecondDoorTests(unittest.TestCase):
    """Second-file assertion that the behavior suite still owns its x-* pin.

    A single-file edit to ``test_openapi_behavior_contracts.py`` must not be
    able to delete the independent literal and both count doors. This suite is
    collected by the same contracts layer and reads the guarded file's bytes.
    """

    BEHAVIOR = ROOT / "scripts" / "test_openapi_behavior_contracts.py"

    def test_the_independent_literal_and_all_doors_are_still_in_source(self):
        src = self.BEHAVIOR.read_text(encoding="utf-8")
        for needle in (
            "_EXTENSION_SURFACE_DIGEST = (",
            "actual != _EXTENSION_SURFACE_DIGEST",
            "_EXPECTED_OPERATION_EXTENSION_ROWS",
            "_EXPECTED_EXTENSION_KEYS",
            "_EXPECTED_TOP_EXTENSION_KEYS",
            "found.extend(_extension_key_errors(document))",
        ):
            self.assertIn(needle, src)

    def test_a_phantom_extension_is_rejected_by_the_committed_suite(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "behavior_contracts_second_door", self.BEHAVIOR
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        document, generated, main, smoke = module._load()
        assert not module._extension_key_errors(document)
        key = next(k for k in sorted(module._operations(document)))
        document["paths"][key[0]][key[1]]["x-audit-anchor"] = "reviewed"
        found = module._extension_key_errors(document)
        self.assertTrue(any("_EXTENSION_SURFACE_DIGEST" in f for f in found), found)
        self.assertTrue(
            any("_EXPECTED_OPERATION_EXTENSION_ROWS" in f for f in found), found
        )


if __name__ == "__main__":
    unittest.main()
