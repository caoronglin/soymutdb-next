#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — Rust bio-core verification (single source for CI and local runs)
# =============================================================================
# Owns the ordered, blocking gates for packages/bio-core:
#   toolchain pin → fmt → clippy → cargo test (unit + golden + adversarial) →
#   maturin wheel → wheel import smoke → real scientific function smoke.
#
# A wheel that only builds but is never installed and imported is NOT a pass:
# the last two steps exercise the exact artifact the API/Worker images consume.
# Missing prerequisites fail the script; they never report SKIPPED-as-PASS.
#
# This job is the SINGLE producer of the cp315 wheel. It writes the artifact to
# artifacts/wheels/ and leaves it there so the backend gate can install that
# exact file (spec §13.5) without owning a second Rust toolchain. The api-tests
# stage is a bare python:3.15 with no cargo/curl/C linker; building the crate
# there would both fail on the first CI run and add minutes of uncached native
# compile to every PR. Stale wheels are removed first so a consumer can never
# install a wheel from a different revision.
#
# Usage: bash scripts/verify-bio-core.sh
# Env:   SOYMUTDB_BIO_CORE_PYTHON       CPython 3.15 interpreter (wheel target)
#        SOYMUTDB_BIO_CORE_WHEEL_DIR    wheel output dir (default artifacts/wheels)
#        CARGO_HOME / RUSTUP_HOME       optional rustup storage
#        SOYMUTDB_BIO_CORE_SKIP_WHEEL=1 is NOT supported: no silent skips.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

CRATE_DIR="${REPO_ROOT}/packages/bio-core"
WHEEL_DIR="${SOYMUTDB_BIO_CORE_WHEEL_DIR:-${REPO_ROOT}/artifacts/wheels}"
PY="${SOYMUTDB_BIO_CORE_PYTHON:-python3.15}"

step() { printf '\n==> %s\n' "$*"; }

export CARGO_HOME="${CARGO_HOME:-${TMPDIR:-/tmp}/soymutdb-cargo}"
export RUSTUP_HOME="${RUSTUP_HOME:-${TMPDIR:-/tmp}/soymutdb-rustup}"
export PATH="${CARGO_HOME}/bin:${PATH}"

# The crate pins its own toolchain; `cargo` respects rust-toolchain.toml, so CI
# and a developer workstation resolve the same compiler without a second pin
# living in this script.
# The pinned compiler itself is declared ONCE in
# packages/bio-core/rust-toolchain.toml.  CI images that do not ship Rust get
# it through rustup here; the crate's own pin then selects the exact channel,
# so no second version lives in this script or in either provider's YAML.
if ! command -v cargo >/dev/null 2>&1; then
  step "Bootstrap the pinned Rust toolchain"
  command -v curl >/dev/null 2>&1 || { echo "missing curl (needed for rustup)" >&2; exit 1; }
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --profile minimal --default-toolchain none --no-modify-path
fi
command -v cargo >/dev/null 2>&1 || { echo "missing cargo after bootstrap" >&2; exit 1; }
command -v rustc >/dev/null 2>&1 || { echo "missing rustc after bootstrap" >&2; exit 1; }
# A C linker is required by several native crates; fail loudly instead of
# letting a build error masquerade as a test failure.
command -v cc >/dev/null 2>&1 || {
  echo "missing C linker (cc): install build-essential" >&2
  exit 1
}

step "Rust toolchain"
# rustup resolves rust-toolchain.toml from the CURRENT WORKING DIRECTORY, not
# from --manifest-path.  The pin lives in the crate dir, so every toolchain
# invocation below must run there; from the repo root a clean machine with no
# default toolchain fails before any gate executes.
(
  cd "${CRATE_DIR}"
  rustc --version
  cargo --version
)

step "Rust kernel ↔ advertised capability surface"
# The numeric parity guard only compares values that exist on BOTH sides, so
# dropping a program/format from `capabilities` reads as "no difference" while
# the route and kernel binding stay live. Derive the surface from the routes
# and the /inspect dispatch table, then prove the guard is load-bearing.
"${PY}" scripts/check_bio_core_capability_surface.py --self-test
"${PY}" scripts/check_bio_core_capability_surface.py

step "Rust kernel ↔ advertised capability parity"
# GET /tools/sequence/capabilities advertises input limits that the Rust
# kernel enforces. Both sides are committed sources; a one-sided edit would
# advertise a bound the kernel rejects (or vice versa) with no OpenAPI drift
# and no failing unit test. Read the bytes before the expensive build so the
# failure is named early, and prove the guard is load-bearing via --self-test.
"${PY}" scripts/check_bio_core_capability_parity.py --self-test
"${PY}" scripts/check_bio_core_capability_parity.py

step "Lock file consistency"
# --locked makes an uncommitted dependency resolution a hard failure.
(cd "${CRATE_DIR}" && cargo metadata --locked --format-version 1 >/dev/null)
echo "Cargo.lock matches Cargo.toml"

step "cargo fmt"
(cd "${CRATE_DIR}" && cargo fmt --all -- --check)

step "cargo clippy"
(cd "${CRATE_DIR}" && cargo clippy --all-targets --all-features --locked -- -D warnings)

step "cargo test (unit + golden + adversarial)"
(cd "${CRATE_DIR}" && cargo test --all-targets --locked)

step "maturin wheel (CPython 3.15)"
"${PY}" --version
# Provisioning lives here, in the shared job body -- NOT in either provider's
# YAML. scripts/test_ci_job_contracts.py asserts that no `maturin`/`cargo`
# command is inlined into .cnb.yml or the GitHub mirror, so both providers run
# the exact same pinned bytes. The pin is the one declared in the crate's
# pyproject.toml / spec §9.2.
if ! "${PY}" -m maturin --version >/dev/null 2>&1; then
  step "Install pinned maturin for ${PY}"
  "${PY}" -m pip install --quiet "maturin==1.16.0" || {
    echo "failed to install maturin==1.16.0 for ${PY}" >&2
    exit 1
  }
fi
"${PY}" -m maturin --version >/dev/null 2>&1 || {
  echo "missing maturin for ${PY} after install" >&2
  exit 1
}
mkdir -p "${WHEEL_DIR}"
# /workspace is shared across CNB stages and cached between builds. Remove any
# wheel left by an earlier revision so the backend gate cannot install a stale
# artifact; maturin then writes exactly one wheel for THIS commit.
rm -f "${WHEEL_DIR}"/soymutdb_bio_core-*.whl
(cd "${CRATE_DIR}" && "${PY}" -m maturin build --release --locked \
  --interpreter "${PY}" --out "${WHEEL_DIR}")

WHEEL="$(ls -1 "${WHEEL_DIR}"/soymutdb_bio_core-*-cp315-*.whl 2>/dev/null | head -1)"
[[ -n "${WHEEL}" ]] || { echo "no cp315 wheel produced in ${WHEEL_DIR}" >&2; exit 1; }
echo "wheel: ${WHEEL}"

step "wheel import + real scientific smoke"
# Build an isolated venv: the CI image's system Python 3.15 has NO pytest
# (real build cnb-6e3-1k6jsptrg died with "No module named pytest").  Creating
# a throwaway venv installs both pytest and the exact wheel without mutating
# the pipeline image, and keeps this gate identical on CNB / GitHub / a laptop.
SMOKE_DIR="$(mktemp -d)"
trap 'rm -rf "${SMOKE_DIR}"' EXIT
"${PY}" -m venv "${SMOKE_DIR}/venv"
SMOKE_PY="${SMOKE_DIR}/venv/bin/python"
"${SMOKE_PY}" -m pip install --quiet pytest "${WHEEL}"
"${SMOKE_PY}" - <<'PY'
import soymutdb_bio_core as c

cap = c.capabilities()
assert cap["engine_version"], "missing engine version"
assert cap["genetic_codes"] == [1], "only the standard genetic code may be advertised"
assert c.reverse_complement("ATGCRY") == "RYGCAT", "IUPAC reverse complement"
assert c.reverse_complement("AUG", alphabet="rna") == "CAU", "RNA reverse complement"
assert c.sequence_statistics("ACGTNN")["denominator"] == 4, "GC denominator"
assert c.kmer_counts("ACGTACGTNACG", 4)["distinct_kmers"] == 3, "spec k-mer golden"
assert c.translate_sequence("ATGAAATAA")["protein"] == "MK*", "standard translation"
assert c.align_pairwise("ACGT", "ACGT")["cigar"] == "4M", "pairwise CIGAR"
q = c.overlap_intervals([(10, 20, 0), (10, 20, 1)], [(10, 20)])[0]
assert q["overlap_count"] == 2 and q["covered_bp"] == 10, "count vs union coverage"
assert c.validate_fasta(b">g\nACGT\n")["total_records"] == 1, "FASTA validation"
assert c.validate_bed(b"chr1\t10\t20\n") == 1, "BED validation"
try:
    c.translate_sequence("ATG", genetic_code_id=2)
except c.BioCoreException as e:
    assert e.args[0] == "UNKNOWN_GENETIC_CODE", "no silent genetic-code fallback"
else:
    raise AssertionError("unimplemented genetic code was not rejected")
print("bio-core wheel smoke: PASS")
PY

step "wheel contract tests (pytest against the installed artifact)"
"${SMOKE_PY}" -m pytest "${CRATE_DIR}/python_tests" -q

step "capability-parity guard regression (the guard itself must be load-bearing)"
# The isolated venv above has pytest; the guard's own suite proves a weakened
# comparison is caught, rather than leaving an unexercised file in the repo.
"${SMOKE_PY}" -m pytest scripts/test_bio_core_capability_parity.py -q

step "capability-surface guard regression (the guard itself must be load-bearing)"
"${SMOKE_PY}" -m pytest scripts/test_bio_core_capability_surface.py scripts/test_bio_core_capability_surface_wiring.py -q

echo "==> bio-core verification: PASS"
