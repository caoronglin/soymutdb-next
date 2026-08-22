import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
NODE_VERSION = "24.19.0"
PROFILES = {"core", "jbrowse", "blast", "analyses", "mcp", "cloudflare-tunnel"}
UPGRADE = ROOT / "deploy/scripts/upgrade.sh"
BACKUP = ROOT / "deploy/scripts/backup.sh"
HEALTHCHECK = ROOT / "deploy/scripts/healthcheck.sh"
INSTALL = ROOT / "deploy/linux/install.sh"
CONDA_ENV = ROOT / "deploy/conda/env.example"
CONDA_README = ROOT / "deploy/conda/README.md"
CONDA_DEPLOY = ROOT / "deploy/scripts/conda-deploy.sh"
CONDA_SERVICES = ROOT / "deploy/scripts/conda-services.sh"
CONDA_NO_DOCKER = ROOT / "deploy/conda/no-docker-data-layer.md"
DEPLOYMENT_ARCHITECTURE = ROOT / "docs/design/deployment-architecture.md"
PLATFORM_CATALOG = {
    "react": "19.2.0",
    "react-dom": "19.2.0",
    "typescript": "5.9.3",
    "vite": "6.4.3",
    "antd": "6.6.1",
}


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def _example_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / "deploy/.env.example").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value
    return values


def _workflow_job(workflow: str, job_name: str) -> str:
    match = re.search(
        rf"^  {re.escape(job_name)}:\n.*?(?=^  [a-z0-9-]+:\n|\Z)",
        workflow,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing workflow job: {job_name}"
    return match.group(0)


def test_node_and_pnpm_toolchain_is_exact_in_workflows_that_build_assets() -> None:
    package = _json("package.json")

    assert (ROOT / ".nvmrc").read_text(encoding="utf-8").strip() == NODE_VERSION
    assert (ROOT / ".node-version").read_text(encoding="utf-8").strip() == NODE_VERSION
    assert package["packageManager"] == "pnpm@11.21.0"
    assert package["engines"] == {"node": ">=24.0.0 <25", "pnpm": "11.21.0"}

    for workflow_name in ("ci.yml", "e2e-smoke.yml"):
        workflow = (ROOT / ".github/workflows" / workflow_name).read_text(encoding="utf-8")
        assert "Setup Node 24" in workflow
        assert f"node-version: {NODE_VERSION}" in workflow
        assert "node-version: 22" not in workflow

    # Pages publishes the already-built, checksummed CI artifact; installing a
    # JS toolchain here would invite a second, non-identical build.
    pages = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    deploy_job = _workflow_job(pages, "deploy")
    assert "Download CI-verified Pages artifact" in deploy_job
    assert "Setup Node" not in deploy_job
    assert "node-version:" not in deploy_job
    assert "pnpm install" not in deploy_job
    assert "pnpm --filter" not in deploy_job


def test_frontend_platform_lines_remain_bounded() -> None:
    root_package = _json("package.json")
    workspace = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))

    assert root_package["devDependencies"]["typescript"].startswith("^5.9.")
    assert workspace["overrides"]["react"] == "19.2.0"
    assert workspace["overrides"]["react-dom"] == "19.2.0"
    for app in ("web", "admin", "jbrowse"):
        package = _json(f"apps/{app}/package.json")
        assert package["dependencies"]["react"].startswith("^19.2.")
        assert package["dependencies"]["react-dom"].startswith("^19.2.")
        assert package["devDependencies"]["typescript"].startswith("^5.9.")
        assert package["devDependencies"]["vite"].startswith("^6.")


def test_workspace_catalog_pins_platform_dependencies() -> None:
    workspace = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))

    assert workspace["catalog"] == PLATFORM_CATALOG


def test_dependency_build_scripts_are_fail_closed_except_for_esbuild() -> None:
    workspace = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))

    assert workspace["allowBuilds"] == {"esbuild": True}


def test_antd_consumers_resolve_from_workspace_catalog() -> None:
    for app in ("web", "admin"):
        package = _json(f"apps/{app}/package.json")
        assert package["dependencies"]["antd"] == "catalog:"


def test_pro_components_dependency_is_removed_after_source_migration() -> None:
    for app in ("web", "admin"):
        package = _json(f"apps/{app}/package.json")
        assert "@ant-design/pro-components" not in package["dependencies"]

    admin_vite = (ROOT / "apps/admin/vite.config.ts").read_text(encoding="utf-8")
    assert "@ant-design/pro-components" not in admin_vite


def test_legacy_shared_ui_package_is_not_copied_into_ci_images() -> None:
    for dockerfile in (
        "apps/jbrowse/Dockerfile",
        "infra/docker/Dockerfile.web",
        "infra/docker/Dockerfile.admin",
    ):
        source = (ROOT / dockerfile).read_text(encoding="utf-8")
        assert "packages/ui" not in source, dockerfile


def test_production_compose_has_explicit_capability_profiles() -> None:
    services = _compose()["services"]
    observed_profiles = {
        profile
        for service in services.values()
        for profile in service.get("profiles", [])
    }

    assert observed_profiles == PROFILES
    assert all(service.get("profiles") for service in services.values())
    assert services["api"]["profiles"] == ["core"]
    assert services["jbrowse"]["profiles"] == ["jbrowse"]
    assert services["worker-blast"]["profiles"] == ["blast"]
    assert services["worker-analyses"]["profiles"] == ["analyses"]
    assert services["mcp-server"]["profiles"] == ["mcp"]
    assert services["cloudflared"]["profiles"] == ["cloudflare-tunnel"]


def test_release_services_use_digest_refs_without_compose_build_fallbacks() -> None:
    services = _compose()["services"]
    service_refs = {
        "migrate": "API_IMAGE_REF",
        "api": "API_IMAGE_REF",
        "migrate-clickhouse": "WORKER_IMAGE_REF",
        "worker-default": "WORKER_IMAGE_REF",
        "worker-blast": "WORKER_IMAGE_REF",
        "worker-ingest": "WORKER_IMAGE_REF",
        "worker-analyses": "WORKER_IMAGE_REF",
        "beat": "WORKER_IMAGE_REF",
        "mcp-server": "MCP_IMAGE_REF",
        "jbrowse": "JBROWSE_IMAGE_REF",
    }

    for service_name, variable_name in service_refs.items():
        service = services[service_name]
        assert service["image"].startswith(f"${{{variable_name}:?")
        assert "image@sha256" in service["image"]
        assert "build" not in service

    env = _example_env()
    digest_ref = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}$")
    for variable_name in set(service_refs.values()):
        assert digest_ref.fullmatch(env[variable_name]), (variable_name, env[variable_name])
    assert set(env["COMPOSE_PROFILES"].split(",")) == {"core", "blast", "analyses", "mcp"}


def test_upgrade_path_rejects_tags_and_records_digest_refs() -> None:
    script = UPGRADE.read_text(encoding="utf-8")

    for variable_name in (
        "API_IMAGE_REF",
        "WORKER_IMAGE_REF",
        "MCP_IMAGE_REF",
        "JBROWSE_IMAGE_REF",
    ):
        assert variable_name in script
    assert "@sha256:[0-9a-f]{64}" in script
    assert "docker manifest inspect" in script
    assert '"api_image_ref"' in script
    assert '"worker_image_ref"' in script
    assert '"mcp_image_ref"' in script
    assert "API_IMAGE_TAG" not in script
    assert "WORKER_IMAGE_TAG" not in script
    assert "MCP_IMAGE_TAG" not in script


def test_upgrade_quiesces_application_before_authoritative_backup() -> None:
    script = UPGRADE.read_text(encoding="utf-8")
    backup_command = 'BACKUP_WRITES_QUIESCED=1 bash "${SCRIPT_DIR}/backup.sh"'
    stop_command = '"${COMPOSE[@]}" stop "${APP_SERVICES[@]}"'

    assert backup_command in script
    assert stop_command in script
    assert script.index("APP_SERVICES=") < script.index(backup_command)
    assert script.index(stop_command) < script.index(backup_command)

    backup_section = script[
        script.index(backup_command) : script.index("# Step 6", script.index(backup_command))
    ]
    assert "restart_pre_upgrade_services" in backup_section


def test_backup_uses_minio_root_credentials_when_source_credentials_are_unset() -> None:
    script = BACKUP.read_text(encoding="utf-8")

    assert 'S3_ACCESS_KEY="${S3_ACCESS_KEY:-${MINIO_ROOT_USER:-minioadmin}}"' in script
    assert 'S3_SECRET_KEY="${S3_SECRET_KEY:-${MINIO_ROOT_PASSWORD:-minioadmin}}"' in script


def test_compose_healthcheck_defaults_to_the_published_nginx_port() -> None:
    script = HEALTHCHECK.read_text(encoding="utf-8")

    assert 'API_PORT="${API_PORT:-8080}"' in script
    for path in ("/api/v1/health/live", "/api/v1/health/ready", "/metrics"):
        assert path in script


def test_compose_exposes_the_optional_signed_plugin_manifest_boundary() -> None:
    compose = _compose()
    env_template = (ROOT / "deploy/.env.example").read_text(encoding="utf-8")
    app_env = compose["x-app-env"]
    api_env = compose["services"]["api"]["environment"]

    assert "SOYMUTDB_PLUGIN_MANIFEST_SIGNING_KEY" not in app_env
    assert "SOYMUTDB_PLUGIN_MANIFESTS_JSON" not in app_env
    assert (
        api_env["SOYMUTDB_PLUGIN_MANIFEST_SIGNING_KEY"]
        == "${SOYMUTDB_PLUGIN_MANIFEST_SIGNING_KEY:-}"
    )
    assert api_env["SOYMUTDB_PLUGIN_MANIFESTS_JSON"] == "${SOYMUTDB_PLUGIN_MANIFESTS_JSON:-[]}"
    assert "SOYMUTDB_PLUGIN_MANIFEST_SIGNING_KEY" in env_template
    assert "SOYMUTDB_PLUGIN_MANIFESTS_JSON" in env_template


def test_ols4_manifest_renderer_uses_the_same_api_image_signer() -> None:
    renderer = ROOT / "deploy/scripts/render-ols4-plugin-manifest.sh"

    assert renderer.is_file()
    script = renderer.read_text(encoding="utf-8")
    assert '"${COMPOSE[@]}" run --rm --no-deps' in script
    assert "sign_official_ols4_manifest" in script
    assert "OLS4_PLUGIN_ENABLED" in script
    assert "OLS4_PLUGIN_CONFIGURED" in script
    assert "OLS4_PLUGIN_HEALTHY" in script


def test_linux_install_keeps_deployment_scripts_at_their_expected_layout() -> None:
    script = INSTALL.read_text(encoding="utf-8")

    assert 'mkdir -p "${INSTALL_DIR}/deploy"' in script
    assert 'cp -r "${PROJECT_ROOT}/deploy/scripts" "${INSTALL_DIR}/deploy/"' in script
    assert '"${INSTALL_DIR}/scripts"' not in script


def test_conda_hybrid_mode_exposes_real_data_layer_endpoints_and_all_queues() -> None:
    compose = _compose()
    env = CONDA_ENV.read_text(encoding="utf-8")
    readme = CONDA_README.read_text(encoding="utf-8")
    deploy = CONDA_DEPLOY.read_text(encoding="utf-8")
    services = CONDA_SERVICES.read_text(encoding="utf-8")
    no_docker = CONDA_NO_DOCKER.read_text(encoding="utf-8")
    architecture = DEPLOYMENT_ARCHITECTURE.read_text(encoding="utf-8")

    assert compose["services"]["redis-celery"]["ports"] == ["127.0.0.1:6380:6379"]
    assert "SOYMUTDB_CELERY_BROKER_URL=redis://:change-me-redis@127.0.0.1:6380/0" in env
    assert "SOYMUTDB_CELERY_RESULT_BACKEND=redis://:change-me-redis@127.0.0.1:6380/1" in env
    assert "SOYMUTDB_S3_ENDPOINT=http://127.0.0.1:9001" in env
    assert "localhost:6380/0" in readme
    assert "http://localhost:9001" in readme
    assert "unit_worker_analyses" in services
    assert "UNITS=(api worker-default worker-blast worker-ingest worker-analyses beat)" in services
    assert "--queues=analyses" in services
    assert "worker-analyses" in deploy
    assert "worker-analyses" in no_docker
    assert "localhost:6380" in architecture


def test_ci_validates_profiles_and_publishes_verifiable_digest_contract() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Validate production Compose profiles (Docker-only CI gate)" in workflow
    for profile in sorted(PROFILES):
        assert f'"core,{profile}"' in workflow or profile == "core"

    assert "docker manifest inspect --verbose" in workflow
    assert "release-contract/oci-image-refs.txt" in workflow
    assert 'digest_ref="${image%:*}@${digest}"' in workflow
    assert 'docker manifest inspect "$digest_ref"' in workflow
    assert "sha256sum oci-image-refs.txt" in workflow
    assert "GITHUB_STEP_SUMMARY" in workflow
    assert "release-contract-sha256" in workflow


def test_ci_builds_release_images_on_independent_native_platforms() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    docker_job = _workflow_job(workflow, "docker-build")

    assert "runs-on: ${{ matrix.runner }}" in docker_job
    assert "arch: amd64" in docker_job
    assert "runner: ubuntu-24.04" in docker_job
    assert "platform: linux/amd64" in docker_job
    assert "arch: arm64" in docker_job
    assert "runner: ubuntu-24.04-arm" in docker_job
    assert "platform: linux/arm64" in docker_job
    assert "fail-fast: false" in docker_job
    assert "soymutdb-api:ci-${{ matrix.arch }}" in docker_job

    build = docker_job.index("Build API image (hard gate)")
    smoke = docker_job.index("Smoke test API runtime image (hard gate)")
    scan = docker_job.index("Trivy scan API image (hard gate)")
    sbom = docker_job.index("Generate API SPDX SBOM")
    export = docker_job.index("Export validated runtime images")
    assert build < smoke < scan < sbom < export


def test_ci_asserts_built_image_architecture_before_security_scan() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    docker_job = _workflow_job(workflow, "docker-build")

    assertion = "Assert actual native image architecture (hard gate)"
    assert assertion in docker_job
    gate_start = docker_job.index(assertion)
    scan_start = docker_job.index("Trivy scan API image (hard gate)")
    gate = docker_job[gate_start:scan_start]

    assert "expected_architecture=\"${{ matrix.arch }}\"" in gate
    assert "docker image inspect --format '{{.Architecture}}'" in gate
    for image_name in ("api", "worker", "mcp", "jbrowse"):
        assert f'"soymutdb-{image_name}:ci-${{{{ matrix.arch }}}}"' in gate
    assert docker_job.index("Smoke test JBrowse runtime image (hard gate)") < gate_start < scan_start


def test_ci_merges_only_validated_platform_packages() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    publish_job = _workflow_job(workflow, "publish-images")

    assert "needs: [docker-build, kubernetes-kind]" in publish_job
    assert "pattern: validated-runtime-images-*" in publish_job
    assert '"validated-runtime-images-amd64"' in publish_job
    assert '"validated-runtime-images-arm64"' in publish_job
    assert "docker manifest create" in publish_job
    assert "docker manifest push" in publish_job
    assert "linux/amd64" in publish_job
    assert "linux/arm64" in publish_job
    assert "Verify merged manifest platforms" in publish_job
    assert "docker build" not in publish_job


def test_ci_checksums_all_platform_package_metadata_before_upload() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    docker_job = _workflow_job(workflow, "docker-build")
    export_step = docker_job[
        docker_job.index("Export validated runtime images") :
        docker_job.index("Upload validated runtime images")
    ]
    checksum_command = export_step[export_step.index("sha256sum") :]

    assert "soymutdb-runtime-images-${{ matrix.arch }}.tar" in checksum_command
    assert "image-ids-${{ matrix.arch }}.txt" in checksum_command
    assert "platform.txt" in checksum_command
    assert "sbom-*-${{ matrix.arch }}.spdx.json" in checksum_command
    assert "sha256sum -c SHA256SUMS" in _workflow_job(workflow, "publish-images")


def test_release_signing_is_keyless_and_job_scoped() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    docker_job = _workflow_job(workflow, "docker-build")
    publish_job = _workflow_job(workflow, "publish-images")

    assert "id-token: write" not in docker_job
    assert "id-token: write" in publish_job
    assert "packages: write" in publish_job
    installer = re.search(r"uses: sigstore/cosign-installer@([^\s#]+)", publish_job)
    assert installer is not None
    assert re.fullmatch(r"[0-9a-f]{40}", installer.group(1))
    assert "cosign sign --yes" in publish_job
    assert "cosign attest --yes --type slsaprovenance" in publish_job
    assert "cosign attest --yes --type spdxjson" in publish_job
    assert "cosign verify" in publish_job
    assert "cosign verify-attestation" in publish_job
    assert "token.actions.githubusercontent.com" in publish_job


def test_release_contract_carries_sbom_provenance_and_source_identity() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    docker_job = _workflow_job(workflow, "docker-build")
    publish_job = _workflow_job(workflow, "publish-images")

    assert docker_job.count("format: spdx-json") == 4
    for image_name in ("api", "worker", "mcp", "jbrowse"):
        assert f"sbom-{image_name}-${{{{ matrix.arch }}}}.spdx.json" in docker_job
        assert f"provenance-{image_name}.json" in publish_job
    assert "release-manifest.json" in publish_job
    assert '"schema_version": 1' in publish_job
    assert "GITHUB_SHA" in publish_job
    assert "GITHUB_REPOSITORY" in publish_job
    assert "provenance_sha256" in publish_job
    assert "release-manifest.sigstore.json" in publish_job
    assert "sha256sum release-manifest.json" in publish_job
    assert "Upload signed OCI release contract" in publish_job


def test_blue_green_deploy_is_fail_closed_and_atomic() -> None:
    common = (ROOT / "deploy/scripts/blue-green-common.sh").read_text(encoding="utf-8")
    deploy = (ROOT / "deploy/scripts/blue-green-deploy.sh").read_text(encoding="utf-8")

    assert "set -euo pipefail" in common
    assert "flock" in common
    assert "cosign verify-blob" in common
    assert "cosign verify-attestation" in common
    assert "provenance_sha256" in common
    assert "@sha256:" in common
    assert "BLUE_GREEN_ADAPTER" in common
    assert "eval " not in common
    for command in ("stage", "verify", "switch", "current"):
        assert f'run_adapter "{command}"' in deploy
    preflight = deploy.index('observed_active_slot="$(run_adapter "current")"')
    assert preflight < deploy.index('run_adapter "stage"')
    assert '[[ "${observed_active_slot}" == "${active_slot}" ]]' in deploy
    assert "restore_active_slot" in deploy
    assert "trap restore_active_slot EXIT" in deploy
    assert "write_slot_state" in deploy


def test_blue_green_rollback_uses_verified_previous_release() -> None:
    rollback = (ROOT / "deploy/scripts/blue-green-rollback.sh").read_text(encoding="utf-8")

    assert "validate_release_contract" in rollback
    assert "previous_release_manifest_sha256" in rollback
    assert 'run_adapter "verify"' in rollback
    assert 'run_adapter "switch"' in rollback
    assert 'run_adapter "current"' in rollback
    preflight = rollback.index('observed_active_slot="$(run_adapter "current")"')
    assert preflight < rollback.index('run_adapter "verify"')
    assert '[[ "${observed_active_slot}" == "${active_slot}" ]]' in rollback
    assert "restore_active_slot" in rollback
    assert "write_slot_state" in rollback


def test_platform_delivery_adr_records_decisions_and_rollback() -> None:
    adr = (ROOT / "docs/adr/0001-platform-delivery-contract.md").read_text(encoding="utf-8")

    assert "Status: Accepted" in adr
    assert "Node.js 24.19.0" in adr
    assert "pnpm 11.21.0" in adr
    assert "Ant Design 6" in adr
    assert "image@sha256" in adr
    assert "core,jbrowse,blast,analyses,mcp,cloudflare-tunnel" in adr
    assert "Docker acceptance runs in CI" in adr
    assert "Rollback" in adr
