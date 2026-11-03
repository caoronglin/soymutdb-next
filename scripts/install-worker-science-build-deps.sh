#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — provision the system build prerequisites for the worker science
# stack in a Python 3.15 CI container.
# =============================================================================
# The worker's locked runtime graph has NO cp315 wheels for h5py, cyvcf2,
# pandas and numcodecs, so both `pip install -e "apps/worker[dev]"` (backend
# gate) and `uv run --locked --no-dev --project apps/worker` (dependency
# governance's license/pip-audit analyzers) build those sdists from source.
# On a bare `python:3.15` CI image the first failure is h5py:
#
#   error: libhdf5.so: cannot open shared object file: No such file or directory
#   ERROR: Failed building wheel for h5py
#
# The production worker image already solves this in infra/docker/Dockerfile.worker:
# build-essential, zlib/bzip2/xz headers for cyvcf2's bundled htslib, and
# libhdf5-dev + pkg-config with HDF5 pointed at Debian/Ubuntu's serial flavour
# (`hdf5-serial.pc`). This script applies the SAME recipe to the ephemeral CI
# container, so the CNB `python:3.15` stages and the GitHub ubuntu-latest
# runner install identical system packages. Keep the package list in sync with
# that Dockerfile's RUN apt-get block. The autotools are extra: the CI frontend
# image has no `autoreconf`, which cyvcf2's CMake runs on its bundled htslib,
# while the production builder's base image provides them.
#
# Every CNB stage runs in its own fresh container: the `Compiler prerequisites`
# and `API + Worker verification` stages' apt installs do NOT reach the
# `Dependency governance` stage, which is why it calls this script too.
#
# Callers must export HDF5_PKGCONFIG_NAME=hdf5-serial before the worker build;
# see scripts/verify-backend-tests.sh and the dependency-governance job.
#
# Usage: bash scripts/install-worker-science-build-deps.sh
# =============================================================================
set -euo pipefail

log() { printf '[worker-science-deps] %s\n' "$*" >&2; }

# Idempotent: a warm container or a developer machine may already have HDF5.
if command -v pkg-config >/dev/null 2>&1 \
    && pkg-config --exists "${HDF5_PKGCONFIG_NAME:-hdf5-serial}" 2>/dev/null; then
  log "HDF5 pkg-config ${HDF5_PKGCONFIG_NAME:-hdf5-serial} already available"
  exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
  log "apt-get unavailable; cannot provision HDF5 build deps"
  log "the worker science stack needs libhdf5-dev + pkg-config on Python 3.15"
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

# Same package families as infra/docker/Dockerfile.worker:
#   build-essential  C/C++ compiler for h5py, pandas, numcodecs, cyvcf2
#   pkg-config       h5py resolves HDF5 through it (serial flavour)
#   libhdf5-dev      h5py's HDF5 headers/libraries
#   zlib1g-dev
#   libbz2-dev       cyvcf2 builds a bundled htslib; its configure picks up
#   liblzma-dev      these system compression headers when present
#   autoconf
#   automake         cyvcf2's CMake runs `autoreconf -i` on the bundled
#   libtool          htslib, which needs the autotools at build time
DEBIAN_FRONTEND=noninteractive "${apt_cmd[@]}" update -qq
DEBIAN_FRONTEND=noninteractive "${apt_cmd[@]}" install -y --no-install-recommends \
  build-essential \
  pkg-config \
  libhdf5-dev \
  zlib1g-dev \
  libbz2-dev \
  liblzma-dev \
  autoconf \
  automake \
  libtool

# Fail loudly if the recipe did not actually produce the .pc file h5py needs,
# instead of letting pip die with an opaque "Unable to load dependency HDF5".
pkg-config --exists "${HDF5_PKGCONFIG_NAME:-hdf5-serial}" || {
  log "${HDF5_PKGCONFIG_NAME:-hdf5-serial} not found after install"
  exit 1
}
log "HDF5 build prerequisites ready (${HDF5_PKGCONFIG_NAME:-hdf5-serial})"
