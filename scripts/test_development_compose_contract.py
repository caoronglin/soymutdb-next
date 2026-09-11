"""Static contract checks for the documented development Compose topology."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docker-compose.yml"
DEV = ROOT / "docker-compose.dev.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_development_compose_is_an_overlay_for_the_production_topology() -> None:
    base = _load(BASE)
    dev = _load(DEV)

    assert "Development overlay" in DEV.read_text(encoding="utf-8")
    assert "-f docker-compose.yml -f docker-compose.dev.yml" in DEV.read_text(encoding="utf-8")
    assert set(dev["services"]) - set(base["services"]) == {"web", "admin"}


def test_development_overlay_replaces_production_image_requirements() -> None:
    dev_services = _load(DEV)["services"]

    for service_name in (
        "api",
        "worker-default",
        "worker-blast",
        "worker-ingest",
        "worker-analyses",
        "beat",
    ):
        service = dev_services[service_name]
        assert service["image"] is None
        assert service["build"]["context"] == "."


def test_development_web_and_admin_are_standalone_node_services() -> None:
    dev_services = _load(DEV)["services"]

    for service_name, port in (("web", "5173:5173"), ("admin", "5174:5174")):
        service = dev_services[service_name]
        assert service["image"] == "node:24.19.0-alpine"
        assert service["working_dir"] == "/app"
        assert service["ports"] == [port]
        assert "pnpm install --frozen-lockfile" in service["command"]
        assert "build" not in service


def test_development_overlay_supplies_the_base_required_credentials() -> None:
    dev_services = _load(DEV)["services"]

    assert dev_services["postgres"]["environment"]["POSTGRES_PASSWORD"]
    assert dev_services["clickhouse"]["environment"]["CLICKHOUSE_PASSWORD"]
    assert dev_services["minio"]["environment"]["MINIO_ROOT_USER"]
    assert dev_services["minio"]["environment"]["MINIO_ROOT_PASSWORD"]
    for service_name in ("redis", "redis-celery"):
        assert "soymutdb_dev_password" in dev_services[service_name]["command"]
