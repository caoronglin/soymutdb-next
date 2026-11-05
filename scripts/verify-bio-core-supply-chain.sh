#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — Rust bio-core supply-chain evidence (cargo audit + cargo deny)
# =============================================================================
# The bio-core job is the ONLY stage with a Rust toolchain, so the two Rust
# dependency scanners run here and nowhere else. They produce ONE consolidated
# report in artifacts/ so the release lane can fold its digest into the same
# SHA256SUMS / SBOM evidence bundle as the images (docs/ops/bio-core-wheel.md).
# Registering a second `cargo-*` analyzer in dependency-governance.json would
# create a parallel, contradictory report; that is explicitly forbidden by a
# source contract in scripts/check_bio_core_wheel_abi.py.
#
# Fail-closed: a missing tool, an advisory, a denied license, or a stale lock
# all exit 1. Nothing here reports SKIPPED-as-PASS.
#
# Usage: bash scripts/verify-bio-core-supply-chain.sh
# Env:   SOYMUTDB_BIO_CORE_CARGO_AUDIT   plain x.y.z cargo-audit version (default 0.22.2)
#        SOYMUTDB_BIO_CORE_CARGO_DENY    plain x.y.z cargo-deny version  (default 0.18.9)
#        (the script adds the exact-requirement "=" operator; overrides must NOT
#         include it, or the requirement becomes invalid)
#        SOYMUTDB_BIO_CORE_EVIDENCE_DIR  report dir (default artifacts/bio-core)
# =============================================================================
set -euo pipefail

SHARED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SHARED_DIR}/.." && pwd)"
CRATE_DIR="${REPO_ROOT}/packages/bio-core"
EVIDENCE_DIR="${SOYMUTDB_BIO_CORE_EVIDENCE_DIR:-${REPO_ROOT}/artifacts/bio-core}"
# 0.21.2 cannot parse the RustSec advisory database any more: it rejects CVSS
# 4.0 vectors, and the first advisory carrying one (RUSTSEC-2026-0066) makes
# every run die with "unsupported CVSS version: 4.0" before a single crate is
# scanned (cnb-elt-1k6kb3soh). That run (cnb-k4a-1k6kbhl3c) installed 0.21.2,
# not 0.22.1 -- runner L3266/L3862/L4405. 0.22.1 also died
# (cnb-7qb-1k6kbvp1e, exit 1), but that run redirected scan stdout into a
# file, so its failure reason is NOT in the stage log; its own install chain
# resolved cvss 2.2.0 / rustsec 0.32.0 (L3441/L3541), i.e. it already had the
# 4.0 parser. The cvss 2.1.0 / rustsec 0.30.4 in that log (L4000/L4076)
# belongs to the separate cargo-deny 0.18.4 install. 0.22.2 is the first
# version whose runner log shows the audit scan completing with no CVSS
# error (cnb-qf2-1k6kc4hoo). The pin keeps the finding set from drifting
# between two runs of a commit; it is not a licence to freeze a scanner
# that can no longer read its own input.
AUDIT_VERSION="${SOYMUTDB_BIO_CORE_CARGO_AUDIT:-0.22.2}"
# cargo-deny reads the advisory database through rustsec, so it hits the same
# CVSS wall: 0.18.4 links rustsec 0.30.x -> cvss 2.1.0 and dies on the first
# 4.0 vector (cnb-qf2-1k6kc4hoo). 0.18.9 is the first 0.18 release that
# resolves rustsec 0.31.0 -> `cvss ^2.2` -> 2.2.0, i.e. the same parser that
# cargo-audit already needs, and it is verified against the crate's published
# Cargo.lock -- not inferred from a caret range alone.
DENY_VERSION="${SOYMUTDB_BIO_CORE_CARGO_DENY:-0.18.9}"

# This script is a separate `bash` process from verify-bio-core.sh, so none of
# that script's `export` lines survive into this one. Resolve the SAME rustup
# storage here: the bio-core job bootstraps cargo into $CARGO_HOME/bin once, and
# both scripts must find that exact toolchain (the crate pins its own channel).
# Keep the default expressions byte-identical to verify-bio-core.sh; the
# contracts layer asserts they cannot drift apart.
export CARGO_HOME="${CARGO_HOME:-${TMPDIR:-/tmp}/soymutdb-cargo}"
export RUSTUP_HOME="${RUSTUP_HOME:-${TMPDIR:-/tmp}/soymutdb-rustup}"
export PATH="${CARGO_HOME}/bin:${PATH}"

step() { printf '\n==> %s\n' "$*"; }

fail() { printf 'bio-core supply chain: FAIL: %s\n' "$*" >&2; exit 1; }

[[ -f "${CRATE_DIR}/Cargo.lock" ]] || fail "Cargo.lock is missing (--locked cannot hold)"
[[ -f "${CRATE_DIR}/Cargo.toml" ]] || fail "Cargo.toml is missing"

command -v cargo >/dev/null 2>&1 || fail "cargo unavailable; a Rust supply-chain scan cannot be skipped"

mkdir -p "${EVIDENCE_DIR}"
REPORT="${EVIDENCE_DIR}/cargo-supply-chain.json"

# Both tools are installed at exact versions so the finding set cannot drift
# between two runs of the same commit.
# verify-bio-core.sh bootstraps rustup with `--default-toolchain none`, so
# there is NO default channel: cargo only resolves when run from CRATE_DIR,
# where rust-toolchain.toml pins 1.99.1. Keep every cargo command there (the
# repo root has no toolchain file and would fail with "no default is
# configured"). The crate's pin stays the single source of the version.
step "install pinned cargo audit / cargo deny"
# A bare --version "0.22.2" is a CARET requirement (^0.22.2): the runner may
# install 0.22.99 while the committed declaration still reads 0.22.2. The
# "=" operator makes it an exact requirement; the source guard keeps that "=".
# It cannot verify the resolved version offline -- the runner log owns that.
(cd "${CRATE_DIR}" && cargo install --locked --version "=${AUDIT_VERSION}" cargo-audit) >/dev/null
(cd "${CRATE_DIR}" && cargo install --locked --version "=${DENY_VERSION}" cargo-deny) >/dev/null

# `=` is an exact INSTALL requirement; it cannot prove which binary produced
# the clean verdict (a shadowed binary, an env override, or a dropped `=` all
# yield the same green report). Observe each executed tool's own --version and
# let the verdict fail closed on drift. The probes run in CRATE_DIR too, so
# rustup uses the same pinned channel as the scans.
AUDIT_VERSION_FILE="${EVIDENCE_DIR}/cargo-audit.version"
DENY_VERSION_FILE="${EVIDENCE_DIR}/cargo-deny.version"
(cd "${CRATE_DIR}" && cargo audit --version) > "${AUDIT_VERSION_FILE}" 2>/dev/null || \
  fail "cannot read the installed cargo-audit version"
(cd "${CRATE_DIR}" && cargo deny --version) > "${DENY_VERSION_FILE}" 2>/dev/null || \
  fail "cannot read the installed cargo-deny version"

# Both verdicts come from EXIT STATUS plus the evidence files. A heredoc
# parser that guessed from stdout substrings is not checkable by any gate and
# went green on three fail-open shapes: `found` is a boolean, not a count;
# "error" and "warning" appear together; and empty deny output means the tool
# never ran. scripts/check_bio_core_supply_chain.py owns the verdict and is
# covered by scripts/test_bio_core_supply_chain.py.
step "cargo audit (RustSec advisory DB, Cargo.lock)"
AUDIT_RC=0
(cd "${CRATE_DIR}" && cargo audit --json) > "${EVIDENCE_DIR}/cargo-audit.json" || AUDIT_RC=$?
if (( AUDIT_RC != 0 )); then
  echo "bio-core supply chain: audit exited ${AUDIT_RC}; output follows" >&2
  sed -e 's/^/  /' "${EVIDENCE_DIR}/cargo-audit.json" >&2 || true
fi

step "cargo deny check (licenses / bans / sources / advisories)"
# Fail closed, and keep the reason: a tool that exits 1 with an empty runner
# log is indistinguishable from a broken invocation. The committed
# packages/bio-core/deny.toml is the single source of lint levels; no
# --deny warnings override (docs/dev/bio-core-wheel-abi-tags.md).
DENY_RC=0
(cd "${CRATE_DIR}" && cargo deny check) > "${EVIDENCE_DIR}/cargo-deny.txt" 2>&1 || DENY_RC=$?
if (( DENY_RC != 0 )); then
  echo "bio-core supply chain: deny exited ${DENY_RC}; output follows" >&2
  sed -e 's/^/  /' "${EVIDENCE_DIR}/cargo-deny.txt" >&2 || true
  # The policy is what decides the lint levels now, so a red check here is
  # either a real finding or a config error -- and the config error is the one
  # that just cost a full run: `--deny warnings` used to override the committed
  # deny.toml from outside. Say which file was in force.
  echo "bio-core supply chain: policy in force: ${CRATE_DIR}/deny.toml" >&2
  [[ -f "${CRATE_DIR}/deny.toml" ]] && sed -e 's/^/  /' "${CRATE_DIR}/deny.toml" | head -n 40 >&2 || \
    echo "bio-core supply chain: deny.toml is MISSING; the check ran with defaults" >&2
fi

# One report, not two: the release lane has a single Rust finding set to sign.
python3 "${SHARED_DIR}/check_bio_core_supply_chain.py" \
  "${EVIDENCE_DIR}/cargo-audit.json" "${AUDIT_RC}" "${DENY_RC}" "${REPORT}" \
  --audit-version-file "${AUDIT_VERSION_FILE}" \
  --deny-version-file "${DENY_VERSION_FILE}" \
  --expect-audit "${AUDIT_VERSION}" --expect-deny "${DENY_VERSION}" || exit 1

step "bio-core supply chain: PASS (${REPORT})"
