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


def test_worker_pg_fixture_does_not_swallow_a_failed_alembic_upgrade():
    """A migration that never ran must not surface as a missing-table error.

    The legacy 3.14 lane runs ``alembic upgrade head`` in a subprocess with
    ``check=False``. When that upgrade fails (for example because the 3.15-only
    API app cannot be imported under 3.14), the fixture used to continue and
    die on ``relation \"releases\" does not exist`` -- a symptom that points at
    the table instead of at the migration that was supposed to create it.
    Keep the assertion that reports the real stdout/stderr on failure.
    """
    source = (ROOT / "apps/worker/tests/test_vcf_import.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    upgrade = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "upgrade" for t in node.targets)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "run"
    )
    keywords = {kw.arg: kw.value for kw in upgrade.value.keywords}
    assert isinstance(keywords.get("check"), ast.Constant)
    assert keywords["check"].value is False
    # The subprocess result must be checked before any schema-dependent work.
    checked = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assert)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Attribute)
        and node.test.left.attr == "returncode"
        and isinstance(node.test.left.value, ast.Name)
        and node.test.left.value.id == "upgrade"
    ]
    assert checked, (
        "the fixture must assert upgrade.returncode == 0 and print the real "
        "stdout/stderr, instead of letting a swallowed migration failure "
        "surface as a missing-table error"
    )
