import re
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]


def _workflow_job(workflow: str, job_name: str) -> str:
    match = re.search(
        rf"^  {re.escape(job_name)}:\n.*?(?=^  [a-z0-9-]+:\n|\Z)",
        workflow,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing workflow job: {job_name}"
    return match.group(0)


def _top_level_block(workflow: str, block_name: str) -> str:
    match = re.search(
        rf"^{re.escape(block_name)}:\n.*?(?=^[a-z][a-z0-9_-]*:\n|\Z)",
        workflow,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing top-level workflow block: {block_name}"
    return match.group(0)


def test_ci_pushes_images_to_repository_owner_namespace() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "GITHUB_REPOSITORY_OWNER,," in workflow
    assert "ghcr.io/soymutdb/" not in workflow


def test_ci_grants_package_write_for_ghcr_pushes() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "packages: write" in workflow


def test_ci_pushes_mcp_from_the_image_name_it_builds() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "soymutdb-mcp:ci-${{ matrix.arch }}" in workflow
    assert "local_names=(api worker mcp jbrowse)" in workflow
    assert "remote_names=(api worker mcp-server jbrowse)" in workflow
    assert 'docker tag "soymutdb-${local_names[$index]}:ci-${arch}" "$image"' in workflow


def test_api_and_worker_formally_depend_on_locked_jobs_package() -> None:
    for project_name in ("api", "worker"):
        project_dir = ROOT / "apps" / project_name
        project = tomllib.loads(
            (project_dir / "pyproject.toml").read_text(encoding="utf-8")
        )
        dependencies = project["project"]["dependencies"]
        jobs_source = project["tool"]["uv"]["sources"]["soymutdb-jobs"]

        assert "soymutdb-jobs==0.1.0" in dependencies
        assert jobs_source == {"path": "../../packages/jobs-py"}

        lock = (project_dir / "uv.lock").read_text(encoding="utf-8")
        assert 'name = "soymutdb-jobs"' in lock
        assert 'source = { directory = "../../packages/jobs-py" }' in lock


def test_runtime_dockerfiles_install_jobs_package_from_the_build_context() -> None:
    for dockerfile_name in ("Dockerfile.api", "Dockerfile.worker"):
        dockerfile = (ROOT / "infra/docker" / dockerfile_name).read_text(
            encoding="utf-8"
        )
        copy_position = dockerfile.index(
            "COPY packages/jobs-py ./packages/jobs-py"
        )
        sync_position = dockerfile.index("uv sync --frozen")

        assert copy_position < sync_position


def test_ci_builds_then_smokes_then_scans_before_exporting_exact_images() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    docker_job = _workflow_job(workflow, "docker-build")

    build_steps = [
        "Build API image (hard gate)",
        "Build Worker image (hard gate)",
        "Build MCP image (hard gate)",
        "Build JBrowse image (hard gate)",
    ]
    smoke_steps = [
        "Smoke test API runtime image (hard gate)",
        "Smoke test Worker task registry (hard gate)",
        "Smoke test MCP runtime image (hard gate)",
        "Smoke test JBrowse runtime image (hard gate)",
    ]
    scan_steps = [
        "Trivy scan API image (hard gate)",
        "Trivy scan Worker image (hard gate)",
        "Trivy scan MCP image (hard gate)",
        "Trivy scan JBrowse image (hard gate)",
    ]

    build_positions = [docker_job.index(step) for step in build_steps]
    smoke_positions = [docker_job.index(step) for step in smoke_steps]
    scan_positions = [docker_job.index(step) for step in scan_steps]
    export_position = docker_job.index("Export validated runtime images")
    upload_position = docker_job.index("Upload validated runtime images")

    assert max(build_positions) < min(smoke_positions)
    assert max(smoke_positions) < min(scan_positions)
    assert max(scan_positions) < export_position < upload_position
    for image_name in ("api", "worker", "mcp", "jbrowse"):
        assert f"image-ref: soymutdb-{image_name}:ci" in docker_job
        assert f"soymutdb-{image_name}:ci" in docker_job[export_position:upload_position]

    assert "docker save" in docker_job[export_position:upload_position]
    assert "docker image inspect" in docker_job[export_position:upload_position]
    assert "sha256sum" in docker_job[export_position:upload_position]
    assert "Login to GHCR" not in docker_job
    assert "docker push" not in docker_job


def test_ci_runtime_smoke_imports_real_api_and_full_worker_registry() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    docker_job = _workflow_job(workflow, "docker-build")

    assert "from app.main import app" in docker_job
    assert "import soymutdb_jobs" in docker_job
    assert "scripts/check-worker-task-registry.py" in docker_job
    assert "Smoke test API image (non-blocking)" not in docker_job


def test_ci_installs_local_jobs_package_before_api_and_worker_projects() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    jobs_install = "pip install --quiet -e packages/jobs-py"

    frontend_job = _workflow_job(workflow, "frontend")
    assert frontend_job.index(jobs_install) < frontend_job.index(
        "pip install --quiet -e apps/api"
    )

    api_job = _workflow_job(workflow, "api-tests")
    assert api_job.index(jobs_install) < api_job.index(
        'pip install -e "apps/api[dev]"'
    )
    assert api_job.index(jobs_install) < api_job.index(
        "pip install --quiet -e apps/worker"
    )


def test_ci_offline_frontend_build_uses_demo_sample_data() -> None:
    """The generic CI build cannot require an unpublished API endpoint."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    frontend_job = _workflow_job(workflow, "frontend")
    build_step = frontend_job[
        frontend_job.index("Build all apps (hard gate)") : frontend_job.index(
            "Bundle size budget check (G2 hard gate)"
        )
    ]

    assert "VITE_DEPLOYMENT_MODE: demo" in build_step


def test_ci_runs_the_full_worker_pytest_suite_after_installing_worker_dependencies() -> None:
    """Worker Testcontainers coverage is a hard CI gate, not only an import check."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    api_job = _workflow_job(workflow, "api-tests")
    install = "Install worker deps + verify analysis imports (hard gate)"
    worker_pytest = "apps/api/.venv/bin/python -m pytest apps/worker/tests -q"

    assert install in api_job
    assert worker_pytest in api_job
    assert api_job.index(install) < api_job.index(worker_pytest)
    assert "pytest apps/worker/tests -q -k" not in api_job


def test_ci_requires_the_real_postgresql_worker_integration_environment() -> None:
    """A missing Docker/Testcontainers setup must fail CI instead of skip-green."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    api_job = _workflow_job(workflow, "api-tests")
    worker_step = api_job[api_job.index("Worker pytest including PostgreSQL integration (hard gate)"):]

    assert 'SOYMUTDB_RUN_POSTGRES_INTEGRATION: "1"' in worker_step


def test_ci_publish_is_the_only_package_writer_and_loads_verified_artifact() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    global_permissions = _top_level_block(workflow, "permissions")
    docker_job = _workflow_job(workflow, "docker-build")
    publish_job = _workflow_job(workflow, "publish-images")

    assert "packages: write" not in global_permissions
    assert "actions: write" not in global_permissions
    assert workflow.count("packages: write") == 1
    assert "packages: write" not in docker_job
    assert "packages: write" in publish_job
    assert "contents: read" in docker_job
    for prerequisite in (
        "frontend",
        "api-tests",
        "clickhouse-migration",
        "mcp-e2e",
    ):
        assert f"- {prerequisite}" in docker_job

    # Image publication waits for both the native multi-platform Docker gates
    # and the checksum-verified amd64 Kind runtime smoke.
    assert "needs: [docker-build, kubernetes-kind]" in publish_job
    assert "github.event_name == 'push'" in publish_job
    assert "github.ref == 'refs/heads/main'" in publish_job
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" in publish_job
    assert "validated-runtime-images" in publish_job
    assert "docker build" not in publish_job
    assert "trivy-action" not in publish_job

    checksum_position = publish_job.index("sha256sum -c")
    load_position = publish_job.index("docker load")
    id_check_position = publish_job.index("actual_id=")
    login_position = publish_job.index("Login to GHCR")
    push_position = publish_job.index("Tag and push validated platform images")
    assert checksum_position < load_position < id_check_position < login_position < push_position
    assert workflow.count("docker push") == 1
    merge_position = publish_job.index("Merge manifests, attest evidence, and write release manifest")
    upload_position = publish_job.index("Upload signed OCI release contract")
    assert push_position < merge_position < upload_position


def test_ci_trivy_blocks_unfixed_high_and_critical_findings() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    docker_job = _workflow_job(workflow, "docker-build")

    assert docker_job.count("ignore-unfixed: false") == 4
    assert "ignore-unfixed: true" not in docker_job
    assert docker_job.count("severity: CRITICAL,HIGH") == 4
    assert docker_job.count("exit-code: 1") == 4


def test_e2e_uses_minimum_permissions_pinned_actions_and_lockfile_install() -> None:
    workflow = (ROOT / ".github/workflows/e2e-smoke.yml").read_text(encoding="utf-8")
    permissions = _top_level_block(workflow, "permissions")

    assert "contents: read" in permissions
    assert "actions: write" not in permissions
    assert "npm ci" in workflow
    assert "npm install\n" not in workflow
    assert "cache-dependency-path: e2e/package-lock.json" in workflow

    official_actions = re.findall(r"uses: (actions/[^@\s]+)@([^\s#]+)", workflow)
    assert official_actions
    for action, revision in official_actions:
        assert re.fullmatch(r"[0-9a-f]{40}", revision), (action, revision)


def test_clickhouse_migration_supports_repo_and_image_layouts() -> None:
    script = (ROOT / "deploy/scripts/migrate-clickhouse.sh").read_text(
        encoding="utf-8"
    )

    assert "CLICKHOUSE_MIGRATION_ROOT" in script
    assert 'if [[ ! -f "${ROOT}/migrate_clickhouse_lib.py" ]]' in script
    assert 'ROOT="${SCRIPT_DIR}"' in script
    assert "${REPO_ROOT}/infra/clickhouse/upgrade_variant_facts_schema.sql" in script
    assert "CH_MIGRATION_SQL" in script


def test_clickhouse_fixture_sends_single_queries_and_keeps_error_body() -> None:
    script = (ROOT / "deploy/scripts/migrate-ch-fixture.sh").read_text(
        encoding="utf-8"
    )

    assert "multiquery=1" not in script
    assert "--data-binary @\"${query_file}\"" in script
    assert "--output \"${response_file}\"" in script
    assert "response body:" in script
    assert 'awk -v prefix="${statement_dir}/statement-"' in script
    assert 'run_query "${statement}" "${DATABASE}"' in script


def test_clickhouse_density_backfills_project_their_group_key() -> None:
    """Density INSERTs must define ``bin_start`` before grouping by it.

    ClickHouse accepts the alias in the materialized-view SELECTs, but the
    legacy-schema backfill is a separate query.  Referencing the alias without
    projecting it makes the migration fail before any release can be built.
    """
    schema = (ROOT / "infra/clickhouse/upgrade_variant_facts_schema.sql").read_text(
        encoding="utf-8"
    )

    for table, bucket in (
        ("density_10kb", "10000"),
        ("density_100kb", "100000"),
        ("density_1mb", "1000000"),
    ):
        statement = re.search(
            rf"INSERT INTO {table} SELECT .*?;",
            schema,
            flags=re.DOTALL,
        )
        assert statement is not None
        assert f"intDiv(position, {bucket}) * {bucket} AS bin_start" in statement.group(0)
        assert "GROUP BY release_key, chromosome, bin_start" in statement.group(0)


def test_pages_deploys_an_explicit_public_demo() -> None:
    workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "VITE_DEPLOYMENT_MODE: demo" in ci
    assert "VITE_BASE_URL: /${{ github.event.repository.name }}/" in ci
    assert "github.repository_owner" in ci
    assert "github.event.repository.name }}/api/v1" in ci
    assert "github.event.repository.name }}/soymutdb-jbrowse/" in ci
    assert "secrets.API_BASE_URL" not in workflow
    assert "secrets.JBROWSE_URL" not in workflow
    assert "secrets.CONTENT_SNAPSHOT_URL" not in workflow
    assert "@soymutdb/admin build:web" not in workflow


def test_jbrowse_honors_its_pages_base_path() -> None:
    config = (ROOT / "apps/jbrowse/vite.config.ts").read_text(encoding="utf-8")

    assert "loadEnv" in config
    assert "base:" in config
    assert "VITE_BASE_URL" in config


def test_web_vite_entry_is_not_prefixed_by_deployment_base() -> None:
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")

    assert 'src="/src/main.tsx"' in index
    assert '%BASE_URL%src/main.tsx' not in index


def test_pages_accepts_publication_dispatch_inputs() -> None:
    workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")

    assert "publication_id:" in workflow
    assert "artifact_url:" in workflow
    assert "manifest_digest:" in workflow
    assert "inputs.publication_id" in workflow
    assert "inputs.artifact_url" in workflow
    assert "inputs.manifest_digest" in workflow


def test_pages_verifies_digest_before_ref_update() -> None:
    workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")

    assert "sha256sum -c -" in workflow
    assert '"$MANIFEST_DIGEST' in workflow
    # Digest verification must run BEFORE the gh-pages ref update.
    assert workflow.index("Verify immutable artifact digest") < workflow.index(
        "Deploy all apps to pages"
    )


def test_pages_publishes_the_exact_ci_static_tree_without_rebuilding() -> None:
    """The Pages workflow must deploy CI's bytes, not rebuild source later."""
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")

    assert "Build GitHub Pages demo artifact (deploy input)" in ci
    assert "pages-demo-dist" in ci
    assert "test -f pages-dist/SHA256SUMS" in ci
    assert "Upload GitHub Pages demo artifact" in ci

    assert "actions: read" in workflow
    assert "Download CI-verified Pages artifact" in workflow
    assert 'gh run download "$CI_RUN_ID"' in workflow
    assert "pages-demo-dist" in workflow
    assert "Verify exact Pages artifact tree" in workflow
    assert "sha256sum -c SHA256SUMS" in workflow
    assert "Verify deployed Pages tree is byte-identical" in workflow

    deploy_job = _workflow_job(workflow, "deploy")
    assert "pnpm install" not in deploy_job
    assert "pnpm --filter @soymutdb/web build" not in deploy_job
    assert "pnpm --filter @soymutdb/jbrowse build" not in deploy_job
