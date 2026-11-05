"""Wiring tests for the sequence-tools endpoint source guard.

The guard only helps if something actually runs it. ``check-contract.sh`` is
the authoritative gate, so these tests pin what makes the guard live: the file
exists, the gate invokes it, a reverted source is rejected, and the guard's own
pin set has not been quietly shortened. Deleting one route from
``REQUIRED_ENDPOINTS`` is otherwise a one-line, green-CI change: the guard
still passes on the real router while no longer protecting that route.
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "check_sequence_tools_endpoints.py"
CONTRACT_SH = ROOT / "packages/api-client/scripts/check-contract.sh"
SOURCE = ROOT / "apps/api/app/api/v1/tools_sequence.py"

#: The published contract, pinned in a second file. If the list lived only in
#: the guard, deleting a line from REQUIRED_ENDPOINTS would also delete the only
#: record of what it should contain -- every assertion stayed green on exactly
#: that edit. Exact equality (not "at least") also catches a padded pin set.
PUBLISHED_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("get", "/capabilities"),
    ("post", "/reverse-complement"),
    ("post", "/match"),
    ("post", "/align"),
    ("post", "/stats"),
    ("post", "/orfs"),
    ("post", "/translate"),
    ("post", "/kmers"),
    ("post", "/inspect"),
)
RETIRED_PATHS: tuple[str, ...] = ("/statistics", "/intervals")
ROUTER_PREFIX = "/tools/sequence"

#: The pre-P2 8-endpoint router that PR #108 carried by accident.
REVERTED_SOURCE = '''
router = APIRouter(prefix="/tools/sequence", tags=["tools"])


@router.post("/reverse-complement")
async def reverse_complement(): ...


@router.post("/match")
async def sequence_match(): ...


@router.post("/align")
async def sequence_align(): ...


@router.post("/statistics")
async def sequence_stats(): ...


@router.post("/orfs")
async def sequence_orfs(): ...


@router.post("/translate")
async def sequence_translate(): ...


@router.post("/kmers")
async def sequence_kmers(): ...


@router.post("/intervals")
async def inspect_format(): ...
'''


def load_guard(path: Path = GUARD):
    spec = importlib.util.spec_from_file_location("sequence_tools_guard", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GuardWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.guard = load_guard()

    def test_guard_and_committed_source_exist(self) -> None:
        self.assertTrue(GUARD.is_file(), f"guard script is missing: {GUARD}")
        self.assertTrue(SOURCE.is_file(), f"sequence-tools router is missing: {SOURCE}")
        self.assertEqual(self.guard.inspect(SOURCE.read_text(encoding="utf-8")), [])

    def test_contract_gate_invokes_the_guard(self) -> None:
        script = CONTRACT_SH.read_text(encoding="utf-8")
        self.assertTrue(
            "scripts/check_sequence_tools_endpoints.py" in script,
            "check-contract.sh no longer invokes the sequence-tools endpoint guard",
        )
        self.assertTrue(
            '"$REPO_ROOT/scripts/test_check_sequence_tools_endpoints.py"' in script,
            "check-contract.sh no longer runs the guard's own wiring tests",
        )

    def test_reverted_eight_endpoint_source_is_rejected(self) -> None:
        failures = self.guard.inspect(REVERTED_SOURCE)
        self.assertTrue(failures, "the pre-P2 8-endpoint router must be rejected")
        joined = "\n".join(failures)
        for path in ("/capabilities", "/inspect", "/stats", "/statistics", "/intervals"):
            self.assertIn(path, joined)

    def test_guard_cli_rejects_reverted_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tools_sequence.py"
            path.write_text(REVERTED_SOURCE, encoding="utf-8")
            self.assertEqual(self.guard.main(["--source-path", str(path)]), 1)

    def test_self_test_passes(self) -> None:
        self.assertEqual(self.guard.self_test(), 0)

    def test_guard_pins_the_full_published_endpoint_set(self) -> None:
        """The pin is data too; weakening it must fail, not silently pass."""
        self.assertEqual(tuple(self.guard.REQUIRED_ENDPOINTS), PUBLISHED_ENDPOINTS)
        self.assertEqual(tuple(self.guard.RETIRED_PATHS), RETIRED_PATHS)
        self.assertEqual(self.guard.ROUTER_PREFIX, ROUTER_PREFIX)

    def test_shortening_the_pin_set_is_detectable(self) -> None:
        """Prove the equality above has teeth, using the exact reported edit."""
        original = GUARD.read_text(encoding="utf-8")
        pin_line = '    ("post", "/align"),\n'
        self.assertIn(pin_line, original, "the guard's /align pin line moved")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "weakened_guard.py"
            path.write_text(original.replace(pin_line, ""), encoding="utf-8")
            module = load_guard(path)
            self.assertNotEqual(tuple(module.REQUIRED_ENDPOINTS), PUBLISHED_ENDPOINTS)


if __name__ == "__main__":
    unittest.main()
