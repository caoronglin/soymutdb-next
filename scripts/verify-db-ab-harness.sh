#!/usr/bin/env bash
# =============================================================================
# W6 database A/B harness gate.
#
# WHAT THIS GATE IS NOT
# ---------------------
# It is not a performance benchmark, and nothing it prints may be quoted as a
# performance result. CI runners are shared, throttled containers; the ratio
# between two arms there measures the runner, not the index. The local run that
# produced a 219x-326x spread already demonstrated the failure mode: the
# treatment median was 0.033-0.041 ms, so measurement noise dominated the
# denominator. A CI number would be one more sample of that, with less
# control over the machine.
#
# What this gate DOES assert is the first clause of the W6 acceptance
# criterion: the experiment is replayable, the two arms return identical rows,
# and the single mutated factor is isolated. A harness that cannot be re-run
# proves nothing about a database, and a harness that compares different result
# sets proves nothing at all.
#
# The performance question stays a separate exercise against a real data copy
# on a controlled host, reported with spread across repeated runs.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${REPO_ROOT}/apps/api/.venv/bin/python"
DRIVER="${REPO_ROOT}/scripts/run_db_ab_experiment.py"

# A small row count on purpose: this gate checks the harness, and a large
# fixture would only add minutes without testing anything the small one does not.
ROWS="${SOYMUTDB_AB_ROWS:-50000}"
ROUNDS="${SOYMUTDB_AB_ROUNDS:-5}"
DATABASE="soymutdb_abtest_w6"

log() { printf '[verify-db-ab] %s\n' "$*" >&2; }

if [[ ! -x "${PYTHON}" ]]; then
  log "apps/api virtualenv is required (it provides asyncpg)"
  exit 1
fi

# The driver imports asyncpg and the harness module, both of which live in the
# API virtualenv and the repo root respectively.
export PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1

# `with-postgres-service.sh` starts a disposable PostgreSQL and exports
# SOYMUTDB_TEST_DATABASE_URL for its body. The driver needs a base URL whose
# credentials and host it can reuse while swapping in its own database name.
# It speaks asyncpg directly, so the SQLAlchemy `+asyncpg` dialect prefix that
# the API tests carry has to come off first.
# The scoped-run form is used rather than `--print-exports` plus `source`,
# because a CNB stage body runs under dash where `source` does not exist.
bash "${REPO_ROOT}/scripts/with-postgres-service.sh" -- bash -c '
  set -euo pipefail
  base="postgresql://${SOYMUTDB_TEST_DATABASE_URL#postgresql+asyncpg://}"

  # The driver replaces only the database component, so point it at a database
  # that always exists and let it create its own disposable one.
  admin="${base%/*}/postgres"

  printf "[verify-db-ab] %s\n" \
    "running the A/B harness (rows=$1 rounds=$2)" \
    "this is a reproducibility gate; its timings are not a performance result" >&2

  exec "$3" "$4" --url "${admin}" --database "$5" --rows "$1" --rounds "$2"
' _ "${ROWS}" "${ROUNDS}" "${PYTHON}" "${DRIVER}" "${DATABASE}"

log "harness replayed: arms agreed on rows, single factor isolated"
