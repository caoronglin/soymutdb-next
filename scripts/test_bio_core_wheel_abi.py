"""Synthetic-tree proofs for the bio-core wheel ABI / platform-tag guard.

Each negative must be rejected. The guard reads committed bytes and parses
PEP 427 filenames, so these ablations need no Rust, no wheel and no Docker.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest

from scripts import check_bio_core_wheel_abi as guard

DIST = "soymutdb_bio_core"


def wheel_name(python: str = "cp315", abi: str = "cp315", platform: str = "manylinux_2_34_x86_64") -> str:
    return f"{DIST}-0.1.2-{python}-{abi}-{platform}.whl"


def make_wheel(path: Path, name: str, tag: str) -> Path:
    target = path / name
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(
            f"{DIST}-0.1.2.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: false\nTag: " + tag + "\n",
        )
    return target


def test_positive_amd64_wheel_passes(tmp_path: Path) -> None:
    path = make_wheel(tmp_path, wheel_name(), "cp315-cp315-manylinux_2_34_x86_64")
    assert guard.inspect_wheel(path, "amd64") == []


def test_positive_arm64_wheel_passes(tmp_path: Path) -> None:
    name = wheel_name(platform="manylinux_2_41_aarch64")
    path = make_wheel(tmp_path, name, "cp315-cp315-manylinux_2_41_aarch64")
    assert guard.inspect_wheel(path, "arm64") == []


def test_cp314_wheel_is_rejected(tmp_path: Path) -> None:
    name = wheel_name(python="cp314", abi="cp314")
    path = make_wheel(tmp_path, name, "cp314-cp314-manylinux_2_34_x86_64")
    assert any("cp315" in f for f in guard.inspect_wheel(path, "amd64"))


def test_abi3_wheel_is_rejected(tmp_path: Path) -> None:
    name = wheel_name(abi="abi3")
    path = make_wheel(tmp_path, name, "cp315-abi3-manylinux_2_34_x86_64")
    assert any("cp315" in f for f in guard.inspect_wheel(path, "amd64"))


def test_foreign_architecture_is_rejected(tmp_path: Path) -> None:
    name = wheel_name(platform="manylinux_2_34_x86_64")
    path = make_wheel(tmp_path, name, "cp315-cp315-manylinux_2_34_x86_64")
    assert any("aarch64" in f for f in guard.inspect_wheel(path, "arm64"))


def test_pure_python_wheel_is_rejected(tmp_path: Path) -> None:
    name = wheel_name(python="py3", abi="none", platform="any")
    path = make_wheel(tmp_path, name, "py3-none-any")
    assert any("glibc/linux native tag" in f for f in guard.inspect_wheel(path, "amd64"))


def test_musllinux_wheel_is_rejected(tmp_path: Path) -> None:
    name = wheel_name(platform="musllinux_1_2_x86_64")
    path = make_wheel(tmp_path, name, "cp315-cp315-musllinux_1_2_x86_64")
    assert any("glibc/linux native tag" in f for f in guard.inspect_wheel(path, "amd64"))


def test_renamed_wheel_with_lying_metadata_is_rejected(tmp_path: Path) -> None:
    # Filename says x86_64, internal Tag says aarch64: a filename-only guard
    # would pass this, the archive cross-check must not.
    name = wheel_name(platform="manylinux_2_34_x86_64")
    path = make_wheel(tmp_path, name, "cp315-cp315-manylinux_2_34_aarch64")
    assert any("WHEEL metadata" in f for f in guard.inspect_wheel(path, "amd64"))


def test_ledger_without_arm64_row_is_rejected() -> None:
    text = (guard.ROOT / "docs/dev/bio-core-wheel-abi-tags.md").read_text(encoding="utf-8")
    broken = text.replace("| `arm64` |", "| (arm64 row removed) |")
    assert any("no row for arm64" in f for f in guard.ledger_failures(broken))


def test_ledger_without_pending_marker_is_rejected() -> None:
    text = (guard.ROOT / "docs/dev/bio-core-wheel-abi-tags.md").read_text(encoding="utf-8")
    assert any("pending" in f for f in guard.ledger_failures(text.replace("pending", "done")))


def test_ledger_row_machine_column_is_checked_per_arch() -> None:
    """A token surviving elsewhere in the text must not vouch for its row.

    The old check asked whether `_{machine}` appeared anywhere in the ledger,
    so flipping ONLY the arm64 machine column to x86_64 stayed green while the
    expected-tag column still said aarch64. Each row now has to name its own
    machine in both the machine cell and the expected-tag cell.
    """
    text = (guard.ROOT / "docs/dev/bio-core-wheel-abi-tags.md").read_text(encoding="utf-8")
    assert guard.ledger_failures(text) == []
    broken = text.replace("| `arm64` | `aarch64` |", "| `arm64` | `x86_64` |", 1)
    failures = guard.ledger_failures(broken)
    assert any("machine column" in f for f in failures), failures
    assert any("does not name its machine" in f for f in failures), failures


def test_ledger_row_expected_tag_is_checked_per_arch() -> None:
    text = (guard.ROOT / "docs/dev/bio-core-wheel-abi-tags.md").read_text(encoding="utf-8")
    broken = text.replace(
        "manylinux_<major>_<minor>_aarch64", "manylinux_<major>_<minor>_x86_64", 1
    )
    failures = guard.ledger_failures(broken)
    assert any("expected tag" in f for f in failures), failures


def test_ledger_amd64_row_machine_column_is_checked_too() -> None:
    text = (guard.ROOT / "docs/dev/bio-core-wheel-abi-tags.md").read_text(encoding="utf-8")
    broken = text.replace("| `amd64` | `x86_64` |", "| `amd64` | `aarch64` |", 1)
    failures = guard.ledger_failures(broken)
    assert any("amd64 machine column" in f for f in failures), failures


def _shared_script_names() -> list[str]:
    """The canonical shared-script list, read from the contract suite.

    check_bio_core_wheel.shared_scripts() parses it out of
    test_ci_job_contracts.py; a synthetic tree has to stage the same file set or
    --static reports the missing ones instead of answering about the file under
    test.
    """
    source = (Path(guard.__file__).resolve().parent / "test_ci_job_contracts.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r"SHARED_SCRIPTS\s*=\s*\((.*?)\n\)", source, re.DOTALL)
    assert match is not None, "SHARED_SCRIPTS not found in test_ci_job_contracts.py"
    return re.findall(r'"([^"]+)"', match.group(1))


def _synthetic_tree(tmp_path: Path) -> Path:
    import shutil

    # The committed tree, not guard.ROOT: monkeypatch swaps that, and a test
    # that builds a second synthetic tree would otherwise copy from the first.
    source = Path(guard.__file__).resolve().parent.parent
    fake = tmp_path / "repo"
    (fake / "scripts").mkdir(parents=True)
    (fake / "packages" / "bio-core").mkdir(parents=True)
    (fake / "docs" / "dev").mkdir(parents=True)
    for name in (
        "verify-bio-core.sh",
        "verify-backend-tests.sh",
        "ci-job-steps.sh",
        "verify-bio-core-supply-chain.sh",
        "check_bio_core_supply_chain.py",
        "test_bio_core_supply_chain.py",
        "smoke.sh",
        # --static reads the canonical SHARED_SCRIPTS list out of this suite, and
        # then reads every shared script it names. Without it, check_static()
        # raises FileNotFoundError instead of returning a verdict, so the
        # negative cases below would "pass" on an exception rather than a red.
        "test_ci_job_contracts.py",
    ):
        shutil.copy(source / "scripts" / name, fake / "scripts" / name)
    for name in ("pyproject.toml", "deny.toml", "Cargo.lock"):
        shutil.copy(
            source / "packages/bio-core" / name, fake / "packages/bio-core" / name
        )
    # --static loops over every shared script, so the tree has to look like one:
    # a script that is absent is reported as a failure, and a case that asserts
    # "reject" would then go green for the wrong reason while "accept" goes red.
    for name in _shared_script_names():
        target = fake / name
        if target.exists():
            continue
        (target.parent).mkdir(parents=True, exist_ok=True)
        shutil.copy(source / name, target)
    shutil.copy(source / "dependency-governance.json", fake / "dependency-governance.json")
    # --static also follows every documentation citation in every shared
    # script, so the docs those scripts cite have to be present. Copying them
    # keeps this fixture honest about a real tree instead of patching around a
    # dangling link.
    shutil.copytree(source / "docs", fake / "docs", dirs_exist_ok=True)
    return fake


def test_source_contract_rejects_lost_cp315_glob(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _synthetic_tree(tmp_path)
    (fake / "scripts/verify-bio-core.sh").write_text("maturin build\n", encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("no longer names" in f for f in guard.source_failures())


def test_source_contract_rejects_a_bare_cargo_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Finding cargo is not running it: rustup needs a channel, and the only
    # ones available are CRATE_DIR's rust-toolchain.toml or an explicit pin.
    # One bare `cargo install` at the repo root is enough to blow up the job
    # (cnb-h85-1k6kahbov), so a partial in-crate migration must stay red.
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    scanner.write_text(
        scanner.read_text(encoding="utf-8").replace(
            '(cd "${CRATE_DIR}" && cargo audit --json)',
            "cargo audit --json",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("without the crate directory" in f for f in guard.source_failures())


def test_source_contract_rejects_an_unreadable_audit_scanner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A scanner below the CVSS 4.0 floor dies parsing the advisory database
    # before it looks at a single crate (cnb-elt-1k6kb3soh). Pinned-low is a
    # red gate, not a pass.
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    scanner.write_text(
        scanner.read_text(encoding="utf-8").replace(
            "SOYMUTDB_BIO_CORE_CARGO_AUDIT:-0.22.2",
            "SOYMUTDB_BIO_CORE_CARGO_AUDIT:-0.21.2",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("unsupported CVSS version" in f for f in guard.source_failures())


def test_source_contract_rejects_the_cvss_2_1_audit_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Anything below the floor is a red gate. 0.21.2 is the measured CVSS 4.0
    # failure (cnb-k4a-1k6kbhl3c, which installed 0.21.2 -- not 0.22.1);
    # 0.22.1 also died (cnb-7qb-1k6kbvp1e) with its reason redirected out of
    # the stage log. 0.22.2 is the first measured-clean audit run.
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    scanner.write_text(
        scanner.read_text(encoding="utf-8").replace(
            "SOYMUTDB_BIO_CORE_CARGO_AUDIT:-0.22.2",
            "SOYMUTDB_BIO_CORE_CARGO_AUDIT:-0.22.1",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("unsupported CVSS version" in f for f in guard.source_failures())


def test_source_contract_rejects_an_environment_default_audit_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A default of `${SOME_VERSION}` cannot be compared against the floor, and
    # letting the comparison fail open is how a low pin sneaks back in.
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    scanner.write_text(
        scanner.read_text(encoding="utf-8").replace(
            "SOYMUTDB_BIO_CORE_CARGO_AUDIT:-0.22.2",
            'SOYMUTDB_BIO_CORE_CARGO_AUDIT:-${SOYMUTDB_AUDIT_DEFAULT}"',
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("lost its cargo-audit pin" in f for f in guard.source_failures())


def test_source_contract_rejects_an_unreadable_deny_scanner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other half of the same wall: cargo-deny reads the advisory database
    # through rustsec, so 0.18.4 (cvss 2.1.0) aborts on the first CVSS 4.0
    # entry (cnb-qf2-1k6kc4hoo). The cargo-audit floor did not cover it.
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    scanner.write_text(
        scanner.read_text(encoding="utf-8").replace(
            "SOYMUTDB_BIO_CORE_CARGO_DENY:-0.18.9",
            "SOYMUTDB_BIO_CORE_CARGO_DENY:-0.18.4",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("cargo-deny 0.18.4 is pinned below" in f for f in guard.source_failures())


def test_source_contract_rejects_a_deny_pin_below_the_first_0_18_9(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 0.18.5 checks out as a number and is still red: it resolves rustsec
    # 0.30.4, the resolution that carries cvss 2.1.0. The floor is a
    # resolution, not a "somebody bumped it" gesture.
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    scanner.write_text(
        scanner.read_text(encoding="utf-8").replace(
            "SOYMUTDB_BIO_CORE_CARGO_DENY:-0.18.9",
            "SOYMUTDB_BIO_CORE_CARGO_DENY:-0.18.5",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("cargo-deny 0.18.5 is pinned below" in f for f in guard.source_failures())


def test_source_contract_rejects_an_environment_default_deny_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Same reasoning as the cargo-audit variant: a substituted default cannot
    # be compared, and a comparison that is allowed to fail open is a pin that
    # is allowed to disappear.
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    scanner.write_text(
        scanner.read_text(encoding="utf-8").replace(
            "SOYMUTDB_BIO_CORE_CARGO_DENY:-0.18.9",
            'SOYMUTDB_BIO_CORE_CARGO_DENY:-${SOYMUTDB_DENY_DEFAULT}"',
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("lost its cargo-deny pin" in f for f in guard.source_failures())


def test_source_contract_accepts_a_conditional_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The deny command runs in-crate and captures its exit status; the loud
    # `if (( DENY_RC != 0 ))` branch prints the evidence to stderr. The
    # positional rule must not misread those lines as out-of-crate cargo runs.
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    text = scanner.read_text(encoding="utf-8")
    assert "DENY_RC=$?" in text, "the scanner stopped capturing deny's exit status"
    assert "if (( DENY_RC != 0 )); then" in text, "the scanner stopped failing loudly"
    scanner.write_text(text, encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", fake)
    assert not any("without the crate directory" in f for f in guard.source_failures())


def test_source_contract_rejects_the_failure_path_going_dark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # cnb-7qb-1k6kbvp1e: cargo deny exits 1 and the runner log shows nothing
    # because the output only ever landed in a file. The failure branch has to
    # print what failed. Match the marker instead of the whole shell line so the
    # test cannot rot when the quoting around it changes.
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    text = scanner.read_text(encoding="utf-8")
    kept = [line for line in text.splitlines(keepends=True) if "cargo-deny.txt\" >&2" not in line]
    assert len(kept) < len(text.splitlines(keepends=True)), "the failure branch vanished upstream"
    scanner.write_text("".join(kept), encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("hides the cargo deny failure path" in f for f in guard.source_failures())


def test_source_contract_rejects_overriding_the_deny_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # deny.toml is the policy, and it deliberately keeps maintenance warnings
    # visible instead of fatal. `--deny warnings` on the command line overrides
    # the committed file from outside, so the two can disagree without anyone
    # noticing until an unused allowlist entry breaks the build.
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    scanner.write_text(
        scanner.read_text(encoding="utf-8").replace(
            "cargo deny check)",
            "cargo deny check --deny warnings)",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("overrides the committed deny.toml" in f for f in guard.source_failures())


@pytest.mark.parametrize(
    "check",
    [
        {"name": "cargo-deny", "category": "cargo-deny",
         "command": ["cargo", "deny", "check"]},
        {"name": "rust-audit", "category": "rust-audit",
         "command": ["cargo", "audit", "--json"]},
        {"name": "cargo-udeps", "category": "cargo-udeps",
         "command": ["cargo", "udeps"]},
        {"name": "cargo_geiger", "category": "cargo_geiger"},
        {"name": "deny check", "category": "vulnerabilities",
         "command": ["sh", "-c", "cargo deny check"]},
    ],
)
def test_source_contract_rejects_duplicate_governance_analyzer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, check: dict
) -> None:
    """Registering a SECOND real cargo analyzer must turn the guard red.

    The old guard matched only the literal ``"cargo audit"`` bytes in the raw
    policy file, so a check named ``cargo-deny`` (one of the two tools this
    lane actually runs) registered cleanly and produced a second finding set
    for the same Cargo.lock while every local gate stayed green.
    """
    fake = _synthetic_tree(tmp_path)
    policy_file = fake / "dependency-governance.json"
    config = json.loads(policy_file.read_text(encoding="utf-8"))
    config["checks"].append(check)
    policy_file.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", fake)
    failures = guard.source_failures()
    assert any("exactly one Rust finding set" in f for f in failures), failures
    assert check["name"] in " ".join(failures), failures


def test_source_contract_accepts_the_committed_governance_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The negatives above are only meaningful if the committed policy is clean."""
    fake = _synthetic_tree(tmp_path)
    monkeypatch.setattr(guard, "ROOT", fake)
    assert guard.foreign_cargo_analyzers(fake / "dependency-governance.json") == []
    assert not any("exactly one Rust finding set" in f for f in guard.source_failures())


@pytest.mark.parametrize(
    "broken",
    ["", "not json", '{"schema_version": 1}', '{"checks": "oops"}'],
)
def test_source_contract_fails_closed_on_malformed_governance_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broken: str
) -> None:
    """A policy the guard cannot parse must never read as "no analyzers"."""
    fake = _synthetic_tree(tmp_path)
    (fake / "dependency-governance.json").write_text(broken, encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("exactly one Rust finding set" in f for f in guard.source_failures())


def test_contracts_layer_rejects_duplicate_governance_analyzer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The independent unittest door must catch the same registration.

    It reads committed bytes rather than the guard's own self-test, so it has
    to stay red even if someone edits the guard to lie. Both doors share the
    structural parser so their verdicts cannot drift apart.
    """
    import unittest

    from scripts import test_ci_job_contracts as contracts

    fake = _synthetic_tree(tmp_path)
    policy_file = fake / "dependency-governance.json"
    original = policy_file.read_text(encoding="utf-8")
    config = json.loads(original)
    config["checks"].append(
        {"name": "cargo-deny", "category": "cargo-deny",
         "command": ["cargo", "deny", "check"]}
    )
    policy_file.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", fake)
    monkeypatch.setattr(contracts, "ROOT", fake)

    method = "test_bio_core_wheel_abi_ledger_is_enforced_by_the_contracts_layer"
    case = contracts.DeliveryArchitectureTests(method)
    result = unittest.TestResult()
    case.run(result)
    assert result.failures or result.errors, "contracts door stayed green"

    # Restore the exact captured bytes and prove the same door is green again.
    policy_file.write_text(original, encoding="utf-8")
    result = unittest.TestResult()
    case = contracts.DeliveryArchitectureTests(method)
    case.run(result)
    assert not (result.failures or result.errors), "restored policy must be green"


def test_source_contract_rejects_unwired_smoke_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _synthetic_tree(tmp_path)
    (fake / "scripts/smoke.sh").write_text(
        (fake / "scripts/smoke.sh")
        .read_text(encoding="utf-8")
        .replace("scripts/check_bio_core_wheel_abi.py --ledger --self-test", "true"),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("no longer runs" in f for f in guard.source_failures())


def test_guard_self_test_is_clean() -> None:
    assert guard.self_test() == []


def test_source_contract_requires_shared_cargo_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The wheel builder and the supply-chain scanner are separate bash
    # processes. If either loses the rustup storage export, the second script
    # cannot find cargo and the bio-core job fails after the wheel is built.
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    scanner.write_text(
        scanner.read_text(encoding="utf-8").replace(
            'export CARGO_HOME="${CARGO_HOME:-${TMPDIR:-/tmp}/soymutdb-cargo}"',
            'export CARGO_HOME="/some/other/cargo"',
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("shared cargo resolution" in f for f in guard.source_failures())


def test_source_contract_rejects_a_wrapped_cargo_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `cargo` picks its channel by POSITION: rustup reads rust-toolchain.toml
    # from the current directory. Wrapping the command (`command cargo audit`,
    # `env cargo deny`) or preceding it with a second `cd` puts it back at the
    # unpinned repo root and reproduces cnb-h85-1k6kahbov, even though the line
    # mentions the crate directory.
    wrappers = (
        (
            "command cargo audit --json",
            '(cd "${CRATE_DIR}" && cargo audit --json)'
            ' > "${EVIDENCE_DIR}/cargo-audit.json"',
        ),
        (
            "env cargo deny check",
            '(cd "${CRATE_DIR}" && cargo deny check)'
            ' > "${EVIDENCE_DIR}/cargo-deny.txt" 2>&1',
        ),
        (
            '(cd "${CRATE_DIR}" && cd . && cargo install'
            ' --locked --version "=${AUDIT_VERSION}" cargo-audit)',
            '(cd "${CRATE_DIR}" && cargo install'
            ' --locked --version "=${AUDIT_VERSION}" cargo-audit)',
        ),
    )
    for wrapped, original in wrappers:
        fake = _synthetic_tree(tmp_path / wrapped.split()[0])
        scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
        text = scanner.read_text(encoding="utf-8")
        assert original in text, original
        scanner.write_text(text.replace(original, wrapped, 1), encoding="utf-8")
        monkeypatch.setattr(guard, "ROOT", fake)
        assert any("runs cargo without the crate" in f for f in guard.source_failures()), wrapped


def test_supply_chain_script_finds_cargo_bootstrapped_by_the_sibling_job(
    tmp_path: Path,
) -> None:
    """Behavioural regression for cnb-j3f-1k6k9lt98.

    `verify-bio-core.sh` bootstraps rustup into ${CARGO_HOME}/bin and exports
    PATH inside its own process; the supply-chain scanner is a sibling process
    and inherits neither. Put fake cargo/rustc ONLY in CARGO_HOME/bin, give the
    system PATH no cargo, and run the real script: without the re-export it
    exits immediately with "cargo unavailable". Byte-string guards can be
    satisfied by a comment; this one proves the toolchain is actually found.
    """
    import os
    import subprocess

    # The committed tree, not guard.ROOT: the source-contract tests monkeypatch
    # that attribute and never restore it, and a synthetic tree has no
    # Cargo.lock, so the scanner exits on a different precondition than the one
    # this test is about.
    repo_root = Path(guard.__file__).resolve().parent.parent
    script = repo_root / "scripts/verify-bio-core-supply-chain.sh"
    cargo_home = tmp_path / "soymutdb-cargo"
    bin_dir = cargo_home / "bin"
    bin_dir.mkdir(parents=True)
    for name in ("cargo", "rustc"):
        fake = bin_dir / name
        fake.write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
        fake.chmod(0o755)

    system_path = os.pathsep.join(
        d for d in os.environ.get("PATH", "").split(os.pathsep) if d
    )
    env = {
        "PATH": f"{tmp_path / 'empty-bin'}{os.pathsep}{system_path}",
        "CARGO_HOME": str(cargo_home),
        "RUSTUP_HOME": str(tmp_path / "soymutdb-rustup"),
        "SOYMUTDB_BIO_CORE_EVIDENCE_DIR": str(tmp_path / "evidence"),
    }
    (tmp_path / "empty-bin").mkdir()
    assert not any(
        (Path(d) / "cargo").exists() for d in env["PATH"].split(os.pathsep) if d
    ), "test premise broken: system PATH already has cargo"
    result = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert "cargo unavailable" not in combined, combined
    # The fakes were reached: the first `cargo install` exits 42.
    assert result.returncode != 0
    assert "install pinned cargo audit" in combined, combined


def test_source_contract_rejects_a_blanket_advisory_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `unmaintained = "transitive"` reads like "only transitive crates"; it is
    # measured against the DIRECT DEPENDENT, so those three pinned-bio
    # advisories (which hang off `bio`) fail anyway. "workspace" hides every
    # unmaintained crate behind a direct dependency. Ignoring by ID is the only
    # form that is neither a blanket nor a no-op.
    fake = _synthetic_tree(tmp_path)
    policy = fake / "packages/bio-core/deny.toml"
    policy.write_text(
        policy.read_text(encoding="utf-8").replace(
            'unmaintained = "all"', 'unmaintained = "transitive"'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any('unmaintained = "all"' in f for f in guard.source_failures())


def test_source_contract_rejects_a_blanket_duplicate_version_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `multiple-versions = "allow"` would let a new duplicate major version in
    # behind a decision made about the current lockfile. The named `skip` list
    # is what keeps the next one a decision.
    fake = _synthetic_tree(tmp_path)
    policy = fake / "packages/bio-core/deny.toml"
    policy.write_text(
        policy.read_text(encoding="utf-8").replace(
            'multiple-versions = "deny"', 'multiple-versions = "allow"'
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("multiple-versions" in f for f in guard.source_failures())


def _module_survives_verdict_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old: str, new: str
) -> list[str]:
    """Mutate the verdict MODULE (not the guard) and return what the guard says.

    The final gate for the fail-open fixes has to be the guard, so this runs it
    against a tree whose check_bio_core_supply_chain.py is the only thing that
    changed. Asserting the mutation applied keeps a token rename from turning
    this into a test of the unmodified module.
    """
    fake = _synthetic_tree(tmp_path)
    module = fake / "scripts/check_bio_core_supply_chain.py"
    original = module.read_text(encoding="utf-8")
    assert old in original, f"the verdict module no longer contains {old!r}"
    module.write_text(original.replace(old, new, 1), encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", fake)
    failures = guard.source_failures()
    if not failures:
        module.write_text(original, encoding="utf-8")
        raise AssertionError(f"source_failures() accepted the module with {old!r} -> {new!r}")
    return failures


def test_source_contract_rejects_a_verdict_that_ignores_the_audit_exit_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # cnb-atb-1k6kecm5a: `cargo audit` was judged by `vulnerabilities.found`
    # and its exit status was dropped. A scanner that dies after writing a
    # partial report must not produce a passing report.
    failures = _module_survives_verdict_mutation(tmp_path, monkeypatch, "audit_rc != 0", "False")
    assert any("audit_rc != 0" in f for f in failures)


def test_source_contract_rejects_a_verdict_that_ignores_the_deny_exit_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The failure that was actually observed: cargo deny exited 1 with three
    # unmaintained advisories, and the old verdict was a stdout substring.
    failures = _module_survives_verdict_mutation(tmp_path, monkeypatch, "deny_rc != 0", "False")
    assert any("deny_rc != 0" in f for f in failures)


def test_source_contract_rejects_reading_the_boolean_found_as_a_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `vulnerabilities.found` is a BOOLEAN. A report that sets it false next to
    # a populated `list` passed the old parser; the count/list length is the
    # evidence and must stay the thing that is read.
    failures = _module_survives_verdict_mutation(
        tmp_path, monkeypatch, 'vulnerabilities.get("count")', 'vulnerabilities.get("found")'
    )
    assert any("vulnerabilities.get(\"count\")" in f for f in failures)


def test_source_contract_requires_the_committed_deny_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleting deny.toml must be caught: without it cargo deny's default
    config has an empty license allowlist and rejects all 147 crates."""
    fake = _synthetic_tree(tmp_path)
    (fake / "packages/bio-core/deny.toml").write_text("# empty\n", encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("deny.toml" in f for f in guard.source_failures())

    monkeypatch.setattr(guard, "ROOT", fake)
    (fake / "packages/bio-core/deny.toml").unlink()
    assert any("deny.toml is missing" in f for f in guard.source_failures())


def test_source_contract_rejects_an_over_floor_audit_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A floor-only guard accepts 0.22.99. The pin's stated purpose is that the
    # finding set cannot drift between two runs of one commit, so ANY version
    # other than the exact resolution must be red.
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    scanner.write_text(
        scanner.read_text(encoding="utf-8").replace(
            "SOYMUTDB_BIO_CORE_CARGO_AUDIT:-0.22.2",
            "SOYMUTDB_BIO_CORE_CARGO_AUDIT:-0.22.99",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("must not drift between runs" in f for f in guard.source_failures())


def test_source_contract_rejects_an_over_floor_deny_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Same ceiling for the second scanner: 0.18.99 is above the CVSS floor but
    # is a different advisory-database parser, so it can change the finding set.
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    scanner.write_text(
        scanner.read_text(encoding="utf-8").replace(
            "SOYMUTDB_BIO_CORE_CARGO_DENY:-0.18.9",
            "SOYMUTDB_BIO_CORE_CARGO_DENY:-0.18.99",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("must not drift between runs" in f for f in guard.source_failures())


def _deny_policy_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old: str, new: str
) -> list[str]:
    """Mutate deny.toml on a clean synthetic tree and return the guard verdict."""
    fake = _synthetic_tree(tmp_path)
    policy = fake / "packages/bio-core/deny.toml"
    original = policy.read_text(encoding="utf-8")
    assert old in original, f"deny.toml no longer contains {old!r}"
    policy.write_text(original.replace(old, new, 1), encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", fake)
    return guard.source_failures()


def test_contracts_layer_parses_deny_lint_levels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The unittest layer must parse deny.toml, not substring-match it. A byte
    # substring survives in a comment while the real key flips to a fail-open
    # lint level; measured on 11c3971d, all seven substring assertions passed
    # GREEN on that mutation while source_failures() caught it.
    import unittest

    from scripts import test_ci_job_contracts as contracts

    tree = _synthetic_tree(tmp_path)
    monkeypatch.setattr(contracts, "ROOT", tree)
    method = "test_bio_core_wheel_abi_ledger_is_enforced_by_the_contracts_layer"
    case = contracts.DeliveryArchitectureTests(method)

    mutations = (
        ('unmaintained = "all"', "unmaintained = \"workspace\""),
        ('unknown-registry = "deny"', "unknown-registry = \"warn\""),
        ('yanked = "deny"', "yanked = \"warn\""),
        ('multiple-versions = "deny"', "multiple-versions = \"allow\""),
        ('wildcards = "deny"', "wildcards = \"allow\""),
        ('unknown-git = "deny"', "unknown-git = \"allow\""),
        ('crate = "ryu@1.0.23"', "crate = \"ryu@9.9.9\""),
    )
    deny = tree / "packages" / "bio-core" / "deny.toml"
    original = deny.read_text(encoding="utf-8")
    assert not guard.source_failures(), "synthetic-tree baseline must be green"
    for good, bad in mutations:
        assert good in original, good
        deny.write_text(
            original.replace(good, f"# reviewed: {good}\n{bad}", 1), encoding="utf-8"
        )
        result = unittest.TestResult()
        case.run(result)
        assert result.failures or result.errors, (
            f"contracts layer stayed green on a fail-open {good!r} flip"
        )
        deny.write_text(original, encoding="utf-8")
    result = unittest.TestResult()
    case.run(result)
    assert not (result.failures or result.errors), "restored policy must be green"


def test_source_contract_accepts_the_committed_deny_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The four negatives below are only meaningful if this exact tree is green.
    monkeypatch.setattr(guard, "ROOT", _synthetic_tree(tmp_path))
    assert guard.source_failures() == []


def test_source_contract_rejects_wildcard_version_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `wildcards = "allow"` lets a dependency pin `*` and still ship. The old
    # substring guard never read this lint level at all.
    failures = _deny_policy_mutation(
        tmp_path, monkeypatch, 'wildcards = "deny"', 'wildcards = "allow"'
    )
    assert any("wildcard version" in f for f in failures)


def test_source_contract_rejects_unknown_git_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A git source is a second, unreviewed provenance path. Flipping the lint
    # level to "allow" used to pass the byte-string guard.
    failures = _deny_policy_mutation(
        tmp_path, monkeypatch, 'unknown-git = "deny"', 'unknown-git = "allow"'
    )
    assert any("unknown git sources" in f for f in failures)


def test_source_contract_rejects_an_unversioned_license_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `ryu@1.0.23` declares "Apache-2.0 OR BSL-1.0". Dropping the version
    # makes the BSL-1.0 decision cover every future ryu release.
    failures = _deny_policy_mutation(
        tmp_path, monkeypatch, 'crate = "ryu@1.0.23"', 'crate = "ryu"'
    )
    assert any("version-pinned" in f for f in failures)


def test_source_contract_rejects_a_dropped_duplicate_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The `skip` list must name exactly the duplicate versions in Cargo.lock.
    # Deleting one entry used to leave the "skip = [" substring intact.
    failures = _deny_policy_mutation(
        tmp_path, monkeypatch, '    { crate = "syn@3.0.9" },\n', ''
    )
    assert any("skip list must name exactly" in f for f in failures)


def test_source_contract_rejects_a_missing_lockfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without Cargo.lock the skip list has no ground truth. The guard must say
    # so, not silently turn the comparison into a no-op.
    fake = _synthetic_tree(tmp_path)
    (fake / "packages/bio-core/Cargo.lock").unlink()
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("Cargo.lock is missing" in f for f in guard.source_failures())


def test_source_contract_rejects_a_caret_audit_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Dropping the "=" turns the exact requirement back into ^0.22.2. The
    # declaration pin stays 0.22.2 and every existing assertion still passes,
    # so only this new guard can see the install contract being widened.
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    scanner.write_text(
        scanner.read_text(encoding="utf-8").replace(
            '--version "=${AUDIT_VERSION}"', '--version "${AUDIT_VERSION}"', 1
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("caret requirement" in f for f in guard.source_failures())


def test_source_contract_rejects_a_caret_deny_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    scanner.write_text(
        scanner.read_text(encoding="utf-8").replace(
            '--version "=${DENY_VERSION}"', '--version "${DENY_VERSION}"', 1
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("caret requirement" in f for f in guard.source_failures())


def test_contracts_layer_parses_the_four_remaining_deny_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The seven levels the sibling regression covers were not the whole class.
    # Four more keys in deny.toml were still read as byte substrings, and each
    # one flips the policy toward fail-open: an unused allow-list entry stops
    # being reported, a private workspace crate starts being skipped from the
    # license check, and a 0.0 confidence threshold accepts any match evidence.
    # Measured on the branch before this test: all four stayed GREEN.
    import unittest

    from scripts import test_ci_job_contracts as contracts

    tree = _synthetic_tree(tmp_path)
    monkeypatch.setattr(contracts, "ROOT", tree)
    method = "test_bio_core_wheel_abi_ledger_is_enforced_by_the_contracts_layer"
    case = contracts.DeliveryArchitectureTests(method)

    mutations = (
        ('unused-allowed-license = "warn"', 'unused-allowed-license = "allow"'),
        ("ignore = false", "ignore = true"),
        ("confidence-threshold = 0.8", "confidence-threshold = 0.0"),
        ('allow = ["Unicode-3.0"]', 'allow = ["MIT"]'),
    )
    deny = tree / "packages" / "bio-core" / "deny.toml"
    original = deny.read_text(encoding="utf-8")
    for good, bad in mutations:
        assert good in original, good
        deny.write_text(
            original.replace(good, f"# reviewed: {good}\n{bad}", 1), encoding="utf-8"
        )
        result = unittest.TestResult()
        case.run(result)
        assert result.failures or result.errors, (
            f"contracts layer stayed green on a fail-open {good!r} flip"
        )
        deny.write_text(original, encoding="utf-8")
    result = unittest.TestResult()
    case.run(result)
    assert not (result.failures or result.errors), "restored policy must be green"


def test_static_gate_parses_the_toolchain_channel(tmp_path: Path) -> None:
    # `if "channel" not in text` accepts a channel that only survives in a
    # comment, an empty string, and a bare TOML number. All four shapes leave
    # the pin wrecked while --static reports OK, and the failure then surfaces
    # as rustup refusing to resolve a channel mid-build.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "bio_core_wheel_checker_channel",
        Path(guard.__file__).resolve().parent / "check_bio_core_wheel.py",
    )
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)

    fake = _synthetic_tree(tmp_path)
    crate = fake / "packages/bio-core"
    # A manifest that already satisfies the dependency pins, so the only thing
    # each iteration varies is the toolchain file under test.
    (crate / "Cargo.toml").write_text(
        "[dependencies]\n"
        'bio = "4"\nnoodles = "0"\nrust-lapper = "1"\n'
        'bio-seq = "0"\npyo3 = "0"\n',
        encoding="utf-8",
    )
    (crate / "pyproject.toml").write_text("", encoding="utf-8")
    (crate / "src").mkdir()
    (crate / "src" / "lib.rs").write_text("", encoding="utf-8")
    checker.ROOT = fake
    checker.CRATE = crate

    toolchain = crate / "rust-toolchain.toml"
    broken = (
        '[toolchain]\n# channel = "1.99.1"\ncomponents = ["rustfmt"]\n',
        '[toolchain]\nchannel = ""\n',
        "[toolchain]\nchannel = 1.99\n",
        '[toolchain]\nchannel = "stable"\n',
        '[toolchain]\ncomponents = ["rustfmt"]\n',
    )
    for body in broken:
        toolchain.write_text(body, encoding="utf-8")
        assert checker.check_static(), f"--static must reject {body!r}"
    toolchain.write_text('[toolchain]\nchannel = "1.99.1"\n', encoding="utf-8")
    assert not checker.check_static(), "--static must accept an exact release pin"


def test_source_contract_rejects_a_verdict_that_drops_the_observation_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `=` pins the INSTALL requirement; a report that hardcodes "pinned" cannot
    # prove which binary produced the clean verdict. Removing the binding must
    # be caught by the source guard, not only by the behavioural suite.
    failures = _module_survives_verdict_mutation(
        tmp_path, monkeypatch, "def read_observations(", "def _unused_observations("
    )
    assert any("read_observations" in f for f in failures)


def test_source_contract_rejects_a_re_hardcoded_placeholder_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The literal "pinned" as a string CONSTANT (not prose) means the signed
    # report went back to a declaration instead of an observation.
    failures = _module_survives_verdict_mutation(
        tmp_path, monkeypatch,
        '"version": audit_version,', '"version": "pinned",',
    )
    assert any("placeholder version" in f for f in failures)


def test_source_contract_rejects_a_missing_version_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    original = scanner.read_text(encoding="utf-8")
    assert "cargo audit --version" in original
    scanner.write_text(
        original.replace('(cd "${CRATE_DIR}" && cargo audit --version) > "${AUDIT_VERSION_FILE}" 2>/dev/null || \\\n  fail "cannot read the installed cargo-audit version"\n', "", 1),
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("cargo audit --version" in f for f in guard.source_failures())


def test_source_contract_rejects_a_dropped_version_argument(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _synthetic_tree(tmp_path)
    scanner = fake / "scripts/verify-bio-core-supply-chain.sh"
    original = scanner.read_text(encoding="utf-8")
    assert "--expect-audit" in original
    scanner.write_text(original.replace(" --expect-audit", "", 1), encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", fake)
    assert any("--expect-audit" in f for f in guard.source_failures())
