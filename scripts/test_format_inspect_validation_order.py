"""Synthetic-tree proofs for the /inspect validation-order source guard.

Each negative must fail. The guard reads AST line numbers rather than importing
the API (which needs Python 3.15), so these ablations are cheap and honest.
"""
from pathlib import Path

import pytest

from scripts import check_format_inspect_validation_order as guard

GOOD_SERVICE = '''
async def inspect(payload):
    raw = _decode(payload.data)
    core = bridge.require()
    return core
'''

# The original bug: engine required before request validation.
ENGINE_FIRST = '''
async def inspect(payload):
    core = bridge.require()
    raw = _decode(payload.data)
    return core
'''

NO_DECODE = '''
async def inspect(payload):
    core = bridge.require()
    return core
'''

NO_REQUIRE = '''
async def inspect(payload):
    raw = _decode(payload.data)
    return raw
'''

GOOD_TEST = '''
async def test_malformed_base64_422_wins_over_missing_engine():
    def _unavailable():
        raise ServiceUnavailableError("engine down")
    assert exc.value.status_code == 422
'''


@pytest.fixture
def tree(tmp_path):
    return tmp_path


def put(tree: Path, name: str, text: str) -> Path:
    path = tree / name
    path.write_text(text, encoding="utf-8")
    return path


def run(tree: Path, service: str, test: str = GOOD_TEST) -> int:
    return guard.main([
        "--service-path", str(put(tree, "svc.py", service)),
        "--test-path", str(put(tree, "test.py", test)),
    ])


def test_current_contract_is_accepted(tree):
    assert run(tree, GOOD_SERVICE) == 0


def test_engine_before_validation_is_rejected(tree, capsys):
    assert run(tree, ENGINE_FIRST) == 1
    assert "before _decode()" in capsys.readouterr().err


def test_removing_validation_is_rejected(tree, capsys):
    assert run(tree, NO_DECODE) == 1
    assert "never calls _decode()" in capsys.readouterr().err


def test_removing_fail_closed_is_rejected(tree, capsys):
    assert run(tree, NO_REQUIRE) == 1
    assert "never calls bridge.require()" in capsys.readouterr().err


def test_regression_test_removed_is_rejected(tree, capsys):
    assert run(tree, GOOD_SERVICE, "async def test_other(): pass") == 1
    assert guard.REQUIRED_TEST in capsys.readouterr().err


def test_regression_test_loses_its_422_assertion_is_rejected(tree, capsys):
    short = "async def test_malformed_base64_422_wins_over_missing_engine(): pass"
    assert run(tree, GOOD_SERVICE, short) == 1
    assert "stub a missing engine and assert 422" in capsys.readouterr().err


def test_missing_source_file_is_rejected(tree, capsys):
    test = put(tree, "test.py", GOOD_TEST)
    assert guard.main([
        "--service-path", str(tree / "absent.py"),
        "--test-path", str(test),
    ]) == 1
    assert "missing" in capsys.readouterr().err


def test_guard_is_wired_into_the_contracts_layer():
    """A guard that only runs on branches that already have it is not a gate."""
    import re

    smoke = (guard.ROOT / "scripts/smoke.sh").read_text(encoding="utf-8")
    layer = smoke.split("smoke_contracts() {", 1)[1].split("\n}\n", 1)[0]
    assert "scripts/check_format_inspect_validation_order.py" in layer, (
        "the live-source guard is not invoked by smoke.sh contracts layer"
    )
    assert "scripts/test_format_inspect_validation_order.py" in layer, (
        "the ablation suite is not registered in smoke.sh contracts layer"
    )
    assert re.search(
        r"^\s+scripts/test_format_inspect_validation_order\.py\s*$", layer, re.MULTILINE
    ), "the ablation suite must be in the pytest suite array, not just a comment"
