#!/usr/bin/env python3
"""Fail-closed verdict for the Rust bio-core supply-chain evidence.

The scanner captures ``cargo audit --json``, the ``cargo deny`` stdout/stderr
and both exit statuses; this module turns those four facts into one verdict.
It is deliberately a real module: a heredoc buried in a shell script cannot
be imported, so its three fail-open paths can only be checked by reading them.
That is exactly how they survived a review and a green contract suite.

cargo audit --json reports ``vulnerabilities.found`` as a BOOLEAN and
``vulnerabilities.count`` as the number. Treating ``found`` as a count prints
"True vulnerability/ies" for real findings and, worse, a report that sets
``found: false`` alongside a populated ``list`` passes. The verdict therefore
uses the count/list length and never the boolean.

cargo deny's verdict is its EXIT STATUS, not a substring of its output:
"error" and "warning" routinely appear together, and an empty output (tool
died, config failed to load, wrote nothing) is not a pass.

The report is folded into the release SBOM / SHA256SUMS, so it names the
scanner binaries that ran. ``--version "=0.22.2"`` is an install contract;
it does not prove that the binary on PATH is the one that produced the clean
verdict. Each tool's own ``--version`` is captured at scan time, compared to
the pin that was installed, and the observed value is written into the signed
report. A missing, empty, or drifting observation is a hard failure.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


class VerdictError(Exception):
    """A scanner input that is missing, malformed, or reports a finding."""


VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.]+)?)\b")
AUDIT_TOOL = "cargo-audit"
DENY_TOOL = "cargo-deny"


def audit_findings(audit: object) -> int:
    """Number of cargo-audit findings; fail closed on an unknown shape."""
    if not isinstance(audit, dict):
        raise VerdictError("cargo audit evidence is not a JSON object")
    vulnerabilities = audit.get("vulnerabilities")
    if vulnerabilities is None:
        raise VerdictError("cargo audit evidence has no 'vulnerabilities' object")
    if isinstance(vulnerabilities, dict):
        count = vulnerabilities.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise VerdictError("cargo audit 'vulnerabilities.count' is not a non-negative integer")
        entries = vulnerabilities.get("list")
        if entries is None:
            entries = []
        if not isinstance(entries, list):
            raise VerdictError("cargo audit 'vulnerabilities.list' is not an array")
        # A stale/malformed report that claims zero while listing findings is
        # not a clean scan: take the larger of the two, never the smaller.
        return max(count, len(entries))
    if isinstance(vulnerabilities, list):
        return len(vulnerabilities)
    raise VerdictError("cargo audit 'vulnerabilities' is neither an object nor an array")


def parse_scanner_version(text: str, tool: str) -> str:
    """Last semver-looking token in ``tool --version``; fail closed if absent."""
    matches = VERSION_RE.findall(text)
    if not matches:
        raise VerdictError(f"{tool} --version produced no parseable version: {text!r}")
    return matches[-1]


def read_observations(
    audit_version_file: Path,
    deny_version_file: Path,
    expected_audit: str,
    expected_deny: str,
) -> dict[str, str]:
    """Bind the executed scanners to the exact pins the install step used.

    ``=`` pins the install requirement, but a report that hardcodes
    ``"version": "pinned"`` is a declaration, not an observation: a shadowed
    binary, an env override, or a dropped ``=`` all yield the same green
    report. Read each binary's own ``--version`` and fail closed on drift.
    """
    observations: dict[str, str] = {}
    for tool, path, expected in (
        (AUDIT_TOOL, audit_version_file, expected_audit),
        (DENY_TOOL, deny_version_file, expected_deny),
    ):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise VerdictError(f"{tool} version evidence is missing: {exc}") from exc
        if not raw.strip():
            raise VerdictError(f"{tool} version evidence is empty: the probe did not run")
        observed = parse_scanner_version(raw, tool)
        if observed != expected:
            raise VerdictError(
                f"{tool} executed as {observed}, but the install pin is {expected}: "
                "the resolved binary is not the one that was installed"
            )
        observations[tool] = observed
    return observations


def validate_observations(observations: object) -> tuple[str, str]:
    """A report may not be signed without both observed versions."""
    if not isinstance(observations, dict):
        raise VerdictError("scanner version observations are missing")
    try:
        audit_version, deny_version = observations[AUDIT_TOOL], observations[DENY_TOOL]
    except KeyError as exc:
        raise VerdictError(f"scanner version observations are incomplete: {exc}") from exc
    for tool, version in ((AUDIT_TOOL, audit_version), (DENY_TOOL, deny_version)):
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            raise VerdictError(f"{tool} observation is not an exact version: {version!r}")
    return audit_version, deny_version


def build_report(
    audit: object, audit_rc: int, deny_rc: int, observations: object
) -> dict:
    """Return the consolidated report or raise VerdictError. Fail closed."""
    if audit_rc != 0:
        raise VerdictError(f"cargo audit exited {audit_rc}; the scan did not complete")
    findings = audit_findings(audit)
    if findings:
        raise VerdictError(f"cargo audit reported {findings} vulnerability/ies")
    if deny_rc != 0:
        raise VerdictError(f"cargo deny exited {deny_rc}; the policy check did not pass")
    audit_version, deny_version = validate_observations(observations)
    return {
        "schema_version": 1,
        "source": "bio-core job (single Rust toolchain)",
        "lockfile": "packages/bio-core/Cargo.lock",
        "cargo_audit": {"version": audit_version, "findings": findings, "exit_code": audit_rc},
        "cargo_deny": {"version": deny_version, "status": "passed", "exit_code": deny_rc},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit_json", type=Path, help="cargo audit --json evidence")
    parser.add_argument("audit_rc", type=int, help="cargo audit exit status")
    parser.add_argument("deny_rc", type=int, help="cargo deny exit status")
    parser.add_argument("report", type=Path, help="consolidated report to write")
    parser.add_argument("--audit-version-file", type=Path, required=True,
                        help="captured `cargo audit --version` output")
    parser.add_argument("--deny-version-file", type=Path, required=True,
                        help="captured `cargo deny --version` output")
    parser.add_argument("--expect-audit", required=True, help="exact cargo-audit pin that was installed")
    parser.add_argument("--expect-deny", required=True, help="exact cargo-deny pin that was installed")
    args = parser.parse_args(argv)
    try:
        raw = args.audit_json.read_text(encoding="utf-8")
        if not raw.strip():
            raise VerdictError("cargo audit produced no output")
        audit = json.loads(raw)
        observations = read_observations(
            args.audit_version_file, args.deny_version_file,
            args.expect_audit, args.expect_deny,
        )
        report = build_report(audit, args.audit_rc, args.deny_rc, observations)
    except (OSError, json.JSONDecodeError, VerdictError) as exc:
        print(f"bio-core supply chain: FAIL: {exc}", file=sys.stderr)
        return 1
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
