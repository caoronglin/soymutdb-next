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
    Dockerfiles       the ghcr.io/astral-sh/uv base image each image builds from
    Dockerfiles       pnpm@<version> installed by the frontend runtime images,
                      their Node base tag, and the CNB frontend ARG pin
    workflows         the uv== install line in the GitHub mirror

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
EXPECTED_NODE = "26.13.0"
EXPECTED_PNPM = "12.11.2"
EXPECTED_PYTHON_MIN = (3, 15)

# uv reaches every image as a pinned base image rather than as an installed
# package, so a bump that only touched the CI script would leave the images
# resolving a different resolver than the gate meant to certify them.
# Dockerfile.worker is included deliberately: the worker image is built from
# the same checkout as the others, and a drift here is exactly the failure
# this guard exists to make loud.
EXPECTED_UV = "0.13.1"
UV_BASE_IMAGE_DOCKERFILES = (
    "infra/docker/Dockerfile.api",
    "infra/docker/Dockerfile.worker",
    "infra/docker/Dockerfile.migrate",
    # The legacy ClickHouse lane stays on Python 3.14 because clickhouse-connect
    # publishes no 3.15 release. That is a Python constraint, not a uv one, so
    # the uv pin still has to match: a resolver drift must not hide behind the
    # deliberately-older interpreter.
    "infra/docker/Dockerfile.migrate-clickhouse",
    "apps/mcp-server/Dockerfile",
)

# deploy/conda/omicverse/setup.sh also hard-fails on a uv version and is
# deliberately NOT checked here. It gates a hash-locked, already-qualified
# scientific profile whose requirements.lock was resolved by uv 0.11.33; moving
# that pin without re-running its own qualification flow would let a future
# operator sync an unverified resolver over a verified lock. Its README carries
# the upgrade procedure instead.

# Container images referenced by the CNB pipeline. The platform builds them on
# every use, so an unpinned FROM would move the environment that scans and signs
# releases without any review noticing.
BUILD_ENV_DOCKERFILES = (
    ".cnb/env/Dockerfile.build-tools",
    # The frontend gate exports the backend OpenAPI schema, so its stage image
    # must carry Node AND Python. Both pins live in this Dockerfile.
    ".cnb/env/Dockerfile.frontend",
)

# (dockerfile, tag the base image must use) for the frontend environment. It
# starts from the Python image and installs Node from the official release
# tarball, because `COPY --from=python:3.15` into a node:26.13.0 base cannot
# work: the two sit on different Debian generations and the copied interpreter
# needs a glibc the older base does not have.
FRONTEND_BUILD_ENV = ".cnb/env/Dockerfile.frontend"
FRONTEND_BUILD_ENV_BASE = "python:3.15"

# The Node tarball checksums published in
# https://nodejs.org/dist/v<version>/SHASUMS256.txt. Duplicated here on purpose:
# the Dockerfile verifies the download against its own copy, and this guard
# fails when the two disagree, so a checksum can never be edited to fit a
# tampered tarball without also editing this file and a reviewer seeing it.
NODE_TARBALL_SHA256 = {
    "x64": "d28a96af6c38596f6d9d97c0ee531c13d238d757742387d1928de822d959e997",
    "arm64": "406fe3fbde1c054adff8b297c16fdb5af6659db327c1ac8acd46b56ef1af9a92",
}

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
    # Every first-party distribution the delivery pipeline runs must not declare
    # a floor below the CI runtime. There is no exemption left: apps/mcp-server
    # used to be excluded because it declared 3.11+ while its transport job ran
    # on the shared image, and it now declares the same >=3.15 floor as the API,
    # the worker and both shared packages. A package that genuinely needs an
    # older floor belongs in an extra with a python_version marker, not in an
    # exemption from this check.
    candidates = sorted(ROOT.glob("apps/*/pyproject.toml")) + sorted(
        ROOT.glob("packages/*/pyproject.toml")
    )
    for path in candidates:
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
            # `python:3.15` / `python:3.14` are grader-pinned elsewhere; this
            # guard only rejects a completely untagged reference.
            if ":" not in image or image.endswith(":latest"):
                _fail(
                    errors,
                    f"{relative}: FROM {image} is not version-pinned",
                )


def check_build_env_toolchain_tags(errors: list[str]) -> None:
    """The frontend stage image must pin the exact Node/Python versions.

    `check_build_env_images` only rejects a completely untagged `FROM`. That is
    enough for the release tooling image, but not for the image that runs the
    frontend gates: it must track `.nvmrc` and the Python pin, or the gate would
    run on a toolchain the repository never declared.

    Both toolchains matter here. Python comes from the base image; Node comes
    from the official release tarball, so it is pinned by version AND by the
    published checksum the Dockerfile verifies before unpacking.
    """
    path = ROOT / FRONTEND_BUILD_ENV
    if not path.is_file():
        _fail(errors, f"missing build environment image: {FRONTEND_BUILD_ENV}")
        return
    text = path.read_text(encoding="utf-8")

    tags = {
        line.strip().split()[1]
        for line in text.splitlines()
        if line.strip().upper().startswith("FROM ") and len(line.split()) > 1
    }
    if FRONTEND_BUILD_ENV_BASE not in tags:
        _fail(
            errors,
            f"{FRONTEND_BUILD_ENV}: no FROM uses {FRONTEND_BUILD_ENV_BASE!r} "
            f"(found {sorted(tags)!r})",
        )

    # The Node version must be the repository pin, not a second copy that can
    # drift from .nvmrc.
    match = re.search(r"^ARG NODE_VERSION=(\S+)\s*$", text, re.M)
    if not match:
        _fail(errors, f"{FRONTEND_BUILD_ENV}: no ARG NODE_VERSION default found")
    elif match.group(1) != EXPECTED_NODE:
        _fail(
            errors,
            f"{FRONTEND_BUILD_ENV}: NODE_VERSION is {match.group(1)!r}, "
            f"expected {EXPECTED_NODE!r}",
        )

    # The checksum the Dockerfile verifies must be the published one, per
    # architecture. A wrong-but-consistent pair would still fail the build, but
    # a swapped pair would silently verify the wrong artifact on arm64.
    for arch, expected_sha in NODE_TARBALL_SHA256.items():
        variable = f"NODE_SHA256_{arch.upper()}"
        match = re.search(rf"^ARG {variable}=(\S+)\s*$", text, re.M)
        if not match:
            _fail(errors, f"{FRONTEND_BUILD_ENV}: no ARG {variable} found")
            continue
        if match.group(1) != expected_sha:
            _fail(
                errors,
                f"{FRONTEND_BUILD_ENV}: {variable} is {match.group(1)!r}, "
                f"expected the published {expected_sha!r}",
            )

    # Node replaces the base image's Python from being the only toolchain, so
    # the build must fail if the interpreter cannot actually run.
    if "sha256sum --check" not in text:
        _fail(
            errors,
            f"{FRONTEND_BUILD_ENV}: the Node tarball is downloaded without a "
            "sha256 verification",
        )


def check_workflow_pins(errors: list[str]) -> None:
    """The GitHub mirror workflows must install the pinned pnpm version.

    AGENTS.md requires the toolchain pins to agree across .nvmrc, package.json,
    .cnb.yml AND the workflows. The workflows set up pnpm either via
    pnpm/action-setup (an inline ``version:`` under the step) or corepack
    (``pnpm@X``); a stale pin breaks ``pnpm install --frozen-lockfile`` against
    the lockfile format the rest of the repo migrated to.
    """
    for path in sorted(ROOT.glob(".github/workflows/*.yml")):
        relative = path.relative_to(ROOT)
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "pnpm/action-setup" in line or "pnpm prepare" in line or (
                "corepack" in line and "pnpm@" in line
            ):
                window = "\n".join(lines[index : index + 7])
                inline = re.search(r"^\s*version:\s*([0-9][0-9.]*)\s*$", window, re.M)
                corepack = re.search(r"pnpm@([0-9][0-9.]*)", line)
                found = inline.group(1) if inline else (corepack.group(1) if corepack else None)
                if found is not None and found != EXPECTED_PNPM:
                    _fail(
                        errors,
                        f"{relative}: pnpm {found!r} != {EXPECTED_PNPM!r}",
                    )


def check_pin_sources(errors: list[str]) -> None:
    expected = {
        "NODE_VERSION": EXPECTED_NODE,
        "PNPM_VERSION": EXPECTED_PNPM,
        "UV_VERSION": EXPECTED_UV,
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


def check_uv(errors: list[str]) -> None:
    """Every image and every workflow must resolve the same uv.

    uv is not installed into these images; it is copied in from a pinned base
    image, so a stale tag still builds a working image -- one that resolves
    dependencies with a different resolver than the gate certified. That is
    invisible in every other check, which is why it gets its own.
    """
    for source in UV_BASE_IMAGE_DOCKERFILES:
        path = ROOT / source
        if not path.is_file():
            _fail(errors, f"missing uv Dockerfile: {source}")
            continue
        text = path.read_text(encoding="utf-8")
        found_tags = sorted(set(re.findall(r"ghcr\.io/astral-sh/uv:([^\s/]+)", text)))
        if not found_tags:
            _fail(errors, f"{source}: no pinned ghcr.io/astral-sh/uv base image")
            continue
        for found in found_tags:
            if found != EXPECTED_UV:
                _fail(errors, f"{source}: uv base image {found!r} != {EXPECTED_UV!r}")

    for path in sorted(ROOT.glob(".github/workflows/*.yml")):
        relative = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for found in sorted(set(re.findall(r"uv==([0-9]+\.[0-9]+\.[0-9]+)", text))):
            if found != EXPECTED_UV:
                _fail(errors, f"{relative}: uv=={found} != uv=={EXPECTED_UV}")


def check_cnb_pipeline_node_images(errors: list[str]) -> None:
    """Every ``node:`` image tag in the CNB pipeline must be the repository pin.

    ``scripts/test_platform_delivery_contracts.py`` already asserts this, but
    this script is the named toolchain authority and is run on its own (preflight,
    developer machines). Without it, editing a pipeline back to a stale Node
    release left this checker reporting "OK" while the repository pin was no
    longer what CI actually built or tested with.
    """
    sources = [ROOT / ".cnb.yml"] + sorted((ROOT / ".cnb/pipelines").glob("*.yml"))
    for path in sources:
        if not path.is_file():
            _fail(errors, f"missing CNB pipeline source: {path.name}")
            continue
        text = path.read_text(encoding="utf-8")
        # Match a full semver only: prose like `` `node:26.13.0` `` in a comment
        # must not be scraped as an image tag with stray punctuation attached.
        for tag in sorted(set(re.findall(r"\bnode:(\d+\.\d+\.\d+)", text))):
            if tag != EXPECTED_NODE:
                _fail(
                    errors,
                    f"{path.name}: node image tag {tag!r} != {EXPECTED_NODE!r}",
                )


RUNTIME_DOCKERFILES = (
    "apps/jbrowse/Dockerfile",
    "infra/docker/Dockerfile.web",
    "infra/docker/Dockerfile.admin",
    # The CNB frontend stage image installs pnpm from ARG PNPM_VERSION.
    ".cnb/env/Dockerfile.frontend",
)


def check_runtime_dockerfiles(errors: list[str]) -> None:
    """Runtime images must install the pinned pnpm and Node base tag.

    The frontend images install pnpm from npm at a literal version (or via an
    ARG in the CNB image), and their ``FROM node:`` tag is a second copy of the
    .nvmrc pin. Both drifted silently when the repository moved to pnpm
    12.11.2: the images kept building with 12.5.1, so a frozen-lockfile install
    ran a package manager the repository never declared. ``package.json``,
    ``.cnb.yml`` and the workflows were updated in that bump; the images were
    not, and no other check covered them.
    """
    for relative in RUNTIME_DOCKERFILES:
        path = ROOT / relative
        if not path.is_file():
            _fail(errors, f"missing runtime Dockerfile: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        for found in sorted(set(re.findall(r"pnpm@([0-9]+\.[0-9]+\.[0-9]+)", text))):
            if found != EXPECTED_PNPM:
                _fail(errors, f"{relative}: pnpm@{found} != pnpm@{EXPECTED_PNPM}")
        match = re.search(r"^ARG PNPM_VERSION=(\S+)\s*$", text, re.M)
        if match and match.group(1) != EXPECTED_PNPM:
            _fail(
                errors,
                f"{relative}: ARG PNPM_VERSION={match.group(1)} != {EXPECTED_PNPM}",
            )
        for tag in sorted(set(re.findall(r"\bFROM\s+node:([0-9]+\.[0-9]+\.[0-9]+)", text))):
            if tag != EXPECTED_NODE:
                _fail(errors, f"{relative}: node base image {tag!r} != {EXPECTED_NODE!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit a JSON result")
    args = parser.parse_args()

    errors: list[str] = []
    check_node(errors)
    check_node_engine(errors)
    check_pnpm(errors)
    check_python(errors)
    check_uv(errors)
    check_runtime_dockerfiles(errors)
    check_build_env_images(errors)
    check_build_env_toolchain_tags(errors)
    check_pin_sources(errors)
    check_cnb_pipeline_node_images(errors)
    check_workflow_pins(errors)

    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
    elif errors:
        for error in errors:
            print(f"toolchain pin mismatch: {error}", file=sys.stderr)
    else:
        print(
            f"toolchain pins OK (node {EXPECTED_NODE}, pnpm {EXPECTED_PNPM}, "
            f"python >= {EXPECTED_PYTHON_MIN[0]}.{EXPECTED_PYTHON_MIN[1]}, "
            f"uv {EXPECTED_UV})"
        )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
