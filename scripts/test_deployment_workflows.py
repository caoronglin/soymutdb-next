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
