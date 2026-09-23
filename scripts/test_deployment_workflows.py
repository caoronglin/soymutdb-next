import json
import re
from pathlib import Path

import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _cnb() -> dict:
    return yaml.safe_load((ROOT / ".cnb.yml").read_text(encoding="utf-8"))


def _cnb_pipeline(name: str, branch: str = "main", event: str = "push") -> str:
    """Serialize one CNB pipeline's definition for assertion purposes.

    The same pipeline name can appear under several events (the PR and main-push
    `verify` jobs differ), so both the branch and event are part of the lookup.
    A rename or a removed pipeline fails loudly here instead of silently
    asserting against the wrong definition.
    """
    document = _cnb()
    pipelines = document.get(branch, {}).get(event)
    if not isinstance(pipelines, list):
        raise AssertionError(f"missing CNB branch/event: {branch}/{event}")
    for pipeline in pipelines:
        if isinstance(pipeline, dict) and pipeline.get("name") == name:
            return json.dumps(pipeline, ensure_ascii=False)
    raise AssertionError(f"missing CNB pipeline: {name} in {branch}/{event}")


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


def test_ci_pushes_images_to_the_delivery_namespace() -> None:
    golden = (ROOT / "scripts/release-contract.golden.sh").read_text(encoding="utf-8")

    # The registry namespace is a per-pipeline variable, never hard-coded, so
    # the GitHub mirror, CNB, and any fork publish to their own namespace.
    assert "RELEASE_REGISTRY_OWNER" in golden
    assert "ghcr.io/soymutdb/" not in golden


def test_publishing_pipeline_owns_registry_credentials() -> None:
    golden = (ROOT / "scripts/release-contract.golden.sh").read_text(encoding="utf-8")
    cnb_pipeline = (ROOT / ".cnb/pipelines/release.yml").read_text(encoding="utf-8")

    # Registry credentials come from the pipeline environment; the contract
    # script logs in with the build-scoped token and never prints it.
    assert "CNB_DOCKER_REGISTRY" in golden
    assert "CNB_TOKEN_USER_NAME" in golden
    assert "docker login" in golden
    assert "--password-stdin" in golden
    assert "release-contract.golden.sh" in cnb_pipeline


def test_publish_keeps_local_to_registry_image_name_mapping() -> None:
    verification = (ROOT / "scripts/build-release-image.sh").read_text(encoding="utf-8")
    golden = (ROOT / "scripts/release-contract.golden.sh").read_text(encoding="utf-8")

    image_list = (ROOT / "scripts/list-images.sh").read_text(encoding="utf-8")

    # The local names are the single source of the image set: the publisher, the
    # verifier, the COPY guard and the contract tests all resolve it from
    # scripts/list-images.sh, so the set cannot be edited in one place and
    # silently skipped in another.
    assert 'source "${REPO_ROOT}/scripts/list-images.sh"' in golden
    assert "while IFS= read -r image_name; do" in golden
    assert "soymutdb_image_names" in golden
    # The one local/remote divergence is declared next to the list, not inline in
    # the publisher.
    assert "mcp) printf 'mcp-server" in image_list
    assert 'RUNTIME_REMOTE_NAMES+=("$(soymutdb_remote_image_name "${image_name}")")' in golden
    assert 'remote_names=("${RUNTIME_REMOTE_NAMES[@]}")' in golden
    assert 'docker tag "soymutdb-${local_names[$index]}:ci-${arch}" "${image}"' in golden


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
    docker_job = (ROOT / "scripts/build-release-image.sh").read_text(encoding="utf-8")
    image_list = (ROOT / "scripts/list-images.sh").read_text(encoding="utf-8")

    # The image set is enumerated once, in scripts/list-images.sh, and the verify
    # pipeline iterates it. Assert the enumeration itself, then the ordering of
    # the phases that consume it — a build command per image is no longer the
    # right thing to look for, because there is exactly one `docker build`
    # invocation in the script.
    assert 'SOYMUTDB_IMAGES=(' in image_list
    for entry in (
        '"api|.|infra/docker/Dockerfile.api"',
        '"worker|.|infra/docker/Dockerfile.worker"',
        '"migrate|.|infra/docker/Dockerfile.migrate"',
        '"migrate-clickhouse|.|infra/docker/Dockerfile.migrate-clickhouse"',
        '"mcp|apps/mcp-server|apps/mcp-server/Dockerfile"',
        '"jbrowse|.|apps/jbrowse/Dockerfile"',
        '"web|.|infra/docker/Dockerfile.web"',
        '"admin|.|infra/docker/Dockerfile.admin"',
    ):
        assert entry in image_list, entry

    assert 'source "${REPO_ROOT}/scripts/list-images.sh"' in docker_job
    assert "soymutdb_image_entry" in docker_job, (
        "the verify pipeline must iterate the shared image list rather than "
        "repeat the build commands"
    )
    assert 'docker build -f "${dockerfile}" -t "soymutdb-${name}:ci-${ARCH}"' in docker_job

    smoke_steps = [
        "Smoke test API runtime image (hard gate)",
        "Smoke test Worker task registry (hard gate)",
        "Smoke test MCP runtime image (hard gate)",
        "Smoke test JBrowse runtime image (hard gate)",
        "Smoke test web runtime image (hard gate)",
        "Smoke test admin runtime image (hard gate)",
        "Smoke test migrate runtime image (hard gate)",
        "Smoke test migrate-clickhouse runtime image (hard gate)",
    ]
    scan_steps = [
        'step "Trivy scan ${image_name} image (hard gate)"',
        'step "Generate ${image_name} SPDX SBOM"',
    ]

    build_position = docker_job.index("Build release images (${PLATFORM})")
    smoke_positions = [docker_job.index(step) for step in smoke_steps]
    scan_positions = [docker_job.index(step) for step in scan_steps]
    export_position = docker_job.index("Export validated runtime images")
    checksum_position = docker_job.index('step "validate-runtime-images', export_position)

    assert build_position < min(smoke_positions)
    assert max(smoke_positions) < min(scan_positions)
    assert max(scan_positions) < export_position < checksum_position
    # Export and architecture proof both iterate the shared list, so a new image
    # cannot be built, smoke-tested and then forgotten at export time.
    export_section = docker_job[export_position:]
    assert 'validated_images+=("soymutdb-${image_name}:ci-${ARCH}")' in export_section
    assert 'for image_name in "${IMAGE_NAMES[@]}"; do' in docker_job
    assert "docker save \"${validated_images[@]}\"" in export_section
    # Every smoke gate names the tag the shared builder produces.
    for image_name in ("api", "worker", "mcp", "jbrowse", "web", "admin", "migrate"):
        assert f'"soymutdb-{image_name}:ci-${{ARCH}}"' in docker_job, image_name

    assert "docker save" in docker_job[export_position:]
    assert "docker image inspect" in docker_job[export_position:]
    assert "sha256sum" in docker_job[export_position:]
    # Verification never logs in or pushes; publishing is a separate pipeline.
    assert "docker login" not in docker_job
    assert "docker push" not in docker_job


def test_ci_runtime_smoke_imports_real_api_and_full_worker_registry() -> None:
    verification = (ROOT / "scripts/build-release-image.sh").read_text(encoding="utf-8")

    assert "from app.main import app" in verification
    assert "import soymutdb_jobs" in verification
    assert "scripts/check-worker-task-registry.py" in verification
    assert "Smoke test API image (non-blocking)" not in verification


def test_ci_installs_local_jobs_package_before_api_and_worker_projects() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    # Every Python install step goes through the one shared bootstrap. The
    # editable workspace distributions (packages/jobs-py, and the import
    # protocol that does not exist on PyPI) are installed inside it, before the
    # app target, so the ordering rule lives in exactly one place.
    bootstrap = "scripts/install_python_workspace.py"
    frontend_job = _workflow_job(workflow, "frontend")
    assert bootstrap in frontend_job
    assert "pip install" not in frontend_job

    api_job = _workflow_job(workflow, "api-tests")
    assert bootstrap in api_job
    assert api_job.index(bootstrap) < api_job.index(
        "bash scripts/verify-backend-tests.sh"
    )

    # The worker deps are installed inside the shared backend verifier, after
    # the API package — one ordering rule, one place to change it.
    backend = (ROOT / "scripts/verify-backend-tests.sh").read_text(encoding="utf-8")
    assert backend.index(bootstrap) < backend.index("pytest apps/worker/tests -q")
    assert "apps/worker[dev]" in backend

    # The CNB verify pipeline installs the same local package first.
    cnb_job = _cnb_pipeline("verify")
    assert "scripts/ci-job-steps.sh run api-tests" in cnb_job


def test_offline_frontend_build_uses_demo_sample_data() -> None:
    """The generic verification build cannot require an unpublished API endpoint."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    frontend_job = _workflow_job(workflow, "frontend")
    verifier = (ROOT / "scripts/verify-frontend-artifacts.sh").read_text(encoding="utf-8")

    # The workflow supplies the demo origins through the environment...
    assert "VITE_DEPLOYMENT_MODE: demo" in frontend_job
    assert "scripts/verify-frontend-artifacts.sh" in frontend_job
    # ...and the shared script defaults to them and exports them for the build.
    assert "SOYMUTDB_CI_DEMO_MODE:-demo" in verifier
    assert 'VITE_DEPLOYMENT_MODE="${SOYMUTDB_CI_DEMO_MODE}"' in verifier

    cnb_job = json.loads(_cnb_pipeline("verify"))
    assert cnb_job["env"]["VITE_DEPLOYMENT_MODE"] == "demo"
    assert any(
        "scripts/ci-job-steps.sh run frontend" in (stage.get("script") or "")
        for stage in cnb_job["stages"]
    )


def test_full_worker_pytest_suite_is_a_hard_gate() -> None:
    """Worker Testcontainers coverage is a hard gate, not only an import check."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    api_job = _workflow_job(workflow, "api-tests")
    backend = (ROOT / "scripts/verify-backend-tests.sh").read_text(encoding="utf-8")

    assert "scripts/verify-backend-tests.sh" in api_job

    # The full worker suite is invoked unfiltered, after the analysis deps are
    # installed through the shared bootstrap; no `-k` narrowing and no skip flag
    # is allowed.
    assert "pytest apps/worker/tests -q" in backend
    assert "-k " not in backend
    assert backend.index("apps/worker[dev]") < backend.index("pytest apps/worker/tests -q")

    # The same verifier is what the CNB pipeline calls.
    cnb_job = _cnb_pipeline("verify")
    assert "scripts/ci-job-steps.sh run api-tests" in cnb_job


def test_real_postgresql_worker_integration_environment_is_required() -> None:
    """A missing PostgreSQL setup must fail CI instead of skip-green."""
    backend = (ROOT / "scripts/verify-backend-tests.sh").read_text(encoding="utf-8")

    # The verifier exports the flag itself, so no caller can forget it and turn
    # the privacy/identity/assembly matrix into skips.
    assert "export SOYMUTDB_RUN_POSTGRES_INTEGRATION=1" in backend

    # CNB supplies the service the gate needs to reach a database. It is
    # `docker`, not a `postgres` service: `services` only implements docker and
    # vscode, and `services: - postgres:16` was accepted while starting NOTHING
    # (measured: no DNS entry, nothing on 5432, no docker socket), which sent
    # the suite to Testcontainers and produced 116 docker stack traces.
    api_pipeline = _cnb_pipeline("verify")
    assert '"docker"' in api_pipeline
    assert "postgres:16" not in api_pipeline
    cnb_api_record = (ROOT / ".cnb/pipelines/api.yml").read_text(encoding="utf-8")
    assert "SOYMUTDB_RUN_POSTGRES_INTEGRATION" in cnb_api_record
    assert "- docker" in cnb_api_record

    # The database itself comes from the gate, which must fail closed.
    resolver = ROOT / "scripts" / "with-postgres-service.sh"
    assert resolver.is_file()
    assert "with-postgres-service.sh" in backend


def test_publish_is_the_only_registry_writer_and_loads_verified_artifacts() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    global_permissions = _top_level_block(workflow, "permissions")
    docker_job = _workflow_job(workflow, "docker-build")
    publish_job = _workflow_job(workflow, "publish-images")
    golden = (ROOT / "scripts/release-contract.golden.sh").read_text(encoding="utf-8")

    # The verification job holds no registry identity at all.
    assert "packages: write" not in global_permissions
    assert "actions: write" not in global_permissions
    assert "packages: write" not in docker_job
    assert "contents: read" in docker_job
    for prerequisite in (
        "frontend",
        "api-tests",
        "clickhouse-migration",
        "mcp-e2e",
    ):
        assert f"- {prerequisite}" in docker_job

    # The GitHub mirror still publishes only on main; CNB publishes on its
    # release pipeline with repository-scoped credentials.
    assert "needs: [docker-build, kubernetes-kind]" in publish_job
    assert "github.ref == 'refs/heads/main'" in publish_job
    assert "scripts/release-contract.golden.sh" in publish_job
    assert "validated-runtime-images" in publish_job
    assert "docker build" not in publish_job
    assert "trivy-action" not in publish_job

    checksum_position = golden.index("sha256sum -c")
    load_position = golden.index("docker load")
    id_check_position = golden.index("actual_id=")
    login_position = golden.index("docker login")
    push_position = golden.index("Tag and push validated platform images")
    assert (
        checksum_position
        < load_position
        < id_check_position
        < login_position
        < push_position
    )
    assert workflow.count("docker push") == 0
    # Exactly one push SITE (the loop body). The publisher may mention the
    # command in comments, so assert on the executing line, not on a bare count:
    # a comment explaining the push must not be able to mask a second push.
    push_lines = [
        line.strip()
        for line in golden.splitlines()
        if line.strip().startswith("docker push")
    ]
    assert push_lines == ['docker push "${image}"'], push_lines
    assert golden.count("docker push") >= 1
    merge_position = golden.index("Merge manifests, attest evidence, and write release manifest")
    contract_upload_position = golden.index("Upload signed OCI release contract")
    assert push_position < merge_position < contract_upload_position


def test_trivy_blocks_unfixed_high_and_critical_findings() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    docker_job = _workflow_job(workflow, "docker-build")
    verification = (ROOT / "scripts/build-release-image.sh").read_text(encoding="utf-8")

    # The scan policy lives in one script: two call sites (a native trivy binary
    # and a pinned container fallback) and four per-image invocations.
    assert "ignore-unfixed=false" in verification
    assert "ignore-unfixed=true" not in verification
    assert verification.count("--severity CRITICAL,HIGH") == 2
    # The scan policy lives in one script and is applied by one loop over the
    # shared image list, so an image cannot be built and then skipped by the
    # scanner because somebody forgot to add a line.
    assert "for image_name in \"${IMAGE_NAMES[@]}\"; do" in verification
    assert 'trivy_scan "soymutdb-${image_name}:ci-${ARCH}" "trivy-${image_name}.sarif"' in verification
    assert verification.count('trivy_scan "soymutdb-') == 1
    assert 'trivy_sbom "soymutdb-${image_name}:ci-${ARCH}"' in verification
    assert '--ignorefile .trivyignore' in verification
    assert "--exit-code 1" in verification

    # The workflow only calls the script; it cannot weaken the policy locally.
    assert "scripts/build-release-image.sh" in docker_job
    # The workflow comment references .trivyignore for reviewers, but no scan
    # policy is configured here — it only exists in the shared script.
    assert "ignore-unfixed" not in docker_job
    assert "--severity" not in docker_job
    assert "trivy image" not in docker_job


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
    # Environment contracts only; the build/publish mechanics are single-sourced
    # in scripts/{build,verify}-pages-artifact.sh.
    publisher = (ROOT / "scripts/build-pages-artifact.sh").read_text(encoding="utf-8")
    verifier = (ROOT / "scripts/verify-pages-artifact.sh").read_text(encoding="utf-8")
    ci = _cnb_pipeline("verify")
    publish_pipeline = _cnb_pipeline("publish")

    assert "VITE_DEPLOYMENT_MODE=demo" in publisher
    assert "VITE_BASE_URL" in publisher
    assert "VITE_API_BASE_URL" in publisher
    assert "VITE_JBROWSE_BASE_URL" in publisher
    assert "pages-dist/soymutdb-jbrowse" in publisher
    assert "secrets.API_BASE_URL" not in publisher
    assert "secrets.JBROWSE_URL" not in publisher

    ci_job = json.loads(ci)
    assert ci_job["env"]["VITE_DEPLOYMENT_MODE"] == "demo"
    assert ci_job["env"]["VITE_API_BASE_URL"]
    assert ci_job["env"]["VITE_JBROWSE_BASE_URL"]
    # The deployment base path is owned by the build script, so the pipeline
    # only has to provide the site slug and origin.
    assert "SOYMUTDB_SITE_SLUG" not in ci
    assert "PAGES_BASE_PATH" in verifier or "PAGES_BASE_PATH" in publisher
    assert "@soymutdb/admin build:web" not in ci
    assert "@soymutdb/admin" not in publish_pipeline

    for artifact in ("index.html", "soymutdb-jbrowse/index.html", "SHA256SUMS"):
        assert artifact in verifier


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
    publish_pipeline = _cnb_pipeline("publish")
    verifier = (ROOT / "scripts/verify-pages-artifact.sh").read_text(encoding="utf-8")

    for variable in ("PUBLICATION_ID", "ARTIFACT_URL", "MANIFEST_DIGEST"):
        assert variable in verifier
    # The publication pipeline stays artifact-driven; it never rebuilds. It
    # delegates to scripts/stage-pages-publication.sh, which is the single place
    # that invokes the verifier (the stage body itself must be a plain
    # `bash <script>` call: CNB executes it with `sh`).
    assert "stage-pages-publication.sh" in publish_pipeline
    stage = (ROOT / "scripts/stage-pages-publication.sh").read_text(encoding="utf-8")
    assert "verify-pages-artifact.sh" in stage
    assert "build-pages-artifact.sh" not in publish_pipeline
    assert "pnpm" not in publish_pipeline


def test_pages_verifies_digest_before_ref_update() -> None:
    pipeline = _cnb_pipeline("publish")
    verifier = (ROOT / "scripts/verify-pages-artifact.sh").read_text(encoding="utf-8")

    assert "MANIFEST_DIGEST" in verifier
    # The digest check happens before any extraction or publication step.
    assert verifier.index("MANIFEST_DIGEST") < verifier.index("tar -xzf")
    assert "sha256sum -c SHA256SUMS" in verifier
    # The publication pipeline runs the verifier before staging anything:
    # `verify` is the first stage, and staging happens in the same script only
    # after verify-pages-artifact.sh has succeeded.
    assert "stage-pages-publication.sh verify" in pipeline
    stage = (ROOT / "scripts/stage-pages-publication.sh").read_text(encoding="utf-8")
    assert stage.index("verify-pages-artifact.sh") < stage.index("cp -a")
    assert "build-pages-artifact.sh" not in pipeline


def test_pages_publishes_the_exact_verified_static_tree_without_rebuilding() -> None:
    """Publication must deploy verified bytes, not rebuild source later."""
    verifier = (ROOT / "scripts/verify-pages-artifact.sh").read_text(encoding="utf-8")
    pages = (ROOT / "scripts/build-pages-artifact.sh").read_text(encoding="utf-8")
    pipeline = _cnb_pipeline("verify")
    publisher = _cnb_pipeline("publish")

    assert "pages-dist" in pages
    assert "SHA256SUMS" in pages
    assert "sha256sum -c SHA256SUMS" in verifier
    # The verify pipeline builds, self-verifies, and uploads the artifact under
    # the name the publication pipeline consumes.
    verify_job = json.loads(_cnb_pipeline("verify"))
    verify_text = json.dumps(verify_job)
    assert "pages-demo-dist" in verify_text
    assert "verify-pages-artifact.sh" in verify_text
    assert "Upload GitHub Pages demo artifact" in verify_text

    # Publication consumes the artifact; it never installs a JS toolchain, never
    # rebuilds the web bundle, and never runs the build script.
    assert "pnpm install" not in publisher
    assert "pnpm --filter @soymutdb/web build" not in publisher
    assert "pnpm --filter @soymutdb/jbrowse build" not in publisher
    assert "stage-pages-publication.sh" in publisher
    assert "build-pages-artifact.sh" not in publisher
