"""Synthetic-tree proofs for the interval visibility-order source guard.

Each negative must fail. The guard reads AST line numbers rather than importing
the API (which needs Python 3.15), so these ablations are cheap and honest.
"""
from pathlib import Path

import pytest

from scripts import check_interval_visibility_order as guard

GOOD_SERVICE = '''
async def overlap(db, payload, release_context):
    assembly = await db.execute(select(Assembly))
    if assembly is None:
        raise NotFoundError("not published")
    chromosome = await db.execute(select(Chromosome))
    if chromosome is None:
        raise NotFoundError("not found")
    core = bridge.require()
    return core
'''

# The original bug: engine required before any visibility decision.
ENGINE_FIRST = '''
async def overlap(db, payload, release_context):
    core = bridge.require()
    assembly = await db.execute(select(Assembly))
    if assembly is None:
        raise NotFoundError("not published")
    chromosome = await db.execute(select(Chromosome))
    if chromosome is None:
        raise NotFoundError("not found")
    return core
'''

# Half-fixed: require() moved after the assembly check but still before the
# chromosome check. The chromosome 404 would still be masked by a 503.
BETWEEN_CHECKS = '''
async def overlap(db, payload, release_context):
    assembly = await db.execute(select(Assembly))
    if assembly is None:
        raise NotFoundError("not published")
    core = bridge.require()
    chromosome = await db.execute(select(Chromosome))
    if chromosome is None:
        raise NotFoundError("not found")
    return core
'''

NO_REQUIRE = '''
async def overlap(db, payload, release_context):
    assembly = await db.execute(select(Assembly))
    if assembly is None:
        raise NotFoundError("not published")
    chromosome = await db.execute(select(Chromosome))
    if chromosome is None:
        raise NotFoundError("not found")
    return []
'''

GOOD_TEST = '''
async def test_unpublished_assembly_404_wins_over_missing_engine():
    assert db.calls == 1
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


def test_engine_before_visibility_is_rejected(tree, capsys):
    assert run(tree, ENGINE_FIRST) == 1
    out = capsys.readouterr().err
    assert "before the first visibility decision" in out


def test_engine_between_the_two_checks_is_rejected(tree, capsys):
    assert run(tree, BETWEEN_CHECKS) == 1
    out = capsys.readouterr().err
    assert "after BOTH" in out
    assert "before the first visibility decision" not in out


def test_missing_require_is_rejected(tree, capsys):
    assert run(tree, NO_REQUIRE) == 1
    assert "never calls bridge.require()" in capsys.readouterr().err


def test_regression_test_removed_is_rejected(tree, capsys):
    assert run(tree, GOOD_SERVICE, "async def test_other(): pass") == 1
    assert guard.REQUIRED_TEST in capsys.readouterr().err


def test_regression_test_loses_its_ordering_assertion_is_rejected(tree, capsys):
    short = "async def test_unpublished_assembly_404_wins_over_missing_engine(): pass"
    assert run(tree, GOOD_SERVICE, short) == 1
    assert "DB lookup precedes" in capsys.readouterr().err


def test_missing_source_file_is_rejected(tree, capsys):
    test = put(tree, "test.py", GOOD_TEST)
    assert guard.main([
        "--service-path", str(tree / "absent.py"),
        "--test-path", str(test),
    ]) == 1
    assert "missing" in capsys.readouterr().err

def test_guard_is_wired_into_the_contracts_layer():
    """A guard that only runs on branches that already have it is not a gate.

    The contracts layer runs on both providers' PR pipelines, so the live
    source check and this ablation suite must both stay registered there.
    """
    import re

    smoke = (guard.ROOT / "scripts/smoke.sh").read_text(encoding="utf-8")
    layer = smoke.split("smoke_contracts() {", 1)[1].split("\n}\n", 1)[0]
    assert "scripts/check_interval_visibility_order.py" in layer, (
        "the live-source guard is not invoked by smoke.sh contracts layer"
    )
    assert "scripts/test_interval_visibility_order.py" in layer, (
        "the ablation suite is not registered in smoke.sh contracts layer"
    )
    assert re.search(
        r"^\s+scripts/test_interval_visibility_order\.py\s*$", layer, re.MULTILINE
    ), "the ablation suite must be in the pytest suite array, not just a comment"
