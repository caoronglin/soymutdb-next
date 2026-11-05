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
#   bash scripts/smoke.sh --profile static --static-dir apps/web/dist/external
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
    # PR #135 shipped this wiring suite but no gate collected it: deleting
    # the parity guard's two invocations from verify-bio-core.sh stayed green.
    scripts/test_bio_core_capability_parity_wiring.py
    # The error-code dev docs state suite counts in prose; no gate read them,
    # so a merge adding a test shipped a stale number with a green layer. Pin
    # each sentence to the count derived from the committed sources.
    scripts/test_error_code_doc_counts.py
    # Pin the fallback's two-part declaration shape from outside the guard:
    # a single-file edit must not be able to drop both the behaviour and its
    # own self-test plant.
    scripts/test_api_error_code_fallback_declaration.py
    # The contract guard's own regression suite. It proves the guard still has
    # a live signal (planted drifts are caught) and pins the gate wiring, so
    # this row is what keeps the call above from being deleted silently.
    scripts/test_check_error_code_contract.py
    # The catalog guard's regression suite: proves the plants fail closed and
    # a coordinated source + artifact prune still reddens the guard. Pinning
    # the collection here keeps both --self-test calls above load-bearing.
    scripts/test_error_code_catalog_contract.py
    scripts/test_deployment_workflows.py
    # Behavior contracts injected by app.main (x-idempotent / x-pagination /
    # x-error-codes / documented 429 / uniform 500) are client-visible, but
    # a source+artifact co-reversion keeps check-contract.sh green. Pin them
    # against the committed bytes; stdlib-only, no API import needed.
    scripts/test_openapi_behavior_contracts.py
    scripts/test_platform_delivery_contracts.py
    scripts/test_dependency_governance_contracts.py
    scripts/test_install_python_workspace.py
    scripts/test_clickhouse_migration_contracts.py
    scripts/test_import_capability_contracts.py
    scripts/test_motion_policy.py
    # The self-hosted CJK font subsets are committed assets: a new Chinese UI
    # string, a dropped manifest or a full-font recommit must fail a gate, not
    # silently undo the first-load payload reduction.
    scripts/test_portal_font_subset.py
    scripts/test_site_artifact_isolation.py
    # The document-level info/tags block lives in exactly one committed
    # artifact (openapi.d.ts drops it) and is a reviewed contract: a
    # source+export co-revert keeps check-contract.sh green. Freeze it to
    # a hand-written golden lock; stdlib-only, no 3.15 venv.
    scripts/test_openapi_document_metadata_guard.py
    scripts/test_production_artifact_scan.py
    scripts/test_supply_chain_contracts.py
    scripts/test_production_compose_contract.py
    scripts/test_development_compose_contract.py
    scripts/test_kubernetes_delivery_contracts.py
    # The MCP manifest, server.py _api_request calls and the published
    # OpenAPI operations are three declarations of the same endpoints. The
    # generated-client contract gate never reads apps/mcp-server/**, so a
    # renamed backend path can ship self-consistent artifacts while the MCP
    # tools 404. This guard reconciles them from committed bytes.
    scripts/test_mcp_openapi_parity.py
    scripts/test_backup_restore_contracts.py
    scripts/test_native_backup_runtime.py
    # One code = one sentence across the FFI boundary; guards read committed
    # Rust bytes, so no wheel or Rust toolchain is needed.
    scripts/test_kernel_error_messages.py
    scripts/test_kernel_error_messages_wiring.py
    scripts/test_ci_job_contracts.py
    # A stale-base branch carried an older variants row key AND the shorter
    # test file that matches it: vitest stayed green (2/2) and no contract gate
    # reads frontend source. This suite proves the guard fails on that pair.
    scripts/test_variant_row_key_contract.py
    # PR #117 doubled /api/v1 in every sequence URL; this suite proves the
    # base-path guard fails on that exact shape and on weaker variants.
    scripts/test_api_client_base_path_guard.py
    # The committed OpenAPI snapshot is an export, not a source file. A hand
    # edit to it (4975dbd inlined a hoisted type alias and deleted its
    # component) surfaces in CI only as "CONTRACT DEBT" from the frontend gate,
    # which names neither the file nor the reason. This suite names it, and
    # needs no Python 3.15.
    scripts/test_openapi_snapshot_contract.py
    # The runtime 422 handler always returns the unified ValidationErrorResponse
    # envelope, but setdefault("422") let FastAPI's auto HTTPValidationError win
    # on 235 operations: both committed artifacts agreed with each other while
    # typing a response the server never sends. This guard reads committed
    # bytes and pins the source contract; needs no Python 3.15.
    scripts/test_openapi_422_unified_envelope.py
    # Pin every $ref body in both committed artifacts to independent literal
    # fixed points: two per-component baselines (responses + requests) plus a
    # digest of the (method, path, status|requestBody, component) pair set, so
    # a regenerate that drifts both halves together AND a permutation of two
    # same-count bodies both fail. The envelope guard pins 4xx/5xx shapes and
    # the snapshot guard pins path/schema floors; neither counts success or
    # request bodies. Needs no Python 3.15.
    scripts/test_openapi_snapshot_body_integrity.py
    # The guards above pin the contract to literals in their own source, so
    # bumping a literal is a one-file edit that leaves every one of them green
    # with the artifacts untouched. This suite proves the sync guard reports
    # that edit, both directions, without touching the repository.
    scripts/test_openapi_baseline_sync.py
    # The offline browser-gate inventory (scripts/test_artifact_e2e_gate.py)
    # must fail a build when a gate is dropped from the sweep or the sweep stops
    # failing closed.
    scripts/test_artifact_e2e_gate.py
    # The interpolation guard fails closed on the `conds` vs {{conditions}} class
    # of bug; its self-test proves each synthetic negative case is caught.
    scripts/test_i18n_interpolation_guard.py
    scripts/test_bio_core_wheel_tags.py
    scripts/test_dockerfile_contracts.py
    # One native wheel per image architecture: cp315 + machine matching the
    # image. The guard reads committed bytes and the wheel's own WHEEL tag;
    # this suite proves each synthetic negative really fails.
    scripts/test_bio_core_wheel_abi.py
    # The supply-chain verdict is fail-closed on exit status, not stdout
    # substrings; these proofs cover the three shapes the heredoc parser
    # accepted (boolean `found`, error+warning, empty output).
    scripts/test_bio_core_supply_chain.py
    scripts/test_legacy_worker_test_contract.py
    scripts/test_custom_element_registration_contracts.py
    # The MCP manifest, server.py and the published operations are three
    # declarations of one REST surface, and no gate read apps/mcp-server/**: a
    # renamed API path left snapshot, generated client and backend agreeing
    # while the MCP tool 404s. It also pins the release scoping: the tools that
    # can read a data release must forward X-SoyMutDB-Release, or MCP answers
    # are computed against a different release than the caller asked for.
    #
    # The `--self-test` invocation of check_mcp_release_binding.py is NOT a
    # pytest path: this array is expanded verbatim into `pytest "${tests[@]}"`,
    # so a guard call here reaches pytest as an argument and the whole layer
    # dies with "unrecognized arguments: --self-test". It lives with the other
    # guard calls below instead.
    scripts/test_mcp_release_binding_wiring.py
    # /tools/sequence/inspect must validate the client payload before requiring
    # the kernel; this suite proves each ordering ablation is caught.
    scripts/test_format_inspect_validation_order.py
    infra/clickhouse/test_schema_contract.py
    # An unpublished assembly / unknown chromosome must answer 404 (release
    # boundary), not 503 (engine unavailable). bridge.require() used to run
    # first, so the 404 test could never reach its own assertion without a
    # wheel. This suite proves each ordering ablation is caught.
    scripts/test_interval_visibility_order.py
    # A clean checkout must be able to run this layer without a sibling stage's
    # node_modules; the guard's own ablations prove the wiring stays in place.
    # The 268 published operationIds are the keys of the generated
    # `operations` TypeScript interface. A coordinated source+artifact
    # co-revert (retype one symbol in both halves, re-pin both provenance
    # blob ids) kept every wired OpenAPI guard green on live bytes: no
    # guard read them. This suite proves the independent digest pin
    # reports that co-revert and every one-sided drift.
    scripts/test_openapi_operation_id_floor.py
    scripts/test_openapi_operation_parameter_floor.py
    # Field-level JSON Schema constraints (minimum/maxLength/pattern/
    # format/...) are published in the snapshot but emitted nowhere in
    # the generated client, so no two-artifact check can see one drift.
    # This suite proves an independent literal pins all 815 of them.
    scripts/test_openapi_field_constraints.py
    # Schema-level `required` arrays decide which generated TypeScript
    # properties are optional. A coordinated regenerate of both halves with
    # re-pinned provenance blob ids kept every wired OpenAPI guard green.
    scripts/test_openapi_required_fields.py
    scripts/check_openapi_published_enums.py
    # Component-schema property descriptions are published as generated
    # JSDoc @description lines. A byte-preserving co-revert of one line in
    # both artifacts (with provenance blob ids re-pinned) kept all eleven
    # wired OpenAPI guards green; no fixed point read the prose. Pin it.
    scripts/test_openapi_schema_descriptions.py
    # The per-operation response surface (status codes + content presence)
    # is client-visible but unread by every body digest for content-less
    # responses. This suite proves the independent literal pins it.
    scripts/test_openapi_response_surface.py
    scripts/test_openapi_operation_annotations.py
    # The registry guard's second-file assertions (the dedicated
    # "fails for the pin alone" report, its plant, and the companion
    # suite's own wiring) run ONLY here: the guard's --self-test is a
    # single file, so a one-file edit can weaken the report and keep
    # every wired gate green. Collecting this suite makes the CI-run
    # evidence two-file instead of one-file.
    scripts/test_contracts_registry_collection.py
    scripts/test_contracts_layer_self_containment.py
    # The error-code gate wiring guard judges its co-rename probe by the copied
    # tree's exit status. A clean control must be green first, or an incomplete
    # copy (a missing export_contract.py used to do exactly that) reads as a
    # caught co-rename. This suite pins that differential from a second file.
    scripts/test_error_code_gate_wiring.py
    # The 7-case companion for the OpenAPI auth-surface floor pins the
    # literal itself and both failure directions. No CI stage runs a plain
    # `pytest scripts/`, so without this entry only a local hand-run collects
    # it: register it in the gating array so the layer consumes it.
    scripts/test_openapi_auth_surface_floor.py
    # The console read `common.json` alone, so 87 `tools.sequence.*` keys that
    # only exist in the portal runtime bundles were reported missing while the
    # UI was rendered correctly -- and a real defect parked in a runtime bundle
    # stayed invisible. It now merges the same bundles `lib/i18n.ts` merges.
    # Registering it here is the point: unregistered, it only ever ran by hand
    # and its red could neither block nor be noticed.
    scripts/test_locale_language_purity.py
    # `variant_summaries` has no constraint tying `gene_id` to `assembly_id`
    # (issue #86): a v5 summary can point at a v4 gene and the release-wide
    # `variant_type` aggregate counted it. The behavioural test needs
    # PostgreSQL, so this suite is the only net in a clean checkout. Registering
    # it is the point -- unregistered, it never runs and its red cannot block.
    scripts/test_variant_summary_assembly_consistency.py
    # A red guard that cannot say which byte moved has not measured:
    # stdlib runners must render a named cause for every failed check.
    scripts/test_named_guard_diagnostics.py
    # The placeholder-origin regex is committed twice (smoke.sh static layer +
    # check-production-artifact.sh). Only the second scanner is read back
    # behaviourally; nothing parses smoke.sh's copy, so deleting an origin
    # there stays green. This suite pins both copies from a second file.
    scripts/test_static_placeholder_scan.py
    # Every wired --self-test guard must still execute its mutation cases.
    # The registry guard pins that a call exists, not that the body it
    # reaches survived. A no-op self_test() kept the whole layer green.
    scripts/test_contracts_self_test_teeth.py
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
  # The MCP tool inventory is declared three times (manifest.py, the
  # @mcp.tool bodies in server.py, the limiters in ratelimit.py) and nothing
  # compared them: a keyword added to one function was undiscoverable, a
  # deleted rate-limit guard left every limiter test green, and a limiter
  # swapped to the process-local backend multiplied the advertised budget by
  # the replica count. Reads committed bytes only -- no MCP package, no Redis.
  # Self-test mode, like the guards above, so this is one line here instead of
  # a row in the shared `tests[]` array.
  "${PYTHON_BIN}" scripts/check_mcp_manifest_reconcile.py --self-test || rc=$?
  # The release pin must survive the MCP tool layer: _api_request used to send a
  # fixed header set, so X-SoyMutDB-Release never left the process and MCP
  # answers were computed against a different release than the caller asked for.
  "${PYTHON_BIN}" scripts/check_mcp_release_binding.py --self-test || rc=$?
  # Rust kernel: the crate pins + CI job + wheel-install gate must exist even
  # when this layer has no compiled extension available.
  "${PYTHON_BIN}" scripts/check_bio_core_wheel.py --static || rc=$?
  # Multi-arch ABI/platform-tag ledger + single Rust supply-chain lane. Reads
  # committed bytes, so it holds even where no wheel or cargo exists.
  "${PYTHON_BIN}" scripts/check_bio_core_wheel_abi.py --ledger --self-test || rc=$?
  # Read the committed service bytes: the pytest suite exercises behaviour,
  # this guard catches the validation ordering being moved back at source.
  "${PYTHON_BIN}" scripts/check_format_inspect_validation_order.py || rc=$?
  # Workspace exports are checked the same way, and for the same reason: a
  # gitignore pattern that swallows an imported source directory (the `build/`
  # rule did exactly that to packages/shared/src/build/) leaves every local
  # build green while a clean clone has no source for the import at all.
  "${PYTHON_BIN}" scripts/check_workspace_exports.py || rc=$?
  # The two pinned OpenAPI baselines in the guards below are literals, so
  # bumping one is a one-file edit that turns every guard green with the
  # artifacts untouched -- the documented "update the baseline in the same
  # commit" escape hatch, with nothing checking the same-commit part. This
  # compares the literal to the artifacts (no git needed, so it holds in a
  # squash and on a shallow clone) and to the commit that moved it.
  "${PYTHON_BIN}" scripts/check_openapi_baseline_sync.py --self-test || rc=$?
  # The published OpenAPI auth surface (both security schemes + the per-op
  # HTTPBearer requirement on admin routes) is client-visible, but a co-revert
  # of main.py + openapi.json keeps check-contract.sh green. Pin it against
  # committed bytes; stdlib-only, no API import needed.
  "${PYTHON_BIN}" scripts/check_openapi_auth_surface.py --self-test || rc=$?
  # The three component-body guards pin only $ref bodies. The 75 inline
  # (non-$ref) bodies and the non-JSON media have their own literal pin,
  # so a regenerate that drifts both halves together still fails.
  "${PYTHON_BIN}" scripts/check_openapi_inline_body_integrity.py --self-test || rc=$?
  # The app shells must declare a favicon that resolves in source and in the
  # built tree; the admin console shipped without one and 404'd every load.
  "${PYTHON_BIN}" scripts/check_app_shell_assets.py --self-test || rc=$?
  # Every value domain (enum / const) the OpenAPI snapshot publishes must still
  # be the one the model declares. The offline OpenAPI guards all stop at which
  # schema a response names; a retyped enum survives export==snapshot because
  # both artifacts are exports. Self-test mode, like the guards above, so this
  # adds one line here instead of a row in the shared `tests[]` array.
  "${PYTHON_BIN}" scripts/check_openapi_published_enums.py --self-test || rc=$?
  # operationId is a client-visible published symbol: the key of the
  # generated `operations` interface. --self-test plants the co-revert
  # that every artifact-vs-artifact check is blind to.
  "${PYTHON_BIN}" scripts/check_openapi_operation_id_floor.py --self-test || rc=$?
  # Every published operation parameter (name, location, requiredness,
  # schema) is a client-visible property of the generated operations
  # interface. A coordinated rename in both artifacts, with re-pinned
  # provenance blob ids, kept every wired guard and SMOKE PASS green.
  "${PYTHON_BIN}" scripts/check_openapi_operation_parameter_floor.py --self-test || rc=$?
  # Every published operation declares a set of response codes, and all 12
  # declared 204 responses are content-less -- invisible to every body
  # digest and outside the 4xx/5xx error baseline. A coordinated
  # 204 -> 205 rename in both halves with re-pinned provenance blobs
  # kept every wired OpenAPI guard green. Pin the whole surface.
  "${PYTHON_BIN}" scripts/check_openapi_response_surface.py --self-test || rc=$?
  # Every published operation carries summary/description prose that the
  # generated TypeScript doc comments render verbatim. A coordinated
  # regenerate that rewrites one on both halves, with re-pinned provenance
  # blobs, kept every wired guard green. Pin the whole annotation surface.
  "${PYTHON_BIN}" scripts/check_openapi_operation_annotations.py --self-test || rc=$?
  # The published field-level constraints have no generated half and no
  # body/$ref footprint. A byte-preserving maxItems retype with re-pinned
  # provenance blob ids kept every wired OpenAPI guard green. Pin them.
  "${PYTHON_BIN}" scripts/check_openapi_field_constraints.py --self-test || rc=$?
  # The published schema `required` arrays have no independent fixed point:
  # the field-constraint digest walks constraint keywords, the body digests
  # read bodies, and the snapshot contract compares field sets only. Pin
  # all 1076 declarations and check the generated optional markers.
  "${PYTHON_BIN}" scripts/check_openapi_required_fields.py --self-test || rc=$?
  # The visible-text budget may fall but never rise; new hardcoded strings fail.
  "${PYTHON_BIN}" scripts/check_visible_i18n.py --self-test || rc=$?
  # nginx security-header fragments and the locations that must re-include
  # them. Not part of the frontend gate: the configs cover the API and data
  # planes too, so a backend-only change can break them.
  "${PYTHON_BIN}" scripts/check_nginx_security_headers.py || rc=$?
  # Read the committed service bytes: the pytest suite exercises behaviour,
  # this guard catches the ordering being moved back at the source level.
  "${PYTHON_BIN}" scripts/check_interval_visibility_order.py || rc=$?
  # The published error-code vocabulary is frozen against a hand-written lock:
  # a coordinated source + artifact co-revert stays green under every
  # consistency check. The catalog guard re-derives the runtime catalog from
  # source. Both ran only in check-contract.sh (behind the frontend gate's
  # export), so a failing guard or a co-rename never reddened the contracts
  # layer that actually runs on a clean checkout. Consume them here too.
  "${PYTHON_BIN}" scripts/check_api_error_code_vocabulary.py || rc=$?
  # Its --self-test plants the decisive ablations, including a dropped
  # `catalog[HTTP_ERROR_CODE]` entry. Without this call a one-line weakening
  # of source_codes() back to a constant-only read keeps the whole layer green.
  "${PYTHON_BIN}" scripts/check_api_error_code_vocabulary.py --self-test || rc=$?
  "${PYTHON_BIN}" scripts/check_error_code_catalog.py || rc=$?
  # The plain call above reads committed bytes; --self-test is the only thing
  # that proves the guard's planted drifts still land and still get caught.
  # Wired here because check-contract.sh runs only the plain form, so a
  # _mutate_source no-op (a needle that matches nothing) or a gutted case set
  # could keep the whole contracts layer green while the guard went blind.
  "${PYTHON_BIN}" scripts/check_error_code_catalog.py --self-test || rc=$?
  # The third guard of that family was left behind in check-contract.sh. It is
  # the only one that executes the runtime catalog and reconciles the published
  # x-error-status block with error_status_map(); the two above read
  # declarations and a hand-written lock. Re-measured: a coordinated rename with
  # the lock re-pinned leaves both of those GREEN and this one RED, so without
  # this line the contracts layer has no net under the status binding.
  # Committed bytes only -- no API venv, no export, same as its siblings.
  "${PYTHON_BIN}" scripts/check_error_code_contract.py || rc=$?
  # Pin those two wires: dropping or neutralising either lets the layer stay
  # green while the guard's failure is swallowed. --self-test plants the
  # decisive co-rename and proves the wired guard still has a real signal.
  "${PYTHON_BIN}" scripts/check_error_code_gate_wiring.py --self-test || rc=$?
  # The dev docs state error-code suite counts in prose, but every gate reads
  # only source/artifact bytes: a merge that adds a test and forgets the
  # sentence ships a green layer with a stale number. Derive the counts from
  # the committed sources and pin the sentences; --self-test plants drifts.
  "${PYTHON_BIN}" scripts/check_error_code_doc_counts.py --self-test || rc=$?
  # `variant_summaries` has no constraint tying `gene_id` to `assembly_id`
  # (issue #86), so a v5 summary can point at a v4 gene. The gene page excludes
  # such a row; the release-wide `variant_type` aggregate never joined `genes`
  # and counted it. The API test for this needs PostgreSQL, so the contracts
  # layer had no net at all. Reads committed source; --self-test plants both
  # the dropped predicate and the FILTER-to-WHERE regression.
  # Both calls: --self-test proves the guard still has a signal, the plain run
  # is the one that reads the committed tree. Wiring only the self-test would
  # make this a dead guard -- it would pass while the real source regressed.
  "${PYTHON_BIN}" scripts/check_variant_summary_assembly_consistency.py --self-test || rc=$?
  "${PYTHON_BIN}" scripts/check_variant_summary_assembly_consistency.py || rc=$?
  # Most guards are wired here through --self-test alone. A pinned subset
  # (BOTH_CALLS in the teeth guard) is deliberately called twice: the
  # --self-test proves the guard still has a signal, the plain run is the
  # only call that reads the committed tree. If a self_test body is replaced
  # with `return 0`, the call is still present, still pinned and still green:
  # this guard runs each one as a real process and requires its pinned
  # evidence of mutation cases.
  "${PYTHON_BIN}" scripts/check_contracts_self_test_teeth.py --self-test || rc=$?
  # §4a (PR #206): the placeholder-origin regex is committed twice. Only the
  # production scanner has a behavioural suite reading it back; the static
  # layer's copy can lose an origin with every gate still green. Pin both
  # copies against a reviewed floor; the companion suite plants the drifts.
  "${PYTHON_BIN}" scripts/check_static_placeholder_scan.py || rc=$?
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
    if [[ -d apps/web/dist/external ]]; then
      dir="apps/web/dist/external"
    else
      echo "no external site artifact at apps/web/dist/external" >&2
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
      # The artifact may be built for a deployment sub-path (e.g. /soymutdb-next),
      # so its HTML references assets *with* that prefix while the files sit at
      # the artifact root. Retry once with the baked base segment removed; only
      # report when neither spelling resolves.
      local stripped="${relative#*/}"
      if [[ "${stripped}" == "${relative}" || ! -e "${dir}/${stripped}" ]]; then
        echo "missing referenced asset: ${asset}" >&2
        missing=1
      fi
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
  # The compiled kernel must be installed in the API venv AND produce real
  # scientific results, not merely import.  This is a hard gate: a sequence
  # tool without its engine would otherwise fail closed with 503 in production.
  apps/api/.venv/bin/python scripts/check_bio_core_wheel.py --runtime || return 1
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
  # Top-level scope has no rc; only FAILED decides the exit status.
  "${PYTHON_BIN}" scripts/check_contracts_registry_collection.py || FAILED+=("contracts registry")
  run_layer contracts smoke_contracts
fi

if should_run static; then
  if [[ -d apps/web/dist/external || -n "${STATIC_DIR}" ]]; then
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
