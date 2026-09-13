"""Static contracts for the production Compose runtime.

These checks intentionally do not require a local Docker daemon. They prevent
resource limits, process budgets, and container hardening from silently
regressing when service definitions change.
"""

from __future__ import annotations

import re
from pathlib import Path

from compose_loader import load_compose

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.yml"
API_DOCKERFILE = ROOT / "infra/docker/Dockerfile.api"

APP_SERVICES = (
    "api",
    "worker-default",
    "worker-blast",
    "worker-ingest",
    "worker-analyses",
    "beat",
    "mcp-server",
)
WORKER_SERVICES = (
    "worker-default",
    "worker-blast",
    "worker-ingest",
    "worker-analyses",
)
EXPECTED_MEMORY_VARIABLES = {
    "api": "${API_MEMORY_LIMIT:-2g}",
    "worker-default": "${WORKER_DEFAULT_MEMORY_LIMIT:-4g}",
    "worker-blast": "${WORKER_BLAST_MEMORY_LIMIT:-8g}",
    "worker-ingest": "${WORKER_INGEST_MEMORY_LIMIT:-4g}",
    "worker-analyses": "${WORKER_ANALYSES_MEMORY_LIMIT:-8g}",
    "beat": "${BEAT_MEMORY_LIMIT:-512m}",
    "mcp-server": "${MCP_MEMORY_LIMIT:-1g}",
}


def _compose() -> dict:
    # Compose-specific tags (`!reset`) are understood by the shared loader; see
    # scripts/compose_loader.py.
    return load_compose(COMPOSE_PATH)


def _default_int(value: str) -> int:
    match = re.fullmatch(r"\$\{[^:}]+:-(\d+)\}", value)
    assert match is not None, f"expected an integer Compose default, got {value!r}"
    return int(match.group(1))


def test_application_containers_drop_linux_capabilities() -> None:
    services = _compose()["services"]

    for name in APP_SERVICES:
        service = services[name]
        assert service["init"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service.get("privileged") is not True


def test_long_running_application_services_have_resource_and_stop_budgets() -> None:
    services = _compose()["services"]

    for name, memory in EXPECTED_MEMORY_VARIABLES.items():
        service = services[name]
        assert service["mem_limit"] == memory
        assert service["cpus"]
        assert service["pids_limit"]
        assert service["stop_grace_period"]

    assert services["worker-blast"]["stop_grace_period"] == (
        "${WORKER_BLAST_STOP_GRACE_PERIOD:-10m}"
    )


def test_default_database_connection_budget_stays_below_half_capacity() -> None:
    services = _compose()["services"]
    api_env = services["api"]["environment"]
    workers = _default_int(api_env["SOYMUTDB_API_WORKERS"])
    api_pool = _default_int(api_env["SOYMUTDB_DB_POOL_SIZE"])
    api_overflow = _default_int(api_env["SOYMUTDB_DB_MAX_OVERFLOW"])

    shared_env = services["worker-default"]["environment"]
    worker_pool = _default_int(shared_env["SOYMUTDB_WORKER_DB_POOL_SIZE"])
    worker_overflow = _default_int(shared_env["SOYMUTDB_WORKER_DB_MAX_OVERFLOW"])
    total_concurrency = sum(
        _default_int(services[name]["command"].split("--concurrency=")[1].split()[0])
        for name in WORKER_SERVICES
    )

    application_connections = workers * (
        api_pool + api_overflow
    ) + total_concurrency * (worker_pool + worker_overflow)
    assert application_connections == 20
    assert application_connections <= 40


def test_api_process_count_and_grace_period_are_runtime_configurable() -> None:
    service = _compose()["services"]["api"]
    assert (
        service["environment"]["SOYMUTDB_API_WORKERS"] == "${SOYMUTDB_API_WORKERS:-2}"
    )
    assert service["environment"]["SOYMUTDB_API_GRACEFUL_SHUTDOWN_SECONDS"] == (
        "${SOYMUTDB_API_GRACEFUL_SHUTDOWN_SECONDS:-30}"
    )

    dockerfile = API_DOCKERFILE.read_text(encoding="utf-8")
    assert "PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus-multiproc" in dockerfile
    assert "rm -f /tmp/prometheus-multiproc/*.db" in dockerfile
    assert "exec uvicorn" in dockerfile
    assert "--workers ${SOYMUTDB_API_WORKERS:-2}" in dockerfile
    assert "--timeout-graceful-shutdown" in dockerfile


def test_api_compose_healthcheck_uses_the_python_standard_library() -> None:
    """The runtime image need not carry curl solely for liveness."""
    healthcheck = _compose()["services"]["api"]["healthcheck"]["test"]

    assert healthcheck[0] == "CMD"
    assert healthcheck[1] == "python"
    assert "urllib.request" in healthcheck[3]
    assert "/api/v1/health/live" in healthcheck[3]
