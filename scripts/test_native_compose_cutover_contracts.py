"""Native default topology and isolated legacy migration contracts."""

from pathlib import Path

from compose_loader import load_compose

ROOT = Path(__file__).resolve().parents[1]


def test_native_topologies_have_no_clickhouse_runtime_dependency():
    for name in ("docker-compose.yml", "docker-compose.dev.yml", "docker-compose.local.yml",
                 "docker-compose.preview.yml"):
        compose = load_compose(ROOT / name)
        assert "clickhouse" not in compose["services"]
        assert "migrate-clickhouse" not in compose["services"]
        for service in compose["services"].values():
            assert "clickhouse" not in service.get("depends_on", {})
            assert not any("CLICKHOUSE" in key for key in service.get("environment", {}))


def test_legacy_source_requires_explicit_overlay_and_credentials():
    legacy = load_compose(ROOT / "docker-compose.legacy-clickhouse.yml")
    assert set(legacy["services"]) == {"clickhouse", "migrate-clickhouse"}
    for service in legacy["services"].values():
        assert service["profiles"] == ["legacy-migration"]
    assert "CLICKHOUSE_PASSWORD:?" in legacy["services"]["clickhouse"]["environment"][
        "CLICKHOUSE_PASSWORD"
    ]
    assert set(legacy["volumes"]) == {"chdata", "chbackups"}


def test_upgrade_verifies_native_evidence_before_startup():
    script = (ROOT / "deploy/scripts/upgrade.sh").read_text(encoding="utf-8")
    assert "MIGRATE_CLICKHOUSE_IMAGE_REF" not in script
    assert "run --rm migrate-clickhouse" not in script
    gate = script.index("python -m app.scripts.verify_native_cutover")
    assert script.index('run --rm migrate || fail') < gate
    startup = script.index("# Step 7:")
    assert gate < startup
    assert '"${COMPOSE[@]}" up -d' in script[startup:]
