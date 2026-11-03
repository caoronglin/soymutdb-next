#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — provision the system build prerequisites for the worker science
# stack in a Python 3.15 CI container.
# =============================================================================
# `pip install -e "apps/worker[dev]"` pulls the worker's runtime science stack
# (scanpy -> anndata -> h5py). On Python 3.15, h5py 3.16 ships no wheel, so pip
# builds it from the sdist. That build resolves HDF5 through pkg-config and
# fails on the bare `python:3.15` CI image with:
#
#   error: libhdf5.so: cannot open shared object file: No such file or directory
#   ERROR: Failed building wheel for h5py
#
# The production worker image already solves this in infra/docker/Dockerfile.worker:
# install libhdf5-dev + pkg-config and point h5py at Debian/Ubuntu's serial
# flavour (`hdf5-serial.pc`). This script applies the SAME recipe to the
# ephemeral CI container, so the CNB `python:3.15` stage and the GitHub
# ubuntu-latest runner install identical system packages. Keep the package list
# in sync with that Dockerfile's RUN apt-get block.
#
# Callers must export HDF5_PKGCONFIG_NAME=hdf5-serial before the worker pip
# install; see scripts/verify-backend-tests.sh, which owns that env var.
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

# Same packages as infra/docker/Dockerfile.worker. Only the HDF5 ones are
# needed here: the base python:3.15 image already carries a C toolchain, which
# is why pandas/cyvcf2/numcodecs built successfully before h5py failed.
DEBIAN_FRONTEND=noninteractive "${apt_cmd[@]}" update -qq
DEBIAN_FRONTEND=noninteractive "${apt_cmd[@]}" install -y --no-install-recommends \
  libhdf5-dev \
  pkg-config

# Fail loudly if the recipe did not actually produce the .pc file h5py needs,
# instead of letting pip die with an opaque "Unable to load dependency HDF5".
pkg-config --exists "${HDF5_PKGCONFIG_NAME:-hdf5-serial}" || {
  log "${HDF5_PKGCONFIG_NAME:-hdf5-serial} not found after install"
  exit 1
}
log "HDF5 build prerequisites ready (${HDF5_PKGCONFIG_NAME:-hdf5-serial})"
