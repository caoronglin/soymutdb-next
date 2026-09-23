#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — unified smoke test
# =============================================================================
# One entry point that runs the smoke layers that are POSSIBLE in the current
# environment, reports each layer honestly, and exits non-zero if a layer that
# ran failed.
#
# Layers (select with --profile, default: all applicable)
#   contracts   Dependency-free contract/unit checks: deployment workflows,
#               platform delivery, site-artifact isolation, worker image
#               boundary, supply-chain, Kubernetes manifests, ClickHouse
#               migration assertions, CI job definitions. No Docker needed.
#   static      Static HTML/CSS/JS health of the built web + admin bundles:
#               entry points, checksums, placeholder scan, referenced
#               same-origin assets resolve.
#   runtime     Real HTTP smoke of the API: migrations -> uvicorn -> health ->
#               release-context/search chain. Requires a disposable
#               PostgreSQL reachable via SOYMUTDB_DATABASE_URL.
#   e2e         Browser smoke of the public site (Playwright). Requires
#               Node + Playwright browsers; SMOKE_BASE_URL selects the target.
#   images      Container smoke: build, runtime import/health, Trivy, SBOM.
#               Requires a Docker daemon.
#
# Usage
#   bash scripts/smoke.sh                     # every layer that can run here
#   bash scripts/smoke.sh --profile contracts
#   bash scripts/smoke.sh --profile static --static-dir apps/web/dist
#   bash scripts/smoke.sh --list
#
# Exit codes
#   0  every executed layer passed
#   1  at least one executed layer failed
#   2  usage error
#
# A layer whose prerequisites are missing is reported SKIPPED with the exact
# prerequisite, never as a pass. That distinction is the whole point: a smoke
# test that silently no-ops is worse than no smoke test.
#
# Strictness note: this script deliberately uses `set -uo pipefail` WITHOUT
# `-e`. Exiting on the first failure would hide the remaining layers and the
# summary. Every layer captures its own return code and the driver decides the
# final exit status; scripts/test_ci_job_contracts.py encodes this exception.
# =============================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

PROFILE="all"
STATIC_DIR=""
PYTHON_BIN="${SOYMUTDB_SMOKE_PYTHON:-python3}"

usage() {
  sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) [[ $# -ge 2 ]] || { echo "--profile requires a value" >&2; exit 2; }; PROFILE="$2"; shift 2 ;;
    --static-dir) [[ $# -ge 2 ]] || { echo "--static-dir requires a value" >&2; exit 2; }; STATIC_DIR="$2"; shift 2 ;;
    --list) printf '%s\n' contracts static runtime e2e images; exit 0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "${PROFILE}" in
  all|contracts|static|runtime|e2e|images) ;;
  *) echo "unknown profile: ${PROFILE}" >&2; exit 2 ;;
esac

PASSED=()
FAILED=()
SKIPPED=()

have() { command -v "$1" >/dev/null 2>&1; }

run_layer() {
  local name="$1"; shift
  printf '\n\033[1m== smoke layer: %s\033[0m\n' "${name}"
  if "$@"; then
    PASSED+=("${name}")
  else
    FAILED+=("${name}")
    printf '\033[31mlayer %s FAILED\033[0m\n' "${name}" >&2
  fi
}

skip_layer() {
  local name="$1" reason="$2"
  printf '\n\033[1m== smoke layer: %s\033[0m\n' "${name}"
  printf '\033[33mSKIPPED: %s\033[0m\n' "${reason}"
  SKIPPED+=("${name} (${reason})")
}

# -----------------------------------------------------------------------------
# Layer: contracts — dependency-free contract and unit checks
# -----------------------------------------------------------------------------
smoke_contracts() {
  # These suites are plain test files under scripts/ (not an installable
  # package), so pytest collects them by path. Pytest is the only supported
  # runner: several suites need its `tmp_path` fixture, and a hand-rolled
  # fallback would silently skip exactly the isolation cases that matter.
  local tests=(
    scripts/test_deployment_workflows.py
    scripts/test_platform_delivery_contracts.py
    scripts/test_dependency_governance_contracts.py
    scripts/test_install_python_workspace.py
    scripts/test_site_artifact_isolation.py
    scripts/test_supply_chain_contracts.py
    scripts/test_production_compose_contract.py
    scripts/test_development_compose_contract.py
    scripts/test_kubernetes_delivery_contracts.py
    scripts/test_backup_restore_contracts.py
    scripts/test_ci_job_contracts.py
    scripts/test_dockerfile_contracts.py
  )
  # Suites that need an interpreter or service this smoke layer does not own
  # (worker source analysis runs under the API virtualenv; tunnel/compose drift
  # and OpenAPI visibility need the API app). They are reported separately so a
  # local run stays honest about what it did and did not verify.
  local environment_bound=(
    scripts/test_worker_image_boundary.py
    scripts/test_cloudflare_tunnel_contract.py
    scripts/test_contract_visibility.py
    scripts/test_slow_query_report.py
  )

  if ! "${PYTHON_BIN}" -m pytest --version >/dev/null 2>&1; then
    echo "pytest is required for the contracts smoke layer" >&2
    echo "install it with: ${PYTHON_BIN} -m pip install pytest" >&2
    return 1
  fi

  local rc=0
  # Toolchain pins are checked by a standalone guard rather than a pytest case:
  # it must also be runnable from pre-commit and from a developer machine
  # without the test dependencies. It is part of this layer because a pin
  # mismatch produces a build that differs between two machines on the same
  # commit, which is exactly what a contract layer exists to catch.
  "${PYTHON_BIN}" scripts/check-toolchain-pins.py || rc=$?
  # Workspace exports are checked the same way, and for the same reason: a
  # gitignore pattern that swallows an imported source directory (the `build/`
  # rule did exactly that to packages/shared/src/build/) leaves every local
  # build green while a clean clone has no source for the import at all.
  "${PYTHON_BIN}" scripts/check_workspace_exports.py || rc=$?
  # nginx security-header fragments and the locations that must re-include
  # them. Not part of the frontend gate: the configs cover the API and data
  # planes too, so a backend-only change can break them.
  "${PYTHON_BIN}" scripts/check_nginx_security_headers.py || rc=$?
  "${PYTHON_BIN}" -m pytest "${tests[@]}" -q || rc=$?
  echo
  echo "-- environment-bound contract suites (reported, not gating here) --"
  "${PYTHON_BIN}" -m pytest "${environment_bound[@]}" -q || true
  return "${rc}"
}

# -----------------------------------------------------------------------------
# Layer: static — built bundle health
# -----------------------------------------------------------------------------
smoke_static() {
  local dir="${STATIC_DIR}"
  if [[ -z "${dir}" ]]; then
    if [[ -d apps/web/dist ]]; then
      dir="apps/web/dist"
    else
      echo "no built artifact at apps/web/dist" >&2
      return 1
    fi
  fi
  [[ -d "${dir}" ]] || { echo "missing static directory: ${dir}" >&2; return 1; }

  echo "artifact: ${dir}"
  test -f "${dir}/index.html" || { echo "missing index.html" >&2; return 1; }
  test -s "${dir}/index.html" || { echo "empty index.html" >&2; return 1; }

  # Deployment-facing HTML must not bake placeholder origins.
  if grep -RInE 'api\.example\.com|jbrowse\.example\.com|change-me|CHANGE_ME' \
      "${dir}" --include='*.html' --include='*.js' --include='*.json' >/dev/null 2>&1; then
    echo "placeholder origin found in ${dir}" >&2
    grep -RInE 'api\.example\.com|jbrowse\.example\.com|change-me|CHANGE_ME' \
      "${dir}" --include='*.html' --include='*.js' --include='*.json' >&2 | head -10
    return 1
  fi

  # Every same-origin asset referenced by the entry HTML must exist.
  local missing=0
  local asset
  while IFS= read -r asset; do
    [[ -z "${asset}" ]] && continue
    case "${asset}" in
      http://*|https://*|//*|data:*|mailto:*|"#"*) continue ;;
    esac
    local relative="${asset#/}"
    relative="${relative%%\?*}"
    if [[ ! -e "${dir}/${relative}" ]]; then
      echo "missing referenced asset: ${asset}" >&2
      missing=1
    fi
  done < <(grep -oE '(src|href)="[^"]+"' "${dir}/index.html" | sed -E 's/.*="([^"]+)"/\1/' | sort -u)
  [[ "${missing}" -eq 0 ]] || return 1

  # If the artifact was built with checksums, prove them.
  if [[ -f "${dir}/SHA256SUMS" ]]; then
    (cd "${dir}" && sha256sum -c SHA256SUMS) || return 1
  fi

  echo "static smoke passed for ${dir}"
  return 0
}

# -----------------------------------------------------------------------------
# Layer: runtime — real API HTTP smoke
# -----------------------------------------------------------------------------
smoke_runtime() {
  if [[ ! -x apps/api/.venv/bin/python ]]; then
    echo "missing apps/api/.venv (run: python -m venv apps/api/.venv && pip install -e packages/jobs-py -e \"apps/api[dev]\")" >&2
    return 1
  fi
  if [[ -z "${SOYMUTDB_DATABASE_URL:-}" ]]; then
    echo "SOYMUTDB_DATABASE_URL is required (disposable PostgreSQL only)" >&2
    return 1
  fi
  bash scripts/deploy/smoke.sh --environment development
}

# -----------------------------------------------------------------------------
# Layer: e2e — browser smoke
# -----------------------------------------------------------------------------
smoke_e2e() {
  [[ -d e2e ]] || { echo "missing e2e/ directory" >&2; return 1; }
  [[ -d e2e/node_modules ]] || { echo "run 'npm ci' inside e2e/ first" >&2; return 1; }
  (
    cd e2e
    CI=1 npx playwright test "${PLAYWRIGHT_EXTRA_ARGS:-}"
  )
}

# -----------------------------------------------------------------------------
# Layer: images — container smoke (delegates to the release image verifier)
# -----------------------------------------------------------------------------
smoke_images() {
  SOYMUTDB_CI_EXPORT=0 bash scripts/build-release-image.sh
}

# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------
should_run() {
  [[ "${PROFILE}" == "all" || "${PROFILE}" == "$1" ]]
}

if should_run contracts; then
  run_layer contracts smoke_contracts
fi

if should_run static; then
  if [[ -d apps/web/dist || -n "${STATIC_DIR}" ]]; then
    run_layer static smoke_static
  else
    skip_layer static "no built artifact (run: pnpm build:web)"
  fi
fi

if should_run runtime; then
  if [[ -x apps/api/.venv/bin/python && -n "${SOYMUTDB_DATABASE_URL:-}" ]]; then
    run_layer runtime smoke_runtime
  else
    skip_layer runtime "requires apps/api/.venv and SOYMUTDB_DATABASE_URL (disposable PostgreSQL)"
  fi
fi

if should_run e2e; then
  if [[ -d e2e/node_modules ]]; then
    run_layer e2e smoke_e2e
  else
    skip_layer e2e "requires 'npm ci' inside e2e/ and Playwright browsers"
  fi
fi

if should_run images; then
  if have docker && docker info >/dev/null 2>&1; then
    run_layer images smoke_images
  else
    skip_layer images "requires a reachable Docker daemon"
  fi
fi

printf '\n\033[1m== smoke summary\033[0m\n'
printf 'profile: %s\n' "${PROFILE}"
printf 'passed:  %d%s\n' "${#PASSED[@]}" "${PASSED:+ [${PASSED[*]}]}"
printf 'failed:  %d%s\n' "${#FAILED[@]}" "${FAILED:+ [${FAILED[*]}]}"
printf 'skipped: %d%s\n' "${#SKIPPED[@]}" "${SKIPPED:+ [${SKIPPED[*]}]}"

if [[ "${#FAILED[@]}" -gt 0 ]]; then
  printf '\n\033[31mSMOKE FAIL\033[0m\n' >&2
  exit 1
fi

printf '\n\033[32mSMOKE PASS\033[0m\n'
