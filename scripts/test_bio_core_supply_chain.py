"""Regression proofs for the Rust bio-core supply-chain verdict.

The scanner's heredoc parser used to pass all of these shapes while reporting
green. Every case here is a shape the shipped parser accepted or mishandled;
the fix must reject it. No Rust, cargo, wheel or network is needed.

The report is signed into the release SBOM, so it also has to name the scanner
binaries that actually ran. A report that hardcodes ``"version": "pinned"``
cannot distinguish a shadowed binary from the exact pin; those shapes are
covered here too.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_bio_core_supply_chain as verdict  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "verify-bio-core-supply-chain.sh"
CHECKER = Path(__file__).resolve().parent / "check_bio_core_supply_chain.py"

CLEAN = {"vulnerabilities": {"found": False, "count": 0, "list": []}}
# A valid pair of observed versions, matching the committed install pins.
OBS = {verdict.AUDIT_TOOL: "0.22.2", verdict.DENY_TOOL: "0.18.9"}


# --- cargo audit: `found` is a boolean, not a count -----------------------

def test_clean_audit_passes() -> None:
    report = verdict.build_report(CLEAN, 0, 0, OBS)
    assert report["cargo_audit"]["findings"] == 0
    assert report["cargo_audit"]["version"] == "0.22.2"
    assert report["cargo_deny"]["version"] == "0.18.9"


def test_two_advisories_fail_with_the_real_count() -> None:
    with pytest.raises(verdict.VerdictError, match="2 vulnerability"):
        verdict.build_report({"vulnerabilities": {"found": True, "count": 2, "list": [{}, {}]}}, 0, 0, OBS)


def test_found_false_with_a_populated_list_fails_closed() -> None:
    # The old parser read `found` (False) and passed. The list is the evidence.
    with pytest.raises(verdict.VerdictError, match="2 vulnerability"):
        verdict.build_report({"vulnerabilities": {"found": False, "count": 0, "list": [{}, {}]}}, 0, 0, OBS)


def test_count_lower_than_list_length_fails_closed() -> None:
    with pytest.raises(verdict.VerdictError, match="2 vulnerability"):
        verdict.build_report({"vulnerabilities": {"found": False, "count": 1, "list": [{}, {}]}}, 0, 0, OBS)


def test_bool_count_is_rejected_not_coerced() -> None:
    # bool is a subclass of int in Python; accepting it reintroduces the bug.
    with pytest.raises(verdict.VerdictError, match="not a non-negative integer"):
        verdict.audit_findings({"vulnerabilities": {"count": True, "list": []}})


def test_missing_vulnerabilities_object_fails_closed() -> None:
    with pytest.raises(verdict.VerdictError, match="no 'vulnerabilities'"):
        verdict.build_report({}, 0, 0, OBS)


def test_audit_nonzero_exit_is_not_a_pass_even_with_clean_json() -> None:
    # A scanner that died after writing a partial report still exited non-zero.
    with pytest.raises(verdict.VerdictError, match="exited 1"):
        verdict.build_report(CLEAN, 1, 0, OBS)


# --- cargo deny: verdict is exit status, not stdout substrings ------------

def test_deny_nonzero_exit_fails_even_with_clean_text() -> None:
    # "advisories ok, bans ok" was the old parser's idea of a pass.
    with pytest.raises(verdict.VerdictError, match="exited 1"):
        verdict.build_report(CLEAN, 0, 1, OBS)


def test_deny_error_plus_warning_text_does_not_override_exit_status() -> None:
    # `error + warning` used to be swallowed by `"warning" not in text`.
    # Exit status 1 is authoritative; exit 0 with warnings is a documented pass.
    with pytest.raises(verdict.VerdictError, match="exited 1"):
        verdict.build_report(CLEAN, 0, 1, OBS)
    clean = verdict.build_report(CLEAN, 0, 0, OBS)
    assert clean["cargo_deny"]["status"] == "passed"


# --- the signed report must name the binaries that actually ran ------------

def test_report_rejects_a_placeholder_version() -> None:
    # The old report hard-coded "version": "pinned": a declaration, not an
    # observation. A missing observation is now a hard failure.
    with pytest.raises(verdict.VerdictError, match="observations are missing"):
        verdict.build_report(CLEAN, 0, 0, None)


@pytest.mark.parametrize("broken", [
    {},
    {verdict.AUDIT_TOOL: "0.22.2"},
    {verdict.DENY_TOOL: "0.18.9"},
    {verdict.AUDIT_TOOL: "pinned", verdict.DENY_TOOL: "0.18.9"},
    {verdict.AUDIT_TOOL: "0.22.2", verdict.DENY_TOOL: "^0.18.9"},
    {verdict.AUDIT_TOOL: "0.22.2", verdict.DENY_TOOL: 1},
])
def test_report_rejects_incomplete_or_non_exact_observations(broken: object) -> None:
    with pytest.raises(verdict.VerdictError):
        verdict.build_report(CLEAN, 0, 0, broken)


def test_parse_scanner_version_uses_the_last_semver_token() -> None:
    assert verdict.parse_scanner_version("cargo-audit 0.22.2\n", "cargo-audit") == "0.22.2"
    assert verdict.parse_scanner_version("cargo-audit-audit 0.22.2 (abc)\n", "cargo-audit") == "0.22.2"


def test_parse_scanner_version_fails_closed_without_a_version() -> None:
    with pytest.raises(verdict.VerdictError, match="no parseable version"):
        verdict.parse_scanner_version("cargo-audit (no version here)\n", "cargo-audit")


def _write_versions(tmp_path: Path, audit: str = "cargo-audit 0.22.2\n",
                    deny: str = "cargo-deny 0.18.9\n") -> tuple[Path, Path]:
    a = tmp_path / "audit.version"
    d = tmp_path / "deny.version"
    a.write_text(audit, encoding="utf-8")
    d.write_text(deny, encoding="utf-8")
    return a, d


def test_read_observations_accepts_matching_pins(tmp_path: Path) -> None:
    a, d = _write_versions(tmp_path)
    assert verdict.read_observations(a, d, "0.22.2", "0.18.9") == OBS


def test_read_observations_rejects_a_drifted_binary(tmp_path: Path) -> None:
    # `=` pins the INSTALL requirement; only the binary's own --version can
    # reveal that a different release produced the clean verdict.
    a, d = _write_versions(tmp_path, audit="cargo-audit 0.22.99\n")
    with pytest.raises(verdict.VerdictError, match="executed as 0.22.99"):
        verdict.read_observations(a, d, "0.22.2", "0.18.9")


def test_read_observations_rejects_a_drifted_deny_binary(tmp_path: Path) -> None:
    a, d = _write_versions(tmp_path, deny="cargo-deny 0.18.4\n")
    with pytest.raises(verdict.VerdictError, match="executed as 0.18.4"):
        verdict.read_observations(a, d, "0.22.2", "0.18.9")


def test_read_observations_fails_closed_on_empty_probe(tmp_path: Path) -> None:
    a, d = _write_versions(tmp_path, audit="")
    with pytest.raises(verdict.VerdictError, match="version evidence is empty"):
        verdict.read_observations(a, d, "0.22.2", "0.18.9")


def test_read_observations_fails_closed_on_missing_file(tmp_path: Path) -> None:
    a, d = _write_versions(tmp_path)
    a.unlink()
    with pytest.raises(verdict.VerdictError, match="version evidence is missing"):
        verdict.read_observations(a, d, "0.22.2", "0.18.9")


# --- CLI behaviour of the real module --------------------------------------

def _run_cli(tmp_path: Path, audit_text: str, audit_rc: int, deny_rc: int,
             *, audit_ver: str = "cargo-audit 0.22.2\n",
             deny_ver: str = "cargo-deny 0.18.9\n",
             expect_audit: str = "0.22.2", expect_deny: str = "0.18.9",
             write_versions: bool = True) -> tuple[int, str, dict | None]:
    audit = tmp_path / "cargo-audit.json"
    audit.write_text(audit_text, encoding="utf-8")
    report = tmp_path / "report.json"
    cmd = [sys.executable, str(CHECKER), str(audit), str(audit_rc), str(deny_rc), str(report)]
    if write_versions:
        a, d = _write_versions(tmp_path, audit=audit_ver, deny=deny_ver)
        cmd += ["--audit-version-file", str(a), "--deny-version-file", str(d),
                "--expect-audit", expect_audit, "--expect-deny", expect_deny]
    else:
        cmd += ["--audit-version-file", str(tmp_path / "absent-a"),
                "--deny-version-file", str(tmp_path / "absent-d"),
                "--expect-audit", expect_audit, "--expect-deny", expect_deny]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    parsed = json.loads(report.read_text()) if report.exists() else None
    return proc.returncode, proc.stdout + proc.stderr, parsed


def test_cli_clean_writes_one_report(tmp_path: Path) -> None:
    rc, out, report = _run_cli(tmp_path, json.dumps(CLEAN), 0, 0)
    assert rc == 0, out
    assert report["cargo_audit"]["findings"] == 0
    assert report["cargo_audit"]["version"] == "0.22.2"
    assert report["cargo_deny"]["version"] == "0.18.9"


def test_cli_fail_open_shapes_are_rejected(tmp_path: Path) -> None:
    clean = json.dumps(CLEAN)
    cases = [
        (json.dumps({"vulnerabilities": {"found": False, "count": 0, "list": [{}, {}]}}), 0, 0),
        (clean, 0, 1),
        (clean, 1, 0),
    ]
    for audit_text, audit_rc, deny_rc in cases:
        rc, out, _ = _run_cli(tmp_path, audit_text, audit_rc, deny_rc)
        assert rc == 1, (audit_text, audit_rc, deny_rc, out)
        assert "FAIL" in out


def test_cli_empty_audit_output_fails_closed(tmp_path: Path) -> None:
    rc, out, _ = _run_cli(tmp_path, "", 0, 0)
    assert rc == 1 and "no output" in out


def test_cli_malformed_json_fails_closed(tmp_path: Path) -> None:
    rc, out, _ = _run_cli(tmp_path, "{not json", 0, 0)
    assert rc == 1


def test_cli_drifted_version_fails_closed(tmp_path: Path) -> None:
    rc, out, report = _run_cli(tmp_path, json.dumps(CLEAN), 0, 0, audit_ver="cargo-audit 0.22.99\n")
    assert rc == 1 and "executed as 0.22.99" in out, out
    assert report is None, "a drifted scanner must not produce a signed report"


def test_cli_missing_version_evidence_fails_closed(tmp_path: Path) -> None:
    rc, out, report = _run_cli(tmp_path, json.dumps(CLEAN), 0, 0, write_versions=False)
    assert rc == 1 and "version evidence is missing" in out, out
    assert report is None


# --- the shipped script calls the checkable verdict ------------------------

def test_scanner_delegates_the_verdict_to_the_checkable_module() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "check_bio_core_supply_chain.py" in text
    assert 'vulnerabilities.get("found"' not in text
    assert '"error" in deny_text' not in text
    assert "cargo deny check) >" in text and "DENY_RC=$?" in text
    assert "cargo audit --json)" in text and "AUDIT_RC=$?" in text
    # The committed policy defines lint levels; --deny warnings overrides them.
    # Look at executable lines only, not the comment that explains why.
    commands = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert not any("--deny warnings" in ln for ln in commands)


def test_scanner_observes_both_executed_versions() -> None:
    """The `=` install pin is proven by the binaries' own --version output."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "cargo audit --version" in text
    assert "cargo deny --version" in text
    for flag in ("--audit-version-file", "--deny-version-file",
                 "--expect-audit", "--expect-deny"):
        assert flag in text, f"scanner stopped passing {flag} to the verdict"
    # The module may *quote* the old placeholder in prose; it must not emit it
    # as a report value. Check the literal constants the verdict can return.
    import ast
    tree = ast.parse(CHECKER.read_text(encoding="utf-8"))
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "pinned" not in literals, "the verdict still hardcodes a placeholder version"


def _stub_scanner(tmp_path: Path, *, audit_version: str = "cargo-audit 0.22.2",
                  deny_version: str = "cargo-deny 0.18.9",
                  deny_rc: int = 1) -> tuple[Path, Path]:
    """Build a fake repo + cargo stub; no Rust toolchain needed."""
    script_src = SCRIPT.read_text(encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "packages" / "bio-core").mkdir(parents=True)
    (repo / "packages" / "bio-core" / "Cargo.lock").write_text("", encoding="utf-8")
    (repo / "packages" / "bio-core" / "Cargo.toml").write_text("", encoding="utf-8")
    (repo / "scripts" / "verify-bio-core-supply-chain.sh").write_text(script_src, encoding="utf-8")
    for name in ("check_bio_core_supply_chain.py",):
        (repo / "scripts" / name).write_text(CHECKER.read_text(encoding="utf-8"), encoding="utf-8")

    cargo_home = tmp_path / "cargo" / "bin"
    cargo_home.mkdir(parents=True)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    stub = cargo_home / "cargo"
    stub.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *install*) exit 0 ;;\n"
        f"  *audit*--version*) echo '{audit_version}'; exit 0 ;;\n"
        f"  *deny*--version*) echo '{deny_version}'; exit 0 ;;\n"
        "  *audit*) printf '%s' '{\"vulnerabilities\":{\"found\":false,\"count\":0,\"list\":[]}}' ; exit 0 ;;\n"
        f"  *deny*) echo 'warning: maintenance note'; exit {deny_rc} ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    env = {
        "PATH": f"{cargo_home}{os.pathsep}{os.environ.get('PATH', '')}",
        "CARGO_HOME": str(cargo_home.parent),
        "RUSTUP_HOME": str(tmp_path / "rustup"),
        "SOYMUTDB_BIO_CORE_EVIDENCE_DIR": str(evidence),
    }
    return repo, env, evidence


def _run_stub(repo: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(repo / "scripts" / "verify-bio-core-supply-chain.sh")],
        cwd=repo, env=env, capture_output=True, text=True, timeout=60, check=False,
    )


def test_scanner_runs_the_verdict_end_to_end(tmp_path: Path) -> None:
    """Execute the real script with stub cargo tools; no Rust toolchain needed.

    Stub `cargo install` succeeds, `cargo audit` emits a clean-but-boolean
    report, `cargo deny` exits 1 while printing only harmless words. The old
    parser passed this; the fixed verdict must fail and print the reason.
    """
    repo, env, evidence = _stub_scanner(tmp_path)
    proc = _run_stub(repo, env)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, combined
    assert "deny exited 1" in combined, combined
    report = evidence / "cargo-supply-chain.json"
    assert not report.exists(), "a failed deny check must not write a passing report"


def test_scanner_signs_the_observed_versions_end_to_end(tmp_path: Path) -> None:
    """A clean run writes a report that names the executed binaries."""
    repo, env, evidence = _stub_scanner(tmp_path, deny_rc=0)
    proc = _run_stub(repo, env)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    report = json.loads((evidence / "cargo-supply-chain.json").read_text(encoding="utf-8"))
    assert report["cargo_audit"]["version"] == "0.22.2"
    assert report["cargo_deny"]["version"] == "0.18.9"


def test_scanner_rejects_a_drifted_binary_end_to_end(tmp_path: Path) -> None:
    """A shadowed 0.22.99 binary must not sign a report for a 0.22.2 pin.

    This is the flanking shape the `=` install pin cannot see: the declaration
    and the install contract are both correct, but the executed binary differs.
    """
    repo, env, evidence = _stub_scanner(tmp_path, audit_version="cargo-audit 0.22.99", deny_rc=0)
    proc = _run_stub(repo, env)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, combined
    assert "executed as 0.22.99" in combined, combined
    assert not (evidence / "cargo-supply-chain.json").exists()
