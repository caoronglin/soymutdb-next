from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_pushes_images_to_repository_owner_namespace() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "GITHUB_REPOSITORY_OWNER,," in workflow
    assert "ghcr.io/soymutdb/" not in workflow


def test_clickhouse_fixture_enables_multiquery() -> None:
    script = (ROOT / "deploy/scripts/migrate-ch-fixture.sh").read_text(
        encoding="utf-8"
    )

    assert "multiquery=1" in script
