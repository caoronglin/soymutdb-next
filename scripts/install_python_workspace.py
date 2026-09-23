#!/usr/bin/env python3
"""Install the workspace's local Python distributions in one canonical order.

Every CI provider and every developer machine used to spell out its own
``pip install -e`` sequence. They drifted: the GitHub workflows installed
``packages/jobs-py`` and then ``apps/api``, but not
``packages/import-protocol``, which ``apps/api`` and ``apps/worker`` declare as
``soymutdb-import-protocol==0.1.0``. pip then tried to fetch that distribution
from PyPI, where it has never been published:

    ERROR: Could not find a version that satisfies the requirement
    soymutdb-import-protocol==0.1.0 (from soymutdb-api) (from versions: none)

The local packages are installed editable and in dependency order here, once,
so GitHub Actions, CNB, ``scripts/ci-job-steps.sh``, and local development all
execute the same install plan.

Contract:

* The shared distributions below are installed, in order, before any target.
  They are the packages the apps import but which pip cannot resolve from an
  index.
* A target is a repository-relative path to a local distribution, optionally
  with an extra (``apps/api[dev]``). A target that does not exist, or that has
  no ``pyproject.toml``, fails the whole install: a typo must not degrade into
  a silent skip.
* ``--requirement`` installs third-party packages after the local targets
  (``pytest`` for the baseline jobs).
* The virtualenv is created when missing; ``--recreate`` removes it first.
  ``--expect-version`` verifies the venv interpreter against the repository
  Python pin, so a rebuilt image or a stray interpreter cannot run the delivery
  chain on a version nothing declared.

Usage:
    python3 scripts/install_python_workspace.py --venv apps/api/.venv \
        --upgrade-pip --expect-version 3.14 "apps/api[dev]"
    python3 scripts/install_python_workspace.py --venv .ci-venv \
        --expect-version 3.14 apps/api --requirement pytest --requirement ruff
    python3 scripts/install_python_workspace.py --dry-run --venv .venv \
        "apps/worker[dev]"
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Installed editable, in this order, before any app target. pip cannot fetch
# them from PyPI: they are internal workspace distributions.
SHARED_DISTRIBUTIONS = (
    "packages/jobs-py",
    "packages/import-protocol",
)


class InstallError(RuntimeError):
    """The install plan is invalid; nothing is installed."""


def venv_python(venv: Path, platform: str | None = None) -> Path:
    """Return the interpreter a virtualenv will expose on this platform."""
    if (platform or os.name) == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _split_extra(spec: str) -> tuple[str, str]:
    """Split ``apps/api[dev]`` into the path and the editable extra spec."""
    if "[" not in spec:
        return spec, ""
    path, _, remainder = spec.partition("[")
    if not path or not remainder.endswith("]"):
        raise InstallError(f"malformed target with extras: {spec!r}")
    return path, f"[{remainder}"


def _resolve_local_distribution(spec: str) -> tuple[Path, str]:
    """Resolve one target spec to an absolute path plus its editable suffix."""
    relative, extra = _split_extra(spec)
    path = (REPO_ROOT / relative).resolve()
    if REPO_ROOT not in path.parents and path != REPO_ROOT:
        raise InstallError(f"target escapes the repository: {spec!r}")
    if not path.is_dir():
        raise InstallError(f"target directory does not exist: {relative}")
    if not (path / "pyproject.toml").is_file():
        raise InstallError(f"target has no pyproject.toml: {relative}")
    return path, extra


def build_commands(
    venv: Path,
    targets: list[str],
    requirements: list[str],
    *,
    upgrade_pip: bool,
) -> list[list[str]]:
    """Return the ordered command plan (shared → targets → requirements)."""
    python = venv_python(venv)
    commands: list[list[str]] = []
    if upgrade_pip:
        commands.append([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    for spec in SHARED_DISTRIBUTIONS:
        path, extra = _resolve_local_distribution(spec)
        commands.append([str(python), "-m", "pip", "install", "--quiet", "-e", f"{path}{extra}"])
    for spec in targets:
        path, extra = _resolve_local_distribution(spec)
        commands.append([str(python), "-m", "pip", "install", "-e", f"{path}{extra}"])
    if requirements:
        commands.append([str(python), "-m", "pip", "install", *requirements])
    return commands


def check_python_version(python: Path, expected: str) -> None:
    """Fail when the venv interpreter does not match the repository pin."""
    probe = (
        "import sys; sys.exit(0 if '.'.join(map(str, sys.version_info[:2])) "
        f"== {expected!r} else 1)"
    )
    completed = subprocess.run(
        [str(python), "-c", probe],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        actual = subprocess.run(
            [str(python), "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        raise InstallError(
            f"{python} is Python {actual or '<unknown>'}, not the pinned {expected}"
        )


def create_venv(venv: Path, create_python: str, recreate: bool) -> None:
    if recreate and venv.exists():
        shutil.rmtree(venv)
    if venv.exists():
        if not venv_python(venv).exists():
            raise InstallError(f"{venv} exists but has no interpreter; pass --recreate")
        return
    venv.parent.mkdir(parents=True, exist_ok=True)
    interpreter = shutil.which(create_python) or create_python
    completed = subprocess.run(
        [interpreter, "-m", "venv", str(venv)],
        check=False,
    )
    if completed.returncode != 0:
        raise InstallError(f"could not create the virtualenv with {interpreter!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--venv",
        required=True,
        help="virtualenv path (relative paths resolve against the repository root)",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="interpreter used to create the virtualenv (default: this interpreter)",
    )
    parser.add_argument("--recreate", action="store_true", help="delete and recreate the venv")
    parser.add_argument("--upgrade-pip", action="store_true", help="upgrade pip before installing")
    parser.add_argument(
        "--expect-version",
        default=None,
        metavar="MAJOR.MINOR",
        help="verify the venv interpreter against the repository Python pin",
    )
    parser.add_argument(
        "--requirement",
        action="append",
        default=[],
        metavar="PACKAGE",
        help="third-party package installed after the local targets (repeatable)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the install plan as JSON and exit without running pip",
    )
    parser.add_argument("targets", nargs="+", help="local distributions, e.g. apps/api[dev]")
    args = parser.parse_args(argv)

    venv = Path(args.venv)
    if not venv.is_absolute():
        venv = REPO_ROOT / venv

    try:
        commands = build_commands(
            venv,
            args.targets,
            args.requirement,
            upgrade_pip=args.upgrade_pip,
        )
    except InstallError as error:
        parser.exit(2, f"install_python_workspace: {error}\n")

    if args.dry_run:
        print(json.dumps({"venv": str(venv), "commands": commands}, indent=2))
        return 0

    print(f"install_python_workspace: venv={venv} targets={' '.join(args.targets)}")
    create_venv(venv, args.python, args.recreate)
    python = venv_python(venv)

    if args.expect_version:
        try:
            check_python_version(python, args.expect_version)
        except InstallError as error:
            print(f"install_python_workspace: {error}", file=sys.stderr)
            return 1

    for command in commands:
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            print(
                f"install_python_workspace: command failed ({completed.returncode}): "
                + " ".join(command),
                file=sys.stderr,
            )
            return completed.returncode
    print("install_python_workspace: workspace Python distributions installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
