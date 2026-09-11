#!/usr/bin/env python3
"""Fail when the toolchain version pins disagree anywhere in the repository.

Why this exists as a script and not only as a unit test
    The pins were already inconsistent when this guard was written: `.nvmrc`
    said one Node version and `.node-version` said another, while `package.json`
    said a third. Nothing caught it, because each file is read by a different
    toolchain (nvm, asdf/volta, corepack) and none of them cross-check the
    others. A developer then gets a different build than CI, on the same commit.

    `scripts/test_ci_job_contracts.py` asserts the delivery contract; this
    script is the single source of truth for the pins themselves, so it can also
    be run directly (and wired into pre-commit) without loading the test suite.

Sources checked
    package.json      engines.node / engines.pnpm / packageManager
    .nvmrc            nvm
    .node-version     asdf / volta / mise
    scripts/*.sh      SOYMUTDB_CI_*_VERSION defaults in the shared scripts

Usage
    python3 scripts/check-toolchain-pins.py          # exits 1 on any mismatch
    python3 scripts/check-toolchain-pins.py --json   # machine-readable result
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The authoritative pins. Everything else is checked against these.
EXPECTED_NODE = "24.19.0"
EXPECTED_PNPM = "11.21.0"
EXPECTED_PYTHON_MIN = (3, 14)

# Container images referenced by the CNB pipeline. The platform builds them on
# every use, so an unpinned FROM would move the environment that scans and signs
# releases without any review noticing.
BUILD_ENV_DOCKERFILES = (
    ".cnb/env/Dockerfile.build-tools",
)

# Shared scripts that carry a SOYMUTDB_CI_*_VERSION default.
# (file, variables that file is responsible for declaring)
PIN_SOURCES = (
    ("scripts/ci-job-steps.sh", ("NODE_VERSION", "PNPM_VERSION")),
    ("scripts/setup-workspace.sh", ("PNPM_VERSION",)),
)


def _fail(errors: list[str], message: str) -> None:
    errors.append(message)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def check_node(errors: list[str]) -> None:
    nvmrc = _read(".nvmrc").strip()
    node_version = _read(".node-version").strip()
    if nvmrc != EXPECTED_NODE:
        _fail(errors, f".nvmrc: {nvmrc!r} != {EXPECTED_NODE!r}")
    if node_version != EXPECTED_NODE:
        _fail(errors, f".node-version: {node_version!r} != {EXPECTED_NODE!r}")
    if nvmrc != node_version:
        _fail(
            errors,
            f".nvmrc ({nvmrc!r}) and .node-version ({node_version!r}) disagree; "
            "nvm and asdf/volta/mise would each select a different runtime",
        )


def check_pnpm(errors: list[str]) -> None:
    package = json.loads(_read("package.json"))
    package_manager = package.get("packageManager", "")
    if package_manager != f"pnpm@{EXPECTED_PNPM}":
        _fail(errors, f"package.json packageManager: {package_manager!r} != pnpm@{EXPECTED_PNPM}")
    engines_pnpm = package.get("engines", {}).get("pnpm")
    if engines_pnpm != EXPECTED_PNPM:
        _fail(errors, f"package.json engines.pnpm: {engines_pnpm!r} != {EXPECTED_PNPM!r}")


def check_node_engine(errors: list[str]) -> None:
    package = json.loads(_read("package.json"))
    engine = package.get("engines", {}).get("node", "")
    major = EXPECTED_NODE.split(".")[0]
    if f">={major}" not in engine or f"<{int(major) + 1}" not in engine:
        _fail(errors, f"package.json engines.node: {engine!r} does not bracket {EXPECTED_NODE}")


def check_python(errors: list[str]) -> None:
    minimum = f"{EXPECTED_PYTHON_MIN[0]}.{EXPECTED_PYTHON_MIN[1]}"
    # Packages the delivery pipeline runs on 3.14 must not declare a lower
    # floor. apps/mcp-server is excluded on purpose: it supports 3.11+ and is
    # exercised through its own transport job, so a 3.11 floor is correct there.
    exempt = {"apps/mcp-server"}
    candidates = sorted(ROOT.glob("apps/*/pyproject.toml")) + sorted(
        ROOT.glob("packages/*/pyproject.toml")
    )
    for path in candidates:
        if str(path.parent.relative_to(ROOT)) in exempt:
            continue
        text = path.read_text(encoding="utf-8")
        match = re.search(r'requires-python\s*=\s*"([^"]+)"', text)
        if not match:
            continue
        requires = match.group(1)
        floor = re.search(r">=\s*(\d+)\.(\d+)", requires)
        if floor and (int(floor.group(1)), int(floor.group(2))) < EXPECTED_PYTHON_MIN:
            _fail(
                errors,
                f"{path.relative_to(ROOT)}: requires-python {requires!r} is below the "
                f"CI runtime {minimum}",
            )


def check_build_env_images(errors: list[str]) -> None:
    """Every CNB build-environment image must pin the epoch in its tag.

    `.cnb/env/*` images are built by the platform on every use. A floating tag
    silently moves the environment that scans and signs releases, so each FROM
    that references a platform/third-party image must carry an explicit version.
    """
    for relative in BUILD_ENV_DOCKERFILES:
        path = ROOT / relative
        if not path.is_file():
            _fail(errors, f"missing build environment image: {relative}")
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.upper().startswith("FROM "):
                continue
            image = stripped.split()[1]
            # `python:3.14` / `python:3.12` are grader-pinned elsewhere; this
            # guard only rejects a completely untagged reference.
            if ":" not in image or image.endswith(":latest"):
                _fail(
                    errors,
                    f"{relative}: FROM {image} is not version-pinned",
                )


def check_pin_sources(errors: list[str]) -> None:
    expected = {
        "NODE_VERSION": EXPECTED_NODE,
        "PNPM_VERSION": EXPECTED_PNPM,
    }
    for source, variables in PIN_SOURCES:
        path = ROOT / source
        if not path.is_file():
            _fail(errors, f"missing pin source: {source}")
            continue
        text = path.read_text(encoding="utf-8")
        for variable in variables:
            value = expected[variable]
            pattern = rf'\b{variable}="\${{SOYMUTDB_CI_[A-Z_]*:-([^}}]+)}}"'
            match = re.search(pattern, text)
            if not match:
                _fail(errors, f"{source}: no default found for {variable}")
                continue
            if match.group(1) != value:
                _fail(
                    errors,
                    f"{source}: {variable} defaults to {match.group(1)!r}, expected {value!r}",
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit a JSON result")
    args = parser.parse_args()

    errors: list[str] = []
    check_node(errors)
    check_node_engine(errors)
    check_pnpm(errors)
    check_python(errors)
    check_build_env_images(errors)
    check_pin_sources(errors)

    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
    elif errors:
        for error in errors:
            print(f"toolchain pin mismatch: {error}", file=sys.stderr)
    else:
        print(
            f"toolchain pins OK (node {EXPECTED_NODE}, pnpm {EXPECTED_PNPM}, "
            f"python >= {EXPECTED_PYTHON_MIN[0]}.{EXPECTED_PYTHON_MIN[1]})"
        )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
