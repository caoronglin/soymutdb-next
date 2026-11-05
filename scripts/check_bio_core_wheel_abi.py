#!/usr/bin/env python3
"""Validate a bio-core wheel's CPython ABI / platform tag against its arch.

`infra/docker/Dockerfile.api` builds one native wheel per image pipeline
(amd64 / arm64). Nothing records *which* wheel tag belongs to *which*
architecture, so an arm64 image could ship an x86_64 wheel and the only thing
that would notice is `import soymutdb_bio_core` failing at runtime. This tool
is the checkable ledger: it parses the PEP 427 filename, cross-checks the
wheel's own `.dist-info/WHEEL` Tag declarations, and rejects a tag whose
machine does not match the image architecture.

Two layers, both stdlib-only (no Rust, no wheel, no Docker needed to run):

1. `--ledger` — validate `docs/dev/bio-core-wheel-abi-tags.md` against the
   committed facts (CPython floor, producer/consumer globs, both arch rows).
2. `--wheel <file> --arch <amd64|arm64>` — validate a real wheel's filename
   and internal WHEEL metadata.

`--self-test` runs the built-in synthetic negatives so the guard itself is
proven to fail on each regression class. A bad tag is a hard failure, never a
skipped pass.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "dev" / "bio-core-wheel-abi-tags.md"

# PEP 427: {distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl
WHEEL_NAME = re.compile(
    r"^(?P<name>[A-Za-z0-9_]+)-(?P<version>[A-Za-z0-9_.!+]+)"
    r"(?:-(?P<build>[A-Za-z0-9_]+))?"
    r"-(?P<python>[A-Za-z0-9_.]+)-(?P<abi>[A-Za-z0-9_.]+)"
    r"-(?P<platform>[A-Za-z0-9_.]+)\.whl$"
)
# PEP 600 manylinux_<glibc major>_<glibc minor>_<machine>, plus the legacy
# manylinux2014 alias and the unportable-but-native `linux_<machine>` tag.
MANYLINUX = re.compile(r"^manylinux_(?P<major>\d+)_(?P<minor>\d+)_(?P<machine>.+)$")
LEGACY_MANYLINUX = re.compile(r"^manylinux(?:2010|2014)_(?P<machine>.+)$")
NATIVE_LINUX = re.compile(r"^linux_(?P<machine>.+)$")

# The oldest cargo-audit whose runner log shows the advisory scan completing
# without a CVSS 4.0 parse failure. 0.21.2 aborts with "unsupported CVSS
# version: 4.0" (cnb-k4a-1k6kbhl3c L4405 -- that run installed 0.21.2, not
# 0.22.1). 0.22.1 also died (cnb-7qb-1k6kbvp1e exit 1) with its scan stdout
# redirected, so the reason is not in the stage log; its own chain resolved
# cvss 2.2.0 / rustsec 0.32.0. 0.22.2 is the first measured-clean audit run
# (cnb-qf2-1k6kc4hoo). The floor is a measured resolution, not "newest
# available": re-pinning lower returns to versions whose runner outcome is
# a red gate.
AUDIT_FLOOR = (0, 22, 2)
# Same wall, same rule, second scanner. cargo-deny reads the advisory database
# through rustsec too, so 0.18.4 (rustsec 0.30.x -> cvss 2.1.0) dies on the
# first 4.0 vector with "unsupported CVSS version: 4.0" (cnb-qf2-1k6kc4hoo).
# 0.18.9 is the first 0.18 release whose published Cargo.lock carries rustsec
# 0.31.0 -> cvss 2.2.0, verified against the lock rather than inferred from a
# caret range. Two scanners, two floors, one failure mode: keeping only the
# cargo-audit floor left half this gate unguarded.
DENY_FLOOR = (0, 18, 9)
# Both pins are EXACT resolutions, not floors: "the finding set cannot drift
# between two runs of a commit" only holds while both runs install the SAME
# scanner. A floor-only guard lets 0.22.99 / 0.18.99 (or any later release)
# change the advisory parse and the finding set silently. A caller may override
# through the environment; the committed default must be one fixed version.
AUDIT_PIN = "0.22.2"
DENY_PIN = "0.18.9"

DIST = "soymutdb_bio_core"
CPYTHON_TAG = "cp315"
MACHINES = {"amd64": "x86_64", "arm64": "aarch64"}
ARCHES = tuple(MACHINES)


def parse_filename(name: str) -> dict[str, str | None]:
    match = WHEEL_NAME.match(name)
    if not match:
        raise ValueError(f"not a PEP 427 wheel filename: {name!r}")
    return match.groupdict()


def platform_machine(platform: str) -> str | None:
    """Return the machine token of a glibc/linux platform tag, else None.

    `any`, musllinux and non-Linux tags are deliberately not recognised: a
    pure-Python or musl-linked wheel cannot satisfy the native-kernel contract
    of a `python:3.15.0-slim` (glibc) image.
    """
    for pattern in (MANYLINUX, LEGACY_MANYLINUX, NATIVE_LINUX):
        match = pattern.match(platform)
        if match:
            return match.group("machine")
    return None


def filename_failures(name: str, arch: str) -> list[str]:
    """Failures from the filename alone (usable before the archive is read)."""
    try:
        fields = parse_filename(name)
    except ValueError as exc:
        return [str(exc)]
    failures: list[str] = []
    if fields["name"].lower().replace("-", "_") != DIST:
        failures.append(f"wrong distribution: {fields['name']!r}, expected {DIST!r}")
    for key in ("python", "abi"):
        if fields[key] != CPYTHON_TAG:
            failures.append(
                f"{key} tag is {fields[key]!r}, expected {CPYTHON_TAG!r} "
                "(the API runtime image is CPython 3.15)"
            )
    platform = str(fields["platform"])
    machine = platform_machine(platform)
    if machine is None:
        failures.append(
            f"platform tag {platform!r} is not a glibc/linux native tag; "
            "a pure-Python, musl or foreign wheel cannot satisfy this contract"
        )
    elif machine != MACHINES[arch]:
        failures.append(
            f"platform tag {platform!r} has machine {machine!r}, "
            f"but the image is {arch} ({MACHINES[arch]})"
        )
    return failures


def wheel_metadata_failures(path: Path, platform: str) -> list[str]:
    """Cross-check the archive's own .dist-info/WHEEL Tag declarations."""
    if not zipfile.is_zipfile(path):
        return [f"{path} is not a zip/wheel archive"]
    try:
        with zipfile.ZipFile(path) as archive:
            members = [p for p in archive.namelist() if p.endswith(".dist-info/WHEEL")]
            if not members:
                return ["wheel has no .dist-info/WHEEL metadata"]
            text = archive.read(members[0]).decode("utf-8")
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        return [f"cannot read WHEEL metadata: {exc}"]

    tags = {
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.startswith("Tag:")
    }
    expected = f"{CPYTHON_TAG}-{CPYTHON_TAG}-{platform}"
    if expected not in tags:
        return [f"WHEEL metadata does not declare {expected!r}; found {sorted(tags)!r}"]
    return []


def inspect_wheel(path: Path, arch: str) -> list[str]:
    if arch not in MACHINES:
        return [f"unknown arch {arch!r}, expected one of {list(MACHINES)}"]
    failures = filename_failures(path.name, arch)
    # Only read the archive if the filename is plausible; a renamed wheel with
    # a valid filename but lying metadata is the failure mode worth catching.
    try:
        platform = str(parse_filename(path.name)["platform"])
    except ValueError:
        return failures
    failures += wheel_metadata_failures(path, platform)
    return failures


def ledger_failures(text: str) -> list[str]:
    """Validate the committed ledger against the committed facts.

    The ledger states the RULE and records which tags have actually been
    observed. It must never hardcode a glibc minor that no build produced:
    the minor comes from the build image, so the ledger names the row per arch
    and marks unobserved ones as pending rather than inventing a value.
    """
    failures: list[str] = []
    rows: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] in MACHINES:
            rows[cells[0]] = cells
    for arch, machine in MACHINES.items():
        row = rows.get(arch)
        if row is None:
            failures.append(f"ledger has no row for {arch}")
            continue
        # The row itself must name its machine. A global `_{machine}` check
        # passes when the token survives elsewhere (e.g. the expected-tag
        # column) while the machine column says something else entirely.
        if machine not in row:
            failures.append(f"ledger {arch} row does not name its machine {machine!r}")
        if row[1] != machine:
            failures.append(
                f"ledger {arch} machine column is {row[1]!r}, expected {machine!r}"
            )
        if f"_{machine}" not in row[2]:
            failures.append(f"ledger {arch} expected tag does not name {machine!r}")
    if CPYTHON_TAG not in text:
        failures.append(f"ledger does not record the {CPYTHON_TAG} tag")
    for marker in ("PEP 425", "PEP 600", "pending"):
        if marker not in text:
            failures.append(f"ledger is missing its {marker!r} contract")
    return failures


def cargo_outside_crate(command_line: str) -> bool:
    """True when `cargo` is not positioned right after a `cd` into the crate.

    The failure is positional, not textual. All of these die with "rustup
    could not choose a version of cargo to run" from the repo root:

        cargo audit --json
        command cargo audit --json
        env cargo deny check
        (cd "${CRATE_DIR}" && cd . && cargo install ...)

    while these are fine, because `cargo` heads its own segment:

        (cd "${CRATE_DIR}" && cargo audit --json)
        cd "${CRATE_DIR}" && cargo audit --json

    A version of this check that only looked for '${CRATE_DIR}' anywhere on
    the line accepted every wrapper in the first group, which is why the rule
    is expressed as a position instead.
    """
    # Strip the conditional wrapper first: `if ! (cd X && cargo ...); then` is a
    # run-there guard, not a change of directory, and a rule that rejected it
    # would push people away from failing loudly.
    command_line = re.sub(r"^(?:if|elif|while|until)\s+!?\s*", "", command_line.strip())
    tokens = [t for t in re.split(r"[\s;&|()]+", command_line) if t]
    for index, token in enumerate(tokens):
        if token != "cargo":
            continue
        head = tokens[:index]
        if head[-1:] == ["-v"]:  # `command -v cargo`: a probe, not a run
            continue
        # `cd <dir> && cargo ...` is the one allowed shape: exactly one `cd`,
        # immediately before. A second `cd` (`cd "$C" && cd . && cargo ...`)
        # lands cargo somewhere nobody pinned, so it stays a failure.
        cd_only = head.count("cd") == 1 and head[-1:] != ["&&"]
        if head and head[0] == "cd" and cd_only:
            return False
        return True
    return False


# Only the single bio-core job owns a Rust toolchain, so only it may emit a
# Rust finding set. ANY governance check that names a cargo tool (cargo audit,
# cargo deny, cargo-udeps, ...) would read the same Cargo.lock and produce a
# second, contradictory report. Detection is structural over the parsed checks,
# not a substring of the raw file: a check registered as `cargo-deny` or as an
# argv of ["cargo", "deny", "check"] must not slip past on spelling.
def _names_cargo(text: str) -> bool:
    """True when a field names the `cargo` tool as a standalone token."""
    return "cargo" in re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split()


def foreign_cargo_analyzers(policy: Path) -> list[str]:
    """Names of governance checks that register a Rust cargo analyzer.

    Reads the policy as JSON and inspects each check's ``name``, ``category``,
    ``command`` and report/accept paths. An unreadable/malformed policy returns
    a sentinel so the caller fails closed instead of treating it as clean.
    """
    try:
        document = json.loads(policy.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["<policy unreadable>"]
    if not isinstance(document, dict) or "checks" not in document:
        return ["<policy has no checks key>"]
    checks = document["checks"]
    if not isinstance(checks, list):
        return ["<checks not a list>"]
    registered: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        fields = [check.get("name"), check.get("category"), check.get("accept_file")]
        command = check.get("command")
        if isinstance(command, list):
            fields.extend(command)
        elif command is not None:
            fields.append(command)
        report = check.get("report")
        if isinstance(report, dict):
            fields.append(report.get("path"))
            fields.append(report.get("mode"))
        if any(_names_cargo(f) for f in fields if f is not None):
            registered.append(str(check.get("name", "<unnamed>")))
    return registered


def source_failures() -> list[str]:
    """The producer/consumer glob and the single Rust supply-chain lane."""
    failures: list[str] = []
    glob = "soymutdb_bio_core-*-cp315-*.whl"
    for relative in ("scripts/verify-bio-core.sh", "scripts/verify-backend-tests.sh"):
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"missing source file: {relative}")
        elif glob not in path.read_text(encoding="utf-8"):
            failures.append(f"{relative} no longer names the {glob} wheel")
    pyproject = ROOT / "packages" / "bio-core" / "pyproject.toml"
    if not pyproject.is_file() or 'requires-python = ">=3.15"' not in pyproject.read_text(
        encoding="utf-8"
    ):
        failures.append("packages/bio-core/pyproject.toml no longer pins >=3.15")

    # The Rust scanners belong to the one job that owns a Rust toolchain. A
    # second cargo-* analyzer in the governance policy would produce a second,
    # contradictory finding set for the same Cargo.lock.
    steps = ROOT / "scripts" / "ci-job-steps.sh"
    scanner = ROOT / "scripts" / "verify-bio-core-supply-chain.sh"
    if not steps.is_file() or "verify-bio-core-supply-chain.sh" not in steps.read_text(
        encoding="utf-8"
    ):
        failures.append("bio-core job no longer delegates the Rust supply-chain scan")
    if not scanner.is_file():
        failures.append("scripts/verify-bio-core-supply-chain.sh is missing")
    else:
        text = scanner.read_text(encoding="utf-8")
        for tool in ("cargo audit", "cargo deny"):
            if tool not in text:
                failures.append(f"supply-chain script no longer runs {tool!r}")
    policy = ROOT / "dependency-governance.json"
    if not policy.is_file():
        failures.append("dependency-governance.json is missing")
    else:
        registered = foreign_cargo_analyzers(policy)
        if registered:
            failures.append(
                "a cargo-* analyzer was registered in dependency-governance.json "
                f"(checks: {', '.join(registered)}); "
                "the release lane must have exactly one Rust finding set"
            )

    # The supply-chain scanner is a separate `bash` process from the wheel
    # builder; verify-bio-core.sh's `export PATH=...` does not propagate to it.
    # Both must resolve the same bootstrapped rustup storage, or the job fails
    # with "cargo unavailable" after the wheel has already been built.
    cargo_env = (
        'export CARGO_HOME="${CARGO_HOME:-${TMPDIR:-/tmp}/soymutdb-cargo}"',
        'export RUSTUP_HOME="${RUSTUP_HOME:-${TMPDIR:-/tmp}/soymutdb-rustup}"',
        'export PATH="${CARGO_HOME}/bin:${PATH}"',
    )
    for relative in ("scripts/verify-bio-core.sh", "scripts/verify-bio-core-supply-chain.sh"):
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"missing source file: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        for line in cargo_env:
            if line not in text:
                failures.append(
                    f"{relative} lost its shared cargo resolution: {line!r}"
                )

    # Finding cargo is not enough: rustup still has to pick a channel. Rust is
    # bootstrapped with `--default-toolchain none`, so a channel exists ONLY if
    # the scanner pins one explicitly or runs cargo inside the crate, where
    # rust-toolchain.toml selects it. A bare `cargo install` at the repo root
    # fails with "no default is configured" (cnb-h85-1k6kahbov, the run after
    # the cargo-not-found fix).
    scanner_path = ROOT / "scripts" / "verify-bio-core-supply-chain.sh"
    if scanner_path.is_file():
        scanner_text = scanner_path.read_text(encoding="utf-8")
        pins_channel = "export RUSTUP_TOOLCHAIN=" in scanner_text
        # Presence of `${CRATE_DIR}` is not enough, and neither is the
        # start-of-line spelling: a wrapper (`command cargo`, `env cargo`), a
        # second `cd`, or a line continuation hides the identical failure, so
        # judge the token's POSITION instead. See cargo_outside_crate().
        for line_no, line in enumerate(scanner_text.splitlines(), start=1):
            stripped = line.strip()
            # `step "..."` is a progress message; it never runs anything.
            if stripped.startswith("#") or stripped.startswith("step ") or pins_channel:
                continue
            if cargo_outside_crate(stripped):
                failures.append(
                    "verify-bio-core-supply-chain.sh runs cargo without the crate "
                    f"directory (line {line_no}); rustup cannot resolve the pin: "
                    f"{stripped!r}"
                )

    # A scanner that cannot read the advisory database is not a gate. Pinned-low
    # is a red gate, never a pass. The default must be a plain x.y.z string: a
    # caller overrides it through the environment, the committed value cannot
    # depend on one.
    if scanner_path.is_file():
        match = re.search(
            r"SOYMUTDB_BIO_CORE_CARGO_AUDIT:-([0-9]+\.[0-9]+\.[0-9]+)",
            scanner_path.read_text(encoding="utf-8"),
        )
        if match is None:
            failures.append("verify-bio-core-supply-chain.sh lost its cargo-audit pin")
        elif match.group(1) != AUDIT_PIN:
            if tuple(int(part) for part in match.group(1).split(".")) < AUDIT_FLOOR:
                failures.append(
                    f"cargo-audit {match.group(1)} is pinned below "
                    f"{'.'.join(map(str, AUDIT_FLOOR))}: older scanners cannot parse "
                    "CVSS 4.0 advisories and fail with 'unsupported CVSS version: 4.0'"
                )
            else:
                failures.append(
                    f"cargo-audit must stay pinned to {AUDIT_PIN}, got "
                    f"{match.group(1)}: the finding set must not drift between runs"
                )

    # The cargo-deny pin gets the same treatment as the cargo-audit pin: it is
    # the other half of the same advisory-database parser, and leaving it
    # unguarded is exactly how 0.18.4 survived a green local suite while the
    # job died parsing the database.
    if scanner_path.is_file():
        deny_text = scanner_path.read_text(encoding="utf-8")
        deny_match = re.search(
            r"SOYMUTDB_BIO_CORE_CARGO_DENY:-([0-9]+\.[0-9]+\.[0-9]+)",
            deny_text,
        )
        if deny_match is None:
            failures.append("verify-bio-core-supply-chain.sh lost its cargo-deny pin")
        elif deny_match.group(1) != DENY_PIN:
            if tuple(int(part) for part in deny_match.group(1).split(".")) < DENY_FLOOR:
                failures.append(
                    f"cargo-deny {deny_match.group(1)} is pinned below "
                    f"{'.'.join(map(str, DENY_FLOOR))}: older scanners link rustsec "
                    "-> cvss 2.1.0 and fail with 'unsupported CVSS version: 4.0'"
                )
            else:
                failures.append(
                    f"cargo-deny must stay pinned to {DENY_PIN}, got "
                    f"{deny_match.group(1)}: the finding set must not drift between runs"
                )

    # A declaration pin is not an install contract. `cargo install --version
    # "0.22.2"` is a caret requirement (^0.22.2), so the runner can install a
    # later 0.22.x while the committed default still reads 0.22.2. The "="
    # operator makes it exact; keep both install lines that way. This guard
    # cannot verify the resolved version offline -- the runner log owns that.
    if scanner_path.is_file():
        install_text = scanner_path.read_text(encoding="utf-8")
        for tool_var in ("AUDIT_VERSION", "DENY_VERSION"):
            exact = f'--version "=${{{tool_var}}}"'
            if exact not in install_text:
                failures.append(
                    f"verify-bio-core-supply-chain.sh installs {tool_var} with a "
                    "caret requirement, not an exact pin: use "
                    f'{exact!r} so the runner cannot resolve a different release'
                )

    # A gate that fails silently is worse than no gate: cnb-7qb-1k6kbvp1e saw
    # cargo deny exit 1 with an empty runner log, because the output only ever
    # reached a file. The failure branch has to print the evidence.
    if scanner_path.is_file():
        inner = scanner_path.read_text(encoding="utf-8")
        if "cargo deny check" in inner:
            if 'cargo-deny.txt" >&2' not in inner:
                failures.append(
                    "verify-bio-core-supply-chain.sh hides the cargo deny failure path: "
                    "it must echo cargo-deny.txt to stderr instead of exiting silently"
                )

    # cargo deny with no config falls back to a default with an EMPTY license
    # allowlist, so every crate is rejected as "not explicitly allowed". The
    # committed policy must exist and be the one the scanner uses: it is the
    # failure that follows the CVSS-4.0 parser fix (2649f71f), once cargo deny
    # can finally read the advisory database.
    deny_cfg = ROOT / "packages" / "bio-core" / "deny.toml"
    if not deny_cfg.is_file():
        failures.append("packages/bio-core/deny.toml is missing (cargo deny would use an empty license allowlist)")
    else:
        text = deny_cfg.read_text(encoding="utf-8")
        try:
            policy = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            failures.append(f"deny.toml is not valid TOML: {exc}")
            policy = {}
        if "allow = [" not in text or '"MIT"' not in text:
            failures.append("deny.toml no longer carries an explicit license allowlist")
        if policy.get("sources", {}).get("unknown-registry") != "deny":
            failures.append("deny.toml must reject unknown crate registries")
        # A git source is a second, unreviewed provenance path. `unknown-git =
        # "deny"` is a parsed lint level, not a substring: "allow" flips it to
        # a silent pass while the byte-string check above stays green.
        if policy.get("sources", {}).get("unknown-git") != "deny":
            failures.append("deny.toml must reject unknown git sources")
        # The three advisory IDs this graph cannot fix are ignored BY ID. A
        # scope spelling is a blanket in one direction or the other: measured
        # with cargo-deny 0.18.9, `transitive` still fails them (their direct
        # dependent is `bio`, not this crate) and `workspace` silences every
        # unmaintained crate reached through a direct dependency.
        advisories = policy.get("advisories", {})
        if advisories.get("unmaintained") != "all":
            failures.append(
                'deny.toml must keep unmaintained = "all" and ignore the three '
                "pinned-bio advisories by ID; a scope spelling is a blanket"
            )
        for advisory in ("RUSTSEC-2025-0058", "RUSTSEC-2025-0057", "RUSTSEC-2024-0436"):
            if not any(entry.get("id") == advisory for entry in advisories.get("ignore", [])):
                failures.append(f"deny.toml lost the reasoned ignore for {advisory}")
        if advisories.get("yanked") != "deny":
            failures.append("deny.toml must keep yanked crates a hard failure")
        # Duplicates are named, not blanket-allowed: `multiple-versions = "allow"`
        # would let a new duplicate major version in behind an old decision.
        bans = policy.get("bans", {})
        if bans.get("multiple-versions") != "deny":
            failures.append(
                "deny.toml must deny new duplicate versions; a blanket "
                '`multiple-versions = "allow"` lets one in behind an old decision'
            )
        # `wildcards = "deny"` stops a new dependency from pinning `*`. It is
        # a parsed lint level too; a substring check for "skip = [" cannot see
        # `wildcards` being flipped to "allow".
        if bans.get("wildcards") != "deny":
            failures.append("deny.toml must reject wildcard version requirements")
        # The `skip` list must name the EXACT duplicate versions in Cargo.lock.
        # "skip = [" as a substring lets one entry be deleted, and a bare
        # `crate = "ryu"` exception (no @version) would cover every future
        # ryu release with a license decision made about 1.0.23 only.
        lock = ROOT / "packages" / "bio-core" / "Cargo.lock"
        expected: set[str] | None = None
        if not lock.is_file():
            failures.append("packages/bio-core/Cargo.lock is missing; the deny.toml skip list cannot be checked")
        else:
            try:
                packages = tomllib.loads(lock.read_text(encoding="utf-8")).get("package", [])
                seen: dict[str, list[str]] = {}
                for pkg in packages:
                    seen.setdefault(pkg["name"], []).append(pkg["version"])
                expected = {
                    f"{name}@{version}"
                    for name, versions in seen.items()
                    if len(versions) > 1
                    for version in versions
                }
            except (tomllib.TOMLDecodeError, KeyError) as exc:
                failures.append(f"deny.toml skip list cannot be checked: Cargo.lock is unreadable: {exc}")
        skip = bans.get("skip")
        if not isinstance(skip, list):
            failures.append("deny.toml must name the duplicate versions it accepts in `skip`")
        elif expected is not None:
            named = {entry.get("crate") for entry in skip if isinstance(entry, dict)}
            if named != expected:
                missing = sorted(expected - named)
                extra = sorted(named - expected)
                failures.append(
                    "deny.toml skip list must name exactly the duplicate versions in "
                    f"Cargo.lock (missing: {missing}, stale: {extra})"
                )
        # BSL-1.0 is granted to exactly ryu 1.0.23, whose dual declaration
        # ("Apache-2.0 OR BSL-1.0") was reviewed. `crate = "ryu"` without a
        # version would carry that decision onto every future ryu release.
        exceptions = policy.get("licenses", {}).get("exceptions")
        bsl = [
            entry for entry in (exceptions if isinstance(exceptions, list) else [])
            if isinstance(entry, dict) and "BSL-1.0" in (entry.get("allow") or [])
        ]
        if len(bsl) != 1 or "@" not in str(bsl[0].get("crate", "")):
            failures.append(
                "deny.toml must grant BSL-1.0 to one version-pinned crate "
                '(crate = "ryu@1.0.23"); an unversioned exception outlives the review'
            )

    # The policy and the invocation have to agree. deny.toml deliberately keeps
    # maintenance warnings visible instead of fatal; passing `--deny warnings`
    # from the script would override the committed policy from outside and turn
    # an unused allowlist entry into a build failure.
    if scanner_path.is_file():
        invocation = scanner_path.read_text(encoding="utf-8")
        if "cargo deny check --deny warnings" in invocation:
            failures.append(
                "verify-bio-core-supply-chain.sh passes --deny warnings, which "
                "overrides the committed deny.toml policy instead of using it"
            )

    # The verdict used to live in a heredoc no gate could import and was
    # fail-open on three shapes. It is now a real module with a behavioural
    # suite; neither the delegation nor the wiring may be removed.
    checker = ROOT / "scripts" / "check_bio_core_supply_chain.py"
    if not checker.is_file():
        failures.append("scripts/check_bio_core_supply_chain.py is missing")
    else:
        module = checker.read_text(encoding="utf-8")
        for token in ("audit_rc != 0", "deny_rc != 0",
                      'vulnerabilities.get("count")', "audit_findings"):
            if token not in module:
                failures.append(f"the supply-chain verdict lost {token!r}")
        if '"error" in' in module or "deny_text" in module:
            failures.append("the supply-chain verdict went back to stdout substring matching")
        # The signed report must name the binaries that ran. A hardcoded
        # placeholder ("version": "pinned") is a declaration, not an
        # observation: `=` pins the install requirement but cannot prove which
        # binary produced the clean verdict. Keep the probe -> verdict binding.
        # Require the DEFINITIONS, not bare tokens: a call site alone keeps
        # "read_observations" in the file even when the function is gone, and
        # a guard that only greps a name is decoration.
        for token in ("def read_observations(", "def validate_observations(",
                      "def parse_scanner_version(", "executed as"):
            if token not in module:
                failures.append(f"the supply-chain verdict lost {token!r}")
        # Match the placeholder as a STRING LITERAL, not prose: the docstring
        # legitimately quotes it. A re-hardcoded value is an ast.Constant.
        try:
            verdict_ast = ast.parse(module)
        except SyntaxError as exc:
            failures.append(f"the supply-chain verdict is not valid Python: {exc}")
        else:
            constants = {
                node.value for node in ast.walk(verdict_ast)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            }
            if "pinned" in constants:
                failures.append("the supply-chain verdict hardcodes a placeholder version again")
    if scanner_path.is_file():
        text = scanner_path.read_text(encoding="utf-8")
        if 'vulnerabilities.get("found"' in text or '"error" in deny_text' in text:
            failures.append("the fail-open heredoc verdict returned to the scanner")
        if "check_bio_core_supply_chain.py" not in text:
            failures.append("the scanner no longer delegates its verdict to the checkable module")
        for arg in ('"${AUDIT_RC}"', '"${DENY_RC}"', '|| AUDIT_RC=$?', '|| DENY_RC=$?'):
            if arg not in text:
                failures.append(f"the scanner no longer captures/passes {arg}")
        for probe in ("cargo audit --version", "cargo deny --version"):
            if probe not in text:
                failures.append(f"the scanner stopped observing {probe!r}")
        for arg in ("--audit-version-file", "--deny-version-file",
                    "--expect-audit", "--expect-deny"):
            if arg not in text:
                failures.append(f"the scanner stopped passing {arg!r} to the verdict")
    if not (ROOT / "scripts" / "test_bio_core_supply_chain.py").is_file():
        failures.append("scripts/test_bio_core_supply_chain.py is missing")

    # A guard no gate calls is decoration. Both invocations must stay in the
    # contracts layer: the static/self-test validator AND the negative suite.
    smoke = ROOT / "scripts" / "smoke.sh"
    if smoke.is_file():
        text = smoke.read_text(encoding="utf-8")
        for marker in (
            "scripts/check_bio_core_wheel_abi.py --ledger --self-test",
            "scripts/test_bio_core_wheel_abi.py",
            "scripts/test_bio_core_supply_chain.py",
        ):
            if marker not in text:
                failures.append(f"smoke.sh contracts layer no longer runs {marker!r}")
    else:
        failures.append("scripts/smoke.sh is missing")
    return failures


def self_test() -> list[str]:
    """Each negative must be rejected; the positives must be accepted."""
    failures: list[str] = []
    negatives = [
        ("cp314", f"{DIST}-0.1.2-cp314-cp314-manylinux_2_34_x86_64.whl", "amd64"),
        ("abi3", f"{DIST}-0.1.2-cp315-abi3-manylinux_2_34_x86_64.whl", "amd64"),
        ("foreign arch", f"{DIST}-0.1.2-cp315-cp315-manylinux_2_34_aarch64.whl", "amd64"),
        ("pure python", f"{DIST}-0.1.2-py3-none-any.whl", "amd64"),
        ("musllinux", f"{DIST}-0.1.2-cp315-cp315-musllinux_1_2_x86_64.whl", "amd64"),
        ("macos", f"{DIST}-0.1.2-cp315-cp315-macosx_11_0_arm64.whl", "arm64"),
        ("legacy alias wrong arch", f"{DIST}-0.1.2-cp315-cp315-manylinux2014_x86_64.whl", "arm64"),
    ]
    for label, name, arch in negatives:
        if not filename_failures(name, arch):
            failures.append(f"self-test negative {label!r} was accepted")
    positives = [
        (f"{DIST}-0.1.2-cp315-cp315-manylinux_2_34_x86_64.whl", "amd64"),
        (f"{DIST}-0.1.2-cp315-cp315-manylinux_2_41_aarch64.whl", "arm64"),
        (f"{DIST}-0.1.2-cp315-cp315-linux_aarch64.whl", "arm64"),
        (f"{DIST}-0.1.2-cp315-cp315-manylinux2014_x86_64.whl", "amd64"),
    ]
    for name, arch in positives:
        if filename_failures(name, arch):
            failures.append(f"self-test positive {name!r} ({arch}) was rejected")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", action="store_true", help="validate the committed ABI ledger")
    parser.add_argument("--wheel", type=Path, help="validate a built wheel's tag + WHEEL metadata")
    parser.add_argument("--arch", choices=ARCHES, help="image architecture for --wheel")
    parser.add_argument("--self-test", action="store_true", help="run the synthetic negatives")
    args = parser.parse_args(argv)

    if args.wheel and not args.arch:
        parser.error("--wheel requires --arch")
    if args.arch and not args.wheel:
        parser.error("--arch requires --wheel")

    failures: list[str] = []
    if args.self_test:
        failures += self_test()
    if args.ledger or not (args.wheel or args.self_test):
        if not LEDGER.is_file():
            failures.append(f"missing ABI ledger: {LEDGER.relative_to(ROOT)}")
        else:
            failures += ledger_failures(LEDGER.read_text(encoding="utf-8"))
        failures += source_failures()
    if args.wheel:
        if not args.wheel.is_file():
            failures.append(f"wheel not found: {args.wheel}")
        else:
            failures += inspect_wheel(args.wheel, args.arch)

    for line in failures:
        print(f"FAIL: {line}", file=sys.stderr)
    if failures:
        return 1
    scope = []
    if args.self_test:
        scope.append("self-test")
    if args.ledger or not (args.wheel or args.self_test):
        scope.append("ledger + source contract")
    if args.wheel:
        scope.append(f"wheel tag ({args.arch})")
    print(f"bio-core wheel ABI tag [{' / '.join(scope)}]: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
