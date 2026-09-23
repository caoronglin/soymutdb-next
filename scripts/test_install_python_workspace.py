"""Contract tests for the shared Python workspace bootstrap.

The install planner is the single source of truth for the editable-install
order GitHub, CNB, and local runs execute. These tests pin the two properties
that the 2026-09 CI failure came from: the shared distributions (including
``packages/import-protocol``, which does not exist on PyPI) are installed
before any app target, and an unknown target fails closed instead of silently
degrading into "pip installs what it can".
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_python_workspace.py"


def _module():
    spec = importlib.util.spec_from_file_location("install_python_workspace", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_dry_run_installs_shared_distributions_before_app_targets() -> None:
    completed = _run("--dry-run", "--venv", ".tmp-venv", "apps/api[dev]")
    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    commands = plan["commands"]
    editable = [command for command in commands if "-e" in command]
    installed = [command[command.index("-e") + 1] for command in editable]

    import_protocol = str(ROOT / "packages" / "import-protocol")
    jobs_py = str(ROOT / "packages" / "jobs-py")
    api = str(ROOT / "apps" / "api") + "[dev]"

    assert import_protocol in installed
    assert jobs_py in installed
    assert api in installed
    # The shared distributions must be installed before apps/api resolves its
    # `soymutdb-import-protocol==0.1.0` requirement.
    assert installed.index(jobs_py) < installed.index(api)
    assert installed.index(import_protocol) < installed.index(api)


def test_dry_run_keeps_requirements_after_local_targets() -> None:
    completed = _run(
        "--dry-run", "--venv", ".tmp-venv", "apps/api", "--requirement", "pytest"
    )
    assert completed.returncode == 0, completed.stderr
    commands = json.loads(completed.stdout)["commands"]
    last = commands[-1]
    assert last[-1] == "pytest"
    assert "-e" not in last


def test_unknown_target_fails_closed() -> None:
    completed = _run("--dry-run", "--venv", ".tmp-venv", "apps/does-not-exist")
    assert completed.returncode == 2
    assert "does not exist" in completed.stderr


def test_target_without_pyproject_fails_closed() -> None:
    completed = _run("--dry-run", "--venv", ".tmp-venv", "docs")
    assert completed.returncode == 2
    assert "pyproject.toml" in completed.stderr


def test_venv_python_path_is_platform_specific(tmp_path: Path) -> None:
    module = _module()
    assert module.venv_python(tmp_path, platform="posix") == tmp_path / "bin" / "python"
    assert (
        module.venv_python(tmp_path, platform="nt") == tmp_path / "Scripts" / "python.exe"
    )


def test_expected_version_accepts_the_running_interpreter_and_rejects_others(
    tmp_path: Path,
) -> None:
    module = _module()
    running = f"{sys.version_info[0]}.{sys.version_info[1]}"
    module.check_python_version(Path(sys.executable), running)

    wrong = "2.7"
    try:
        module.check_python_version(Path(sys.executable), wrong)
    except module.InstallError as error:
        assert wrong in str(error)
    else:  # pragma: no cover - only reached if the probe stops failing
        raise AssertionError("a mismatched Python version must fail closed")
