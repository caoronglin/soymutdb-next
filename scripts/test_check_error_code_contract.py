#!/usr/bin/env python3
"""Wiring tests for the error-code contract guard.

The guard only helps if a gate actually runs it and if the published contract
it pins is the exact one the runtime emits. Deleting the gate invocation,
quietly shrinking the published code set, or flipping a published status away
from the hierarchy must fail here rather than pass a green CI by co-reverting
the snapshot and the generated client together.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "check_error_code_contract.py"
CONTRACT_SH = ROOT / "packages/api-client/scripts/check-contract.sh"
SMOKE = ROOT / "scripts" / "smoke.sh"
REGISTRY = ROOT / "scripts" / "check_contracts_registry_collection.py"
SNAPSHOT = ROOT / "packages/api-client/openapi.json"
CODES = ROOT / "packages/api-client/error-codes.json"
SOURCE = ROOT / "apps/api/app/core/exceptions.py"

_spec = importlib.util.spec_from_file_location("check_error_code_contract", GUARD)
assert _spec and _spec.loader
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

#: Pinned in a second file so deleting a catalog entry from the guard (or from
#: the runtime hierarchy) is caught by exact equality, not "at least".
PUBLISHED_CODES: tuple[str, ...] = (
    "authentication_failed",
    "conflict",
    "forbidden",
    "http_error",
    "internal_error",
    "not_found",
    "plugin_disabled",
    "plugin_unavailable",
    "rate_limit_exceeded",
    "service_unavailable",
    "settings_version_conflict",
    "task_dispatch_failed",
    "validation_error",
)


class TestErrorCodeContract(unittest.TestCase):
    def test_guard_exists_and_gate_invokes_it(self) -> None:
        self.assertTrue(GUARD.is_file())
        gate = CONTRACT_SH.read_text(encoding="utf-8")
        self.assertIn("scripts/check_error_code_contract.py", gate)

    def test_contracts_layer_invokes_it_too(self) -> None:
        """The guard must be consumed by the layer that runs on a clean checkout.

        It was called only from ``check-contract.sh``, which sits behind the
        frontend gate's API-venv export. Its two siblings were later wired into
        ``smoke.sh`` for exactly this reason and this one was left behind, so a
        coordinated source+snapshot+lock drift left the whole contracts layer
        green -- reproduced, not inferred: with the golden lock re-pinned to a
        renamed code, ``check_api_error_code_vocabulary.py`` and
        ``check_error_code_catalog.py`` both returned rc=0 while this guard
        returned rc=1 on the x-error-status binding.
        """
        contracts = SMOKE.read_text(encoding="utf-8")
        marker = "smoke_contracts() {"
        self.assertIn(marker, contracts, "smoke.sh no longer defines smoke_contracts()")
        body = contracts.split(marker, 1)[1].split("\n}\n", 1)[0]
        # Read the invocation, not a comment that mentions the path.
        invocations = [
            line
            for line in body.splitlines()
            if "scripts/check_error_code_contract.py" in line
            and "test_check_error_code_contract.py" not in line
            and not line.lstrip().startswith("#")
            and "--self-test" not in line
        ]
        self.assertTrue(
            invocations,
            "smoke_contracts() no longer invokes scripts/check_error_code_contract.py",
        )
        # Unconditionally, and with its status propagated: `|| :` / `2>/dev/null`
        # / a trailing pipe would keep the layer green while the guard failed.
        for line in invocations:
            self.assertIn("|| rc=$?", line, f"guard failure is swallowed: {line!r}")

    def test_contracts_layer_wiring_is_pinned_in_the_registry_floor(self) -> None:
        """A wired call the floor does not name can be dropped without a red.

        ``check_contracts_registry_collection.py`` fails closed on a wired call
        the floor omits; naming the guard here is what makes its removal a
        failure rather than a silent shrink of the layer.
        """
        registry = REGISTRY.read_text(encoding="utf-8")
        self.assertIn(
            '"scripts/check_error_code_contract.py"',
            registry,
            "check_error_code_contract.py is not pinned in REQUIRED_GUARD_CALLS",
        )

    def test_published_catalog_is_exact(self) -> None:
        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual(tuple(sorted(document["x-error-codes"])), PUBLISHED_CODES)

    def test_error_codes_json_matches_snapshot(self) -> None:
        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(CODES.read_text(encoding="utf-8")), document["x-error-codes"])

    def test_status_binding_matches_published_codes(self) -> None:
        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        status = document["x-error-status"]
        self.assertEqual(tuple(sorted(status["by_code"])), PUBLISHED_CODES)
        self.assertEqual(status["http_exception"]["fallback"], "http_error")
        self.assertIsNone(status["by_code"]["http_error"])

    def test_guard_passes_on_committed_bytes(self) -> None:
        self.assertEqual(module.check(SNAPSHOT, CODES, SOURCE), [])

    def test_guard_rejects_a_dropped_code(self) -> None:
        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        document["x-error-codes"].pop("http_error")
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "openapi.json"
            snap.write_text(json.dumps(document, indent=2), encoding="utf-8")
            self.assertTrue(module.check(snap, CODES, SOURCE))

    def test_guard_rejects_a_catalog_that_stops_emitting_a_code(self) -> None:
        """The snapshot keeping a code must not excuse the source dropping it.

        Deleting ``catalog[HTTP_ERROR_CODE] = ...`` leaves the ``HTTP_ERROR_CODE``
        constant in the file, so a literal scan still "sees" http_error and the
        published snapshot still lists it. Only executing ``error_code_catalog()``
        proves the two agree, and that is the function the snapshot is built from.
        """
        source = SOURCE.read_text(encoding="utf-8")
        trimmed = source.replace(module._FALLBACK_CATALOG_ENTRY, "")
        self.assertNotEqual(trimmed, source, "fixture no longer matches exceptions.py")

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "exceptions.py"
            source_path.write_text(trimmed, encoding="utf-8")
            self.assertTrue(module.check(SNAPSHOT, CODES, source_path))

    def test_executed_catalog_matches_the_published_one(self) -> None:
        executed, why = module._executed_contract(SOURCE)
        self.assertIsNone(why)
        self.assertIsNotNone(executed)
        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual(sorted(executed["catalog"]), sorted(document["x-error-codes"]))

    def test_executed_status_binding_matches_the_published_one(self) -> None:
        executed, why = module._executed_contract(SOURCE)
        self.assertIsNone(why)
        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        status = document["x-error-status"]
        self.assertEqual(executed["by_code"], status["by_code"])
        self.assertEqual(executed["http_exception"], status["http_exception"])

    def test_guard_rejects_a_status_drift_from_the_hierarchy(self) -> None:
        """A status flipped in the snapshot must fail even if the source is intact.

        The executed contract functions are the only stdlib oracle for the
        code -> status values; a key-only comparison would let this drift pass.
        """
        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        document["x-error-status"]["by_code"]["not_found"] = 409
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "openapi.json"
            snap.write_text(json.dumps(document, indent=2), encoding="utf-8")
            self.assertTrue(module.check(snap, CODES, SOURCE))

    def test_by_code_digest_is_an_independent_literal(self) -> None:
        """A second file pins the new literal; it must not be self-referential."""
        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        by_code = document["x-error-status"]["by_code"]
        self.assertEqual(module._by_code_digest(by_code), module._BY_CODE_DIGEST)
        self.assertEqual(len(by_code), module._EXPECTED_BY_CODE_ROWS)

    def test_http_exception_digest_is_an_independent_literal(self) -> None:
        """The sibling half is pinned from a second file, not derived from itself."""
        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        hx = document["x-error-status"]["http_exception"]
        self.assertEqual(
            module._status_digest("soymutdb-error-status-http-exception/v1", hx),
            module._HTTP_EXCEPTION_DIGEST,
        )
        self.assertEqual(len(hx), module._EXPECTED_HTTP_EXCEPTION_ROWS)

    def _single_code_co_revert(self):
        import tempfile

        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        document["x-error-status"]["by_code"]["forbidden"] = 409
        source = SOURCE.read_text(encoding="utf-8")
        flipped = source.replace(
            "class AuthorizationError(SoyMutDBError):\n"
            "    status_code = status.HTTP_403_FORBIDDEN",
            "class AuthorizationError(SoyMutDBError):\n"
            "    status_code = status.HTTP_409_CONFLICT",
            1,
        )
        self.assertNotEqual(flipped, source, "fixture no longer matches exceptions.py")
        tmp = tempfile.TemporaryDirectory()
        snap = Path(tmp.name) / "openapi.json"
        src = Path(tmp.name) / "exceptions.py"
        snap.write_text(json.dumps(document, indent=2), encoding="utf-8")
        src.write_text(flipped, encoding="utf-8")
        return tmp, snap, src, document

    def test_a_single_code_status_co_revert_is_rejected(self) -> None:
        """The decisive shape: source and snapshot agree, nothing else moves.

        Flipping one exception's ``status_code`` and its published ``by_code``
        binding together keeps every equality check in ``check()`` true. Only
        the independent literal can object. The guard's own ``--self-test``
        has a co-revert case, but it flips ``NotFoundError`` (which also moves
        ``plugin_disabled``); this one is the single-code bypass.
        """
        tmp, snap, src, _ = self._single_code_co_revert()
        with tmp:
            problems = module.check(snap, CODES, src)
            self.assertTrue(
                any("_BY_CODE_DIGEST" in problem for problem in problems),
                problems,
            )

    def test_the_literal_alone_catches_the_co_revert(self) -> None:
        """With every other door silenced by agreement, the digest still fires."""
        tmp, snap, src, document = self._single_code_co_revert()
        with tmp:
            executed, why = module._executed_contract(src)
            self.assertIsNone(why)
            self.assertEqual(executed["by_code"], document["x-error-status"]["by_code"])
            problems = module.check(snap, CODES, src)
            self.assertEqual(len(problems), 1, problems)
            self.assertIn("_BY_CODE_DIGEST", problems[0])

    def test_a_same_count_by_code_rotation_is_rejected(self) -> None:
        """Counts and key set unchanged; only the positional digest moves."""
        import tempfile

        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        by_code = document["x-error-status"]["by_code"]
        by_code["forbidden"], by_code["conflict"] = (
            by_code["conflict"],
            by_code["forbidden"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "openapi.json"
            snap.write_text(json.dumps(document, indent=2), encoding="utf-8")
            problems = module.check(snap, CODES, SOURCE)
            self.assertTrue(
                any("_BY_CODE_DIGEST" in problem for problem in problems),
                problems,
            )

    def test_the_count_door_is_load_bearing(self) -> None:
        import tempfile

        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        document["x-error-status"]["by_code"]["rogue"] = 418
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "openapi.json"
            snap.write_text(json.dumps(document, indent=2), encoding="utf-8")
            problems = module.check(snap, CODES, SOURCE)
            self.assertTrue(
                any("_EXPECTED_BY_CODE_ROWS" in p for p in problems), problems
            )

    def test_guard_source_still_carries_the_single_code_plant(self) -> None:
        """A second file pins the plant, so a single-file edit cannot drop it."""
        source = GUARD.read_text(encoding="utf-8")
        self.assertIn("_BY_CODE_DIGEST = ", source)
        self.assertIn("single-code status co-revert in source and snapshot", source)

    def _extra_http_exception_co_revert(self):
        """Source literal and snapshot gain the same fourth binding together."""
        import tempfile

        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        document["x-error-status"]["http_exception"]["429"] = "rate_limit_exceeded"
        source = SOURCE.read_text(encoding="utf-8")
        extra = source.replace(
            '    status.HTTP_404_NOT_FOUND: "not_found",\n}',
            '    status.HTTP_404_NOT_FOUND: "not_found",\n'
            '    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limit_exceeded",\n}',
            1,
        )
        self.assertNotEqual(extra, source, "fixture no longer matches exceptions.py")
        tmp = tempfile.TemporaryDirectory()
        snap = Path(tmp.name) / "openapi.json"
        src = Path(tmp.name) / "exceptions.py"
        snap.write_text(json.dumps(document, indent=2), encoding="utf-8")
        src.write_text(extra, encoding="utf-8")
        return tmp, snap, src, document

    def test_a_co_reverted_extra_http_exception_row_is_rejected(self) -> None:
        """Decisive shape: both halves agree, every value pin stays satisfied."""
        tmp, snap, src, document = self._extra_http_exception_co_revert()
        with tmp:
            executed, why = module._executed_contract(src)
            self.assertIsNone(why)
            self.assertEqual(
                executed["http_exception"], document["x-error-status"]["http_exception"]
            )
            problems = module.check(snap, CODES, src)
            self.assertTrue(
                any("_HTTP_EXCEPTION_DIGEST" in p for p in problems), problems
            )

    def test_the_co_revert_silences_equality_but_not_the_digest(self) -> None:
        """Positive control: both halves agree, yet the new doors still fire.

        With the extra row co-reverted, ``error_status_contract()`` returns the
        same map from the source as the snapshot publishes, so the executed
        equality is silent. The independent digest and the row-count door are
        the only witnesses -- exactly the resolution of failure reasons this
        pair of literals exists to preserve.
        """
        tmp, snap, src, document = self._extra_http_exception_co_revert()
        with tmp:
            executed, why = module._executed_contract(src)
            self.assertIsNone(why)
            self.assertEqual(
                executed["http_exception"], document["x-error-status"]["http_exception"]
            )
            problems = module.check(snap, CODES, src)
            self.assertEqual(len(problems), 2, problems)
            self.assertTrue(any("_HTTP_EXCEPTION_DIGEST" in p for p in problems), problems)
            self.assertTrue(
                any("_EXPECTED_HTTP_EXCEPTION_ROWS" in p for p in problems), problems
            )

    def test_a_same_count_http_exception_rotation_is_rejected(self) -> None:
        """Value pins and key set unchanged; only the positional digest moves."""
        import tempfile

        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        hx = document["x-error-status"]["http_exception"]
        hx["401"], hx["403"] = hx["403"], hx["401"]
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "openapi.json"
            snap.write_text(json.dumps(document, indent=2), encoding="utf-8")
            problems = module.check(snap, CODES, SOURCE)
            self.assertTrue(
                any("_HTTP_EXCEPTION_DIGEST" in p for p in problems), problems
            )

    def test_the_http_exception_count_door_is_load_bearing(self) -> None:
        import tempfile

        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        document["x-error-status"]["http_exception"]["418"] = "teapot"
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "openapi.json"
            snap.write_text(json.dumps(document, indent=2), encoding="utf-8")
            problems = module.check(snap, CODES, SOURCE)
            self.assertTrue(
                any("_EXPECTED_HTTP_EXCEPTION_ROWS" in p for p in problems), problems
            )

    def test_guard_source_still_carries_the_http_exception_plant(self) -> None:
        """A second file pins the co-revert plant; a single-file edit cannot drop it."""
        source = GUARD.read_text(encoding="utf-8")
        self.assertIn("_HTTP_EXCEPTION_DIGEST = ", source)
        self.assertIn(
            "co-reverted extra http_exception row in source and snapshot", source
        )

    def test_self_test_passes(self) -> None:
        self.assertEqual(module.self_test(), 0)


if __name__ == "__main__":
    unittest.main()
