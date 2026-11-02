"""Historical engine acceptance must remain a required, separate CI gate."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_embedded_engine_module_runs_in_the_legacy_gate():
    tests = ROOT / "apps/worker/tests"
    embedded = {
        path.name for path in tests.glob("test_*.py")
        if "import chdb.session" in path.read_text()
    }
    tree = ast.parse((tests / "conftest.py").read_text())
    assignment = next(
        node for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "LEGACY_ENGINE_MODULES"
                for target in node.targets)
    )
    assert set(ast.literal_eval(assignment.value)) == embedded
    gate = (ROOT / "scripts/verify-legacy-worker-tests.sh").read_text()
    assert all(f"tests/{name}" in gate for name in embedded)
    assert "SOYMUTDB_RUN_LEGACY_CHDB_TESTS=1" in gate
    assert "SOYMUTDB_RUN_POSTGRES_INTEGRATION=1" in gate
    assert "with-postgres-service.sh" in gate
    assert "sys.version_info[:2] == (3, 14)" in gate
    assert 'bash "${REPO_ROOT}/scripts/verify-legacy-worker-tests.sh"' in (
        ROOT / "scripts/ci-job-steps.sh"
    ).read_text()


def test_native_worker_does_not_install_the_legacy_embedded_engine():
    import tomllib

    project = tomllib.loads((ROOT / "apps/worker/pyproject.toml").read_text())["project"]
    assert not any("chdb" in dep for dep in project["dependencies"])
    assert not any("chdb" in dep for dep in project["optional-dependencies"]["dev"])
