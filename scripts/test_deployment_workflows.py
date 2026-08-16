from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_pushes_images_to_repository_owner_namespace() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "GITHUB_REPOSITORY_OWNER,," in workflow
    assert "ghcr.io/soymutdb/" not in workflow


def test_ci_grants_package_write_for_ghcr_pushes() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "packages: write" in workflow


def test_ci_pushes_mcp_from_the_image_name_it_builds() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert '"soymutdb-mcp:ci" "ghcr.io/${registry_owner}/mcp-server:${RELEASE_TAG}"' in workflow


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


def test_pages_deploys_an_explicit_public_demo() -> None:
    workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")

    assert "VITE_DEPLOYMENT_MODE: demo" in workflow
    assert "VITE_BASE_URL: /soymutdb-next/" in workflow
    assert "github.repository_owner" in workflow
    assert "github.event.repository.name }}/api/v1" in workflow
    assert "github.event.repository.name }}/soymutdb-jbrowse/" in workflow
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
