#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — provision the system build prerequisites for the worker science
# stack in a Python 3.15 CI container.
# =============================================================================
# On Python 3.15 the worker's science stack ships no manylinux wheels, so pip
# (and the governance analyzers' `uv run --project apps/worker`) compile sdists:
#
#   * h5py resolves HDF5 through pkg-config and needs libhdf5-dev;
#   * cyvcf2 builds a bundled htslib, whose configure probes zlib/bzip2/xz
#     headers and invokes autotools (autoreconf / libtoolize);
#   * pandas, numcodecs, cyvcf2 and pysam all need a C/C++ toolchain;
#   * psycopg2-binary uses pg_config from libpq-dev.
#
# infra/docker/Dockerfile.worker installs this same set for the production
# image. Keep the package list in sync with that Dockerfile's apt-get block.
# Both the backend test gate (verify-backend-tests.sh) and the dependency
# governance gate (ci-job-steps.sh dependency_governance_step) call this one
# script, so CNB and GitHub execute identical bytes.
#
# Callers must export HDF5_PKGCONFIG_NAME=hdf5-serial before the worker
# resolution. Two gates reach the worker runtime on Python 3.15 and both own
# that export: scripts/verify-backend-tests.sh (worker editable install) and
# scripts/ci-job-steps.sh (dependency-governance license analyzer, whose
# `uv run --locked --project apps/worker` also builds h5py from sdist).
#
# Usage: bash scripts/install-worker-science-build-deps.sh
# =============================================================================
set -euo pipefail

log() { printf '[worker-science-deps] %s\n' "$*" >&2; }

# Idempotent only when the whole toolchain is present. Checking HDF5 alone
# used to skip containers that already had libhdf5-dev but no autotools, and
# the governance license analyzer then died building cyvcf2's bundled htslib
# (CMake: "cyvcf2: building bundled htslib" -> execute_process failure).
prerequisites_present() {
  command -v cc >/dev/null 2>&1 &&
    command -v pkg-config >/dev/null 2>&1 &&
    command -v autoreconf >/dev/null 2>&1 &&
    command -v libtoolize >/dev/null 2>&1 &&
    pkg-config --exists "${HDF5_PKGCONFIG_NAME:-hdf5-serial}" 2>/dev/null
}

PACKAGES=(
  build-essential
  pkg-config
  libhdf5-dev
  zlib1g-dev
  libbz2-dev
  liblzma-dev
  libpq-dev
  autoconf
  automake
  libtool
)

if prerequisites_present; then
  log "worker science build prerequisites already present; nothing to install"
  exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
  log "apt-get unavailable; cannot provision the worker science build deps"
  log "the worker science stack needs the C/HDF5/htslib toolchain on Python 3.15"
  exit 1
fi

apt_cmd=(apt-get)
if [[ "$(id -u)" -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || {
    log "not root and sudo is unavailable"
    exit 1
  }
  apt_cmd=(sudo -E apt-get)
fi

DEBIAN_FRONTEND=noninteractive "${apt_cmd[@]}" update -qq
DEBIAN_FRONTEND=noninteractive "${apt_cmd[@]}" install -y --no-install-recommends \
  "${PACKAGES[@]}"

# Fail loudly if the recipe did not actually produce the .pc file h5py needs,
# instead of letting pip die with an opaque "Unable to load dependency HDF5".
pkg-config --exists "${HDF5_PKGCONFIG_NAME:-hdf5-serial}" || {
  log "${HDF5_PKGCONFIG_NAME:-hdf5-serial} not found after install"
  exit 1
}
command -v autoreconf >/dev/null 2>&1 || {
  log "autoreconf not found after install; cyvcf2's htslib build would fail"
  exit 1
}
log "worker science build prerequisites ready (${HDF5_PKGCONFIG_NAME:-hdf5-serial})"
