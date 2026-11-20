"""Guard the offline contract of real-binary BLAST fixtures.

NCBI tools contact a usage-report endpoint by default. The runner disables
that in its child environment; fixture-only ``makeblastdb`` calls must do the
same, otherwise opt-in integration runs hang on DNS until the test timeout.
This static guard runs without NCBI binaries so the default CI lane still
catches a regression.
"""
from __future__ import annotations

import ast
from pathlib import Path

import soymutdb_worker.ncbi_blast as runner

FIXTURE = Path(__file__).resolve().parent / "test_ncbi_blast_real.py"
REQUIRED = {
    "BLAST_USAGE_REPORT": "false",
    "NCBI_DONT_USE_NCBIRC": "1",
    "NCBI_DONT_USE_LOCAL_CONFIG": "1",
}


def _subprocess_calls(tree: ast.Module) -> list[ast.Call]:
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "run" and isinstance(node.func.value, ast.Name):
            if node.func.value.id == "subprocess":
                calls.append(node)
    return calls


def test_fixture_makeblastdb_calls_disable_telemetry():
    tree = ast.parse(FIXTURE.read_text(encoding="utf-8"))
    builders = [
        call for call in _subprocess_calls(tree)
        if any(
            isinstance(arg, ast.BinOp)
            and isinstance(arg.right, ast.Constant)
            and arg.right.value == "makeblastdb"
            for arg in ast.walk(call)
        )
        or any(
            isinstance(arg, ast.Constant) and arg.value == "makeblastdb"
            for arg in ast.walk(call)
        )
    ]
    assert builders, "no fixture makeblastdb calls found"
    for call in builders:
        keywords = {kw.arg: kw.value for kw in call.keywords}
        assert "env" in keywords, "makeblastdb fixture must pass an isolated env"
        env_name = keywords["env"]
        assert isinstance(env_name, ast.Name), "env must reference a named constant"
        constant = next(
            (node.value for node in tree.body
             if isinstance(node, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == env_name.id for t in node.targets)),
            None,
        )
        assert isinstance(constant, ast.Dict), "env constant must be a dict literal"
        values = {
            key.value: val.value
            for key, val in zip(constant.keys, constant.values)
            if isinstance(key, ast.Constant) and isinstance(val, ast.Constant)
        }
        for name, expected in REQUIRED.items():
            assert values.get(name) == expected, f"fixture env must disable {name}"


def test_runner_child_environment_disables_telemetry():
    env = runner._env(Path("."))
    for name, expected in REQUIRED.items():
        assert env.get(name) == expected, f"runner env must disable {name}"
    assert env.get("PATH") == "/usr/bin:/bin"
