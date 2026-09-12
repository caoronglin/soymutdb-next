"""Static contracts for the production Compose runtime.

These checks intentionally do not require a local Docker daemon. They prevent
resource limits, process budgets, and container hardening from silently
regressing when service definitions change.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

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
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


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


# ---------------------------------------------------------------------------
# Docker build context
# ---------------------------------------------------------------------------
def test_dockerignore_excludes_generated_output_without_hiding_sources() -> None:
    """`.dockerignore` must drop generated trees without hiding real sources.

    Docker evaluates `.dockerignore` against the build context, which for every
    Dockerfile in this repository is the repository root. Two failure modes make
    the naive form dangerous:

      * A bare `**/dist` matches a directory at ANY depth, so it also removes the
        `dist/` trees other Dockerfiles consume;
      * a pattern aimed at one app's output (e.g. a broad `web`) silently removes
        `apps/web/` and every source file under it, and the build then fails at
        `COPY` with "not found in build context", which reads like a missing file
        rather than a context-policy mistake.

    Both are checked, so the exclusion list can keep being narrowed or widened
    without ever swallowing an input an image build needs.
    """
    import fnmatch

    patterns = [
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    def excluded(path: str) -> bool:
        """Apply the patterns in order, honouring `!` re-inclusion (Docker/Kaniko)."""
        decided = False
        for pattern in patterns:
            negate = pattern.startswith("!")
            candidate = pattern.lstrip("!")
            if fnmatch.fnmatch(path, candidate) or path.startswith(
                candidate.rstrip("/") + "/"
            ):
                decided = not negate
        return decided

    # 1. Generated output stays out of the context.
    for generated in (
        "apps/web/dist/index.html",
        "apps/admin/dist/index.html",
        "apps/jbrowse/dist/main.js",
        "node_modules/react/index.js",
        "apps/web/coverage/index.html",
    ):
        assert excluded(generated), f"{generated} is generated and must be excluded"

    # 2. Every source an image build COPYs stays in it. A wrong pattern here
    #    surfaces as `COPY failed: ... excluded by .dockerignore`.
    for source in (
        "apps/web/package.json",
        "apps/web/src/main.ts",
        "apps/web/scripts/ssg-build.ts",
        "apps/web/vite.config.ts",
        "apps/admin/package.json",
        "apps/admin/src/main.tsx",
        "apps/api/pyproject.toml",
        "apps/api/uv.lock",
        "apps/api/app/main.py",
        "apps/worker/pyproject.toml",
        "apps/jbrowse/Dockerfile",
        "apps/jbrowse/index.html",
        "apps/jbrowse/public/_headers",
        "packages/shared/package.json",
        "packages/shared/src/index.ts",
        "packages/api-client/package.json",
        "packages/i18n/package.json",
        "infra/docker/precompress.sh",
        "infra/docker/web-nginx.conf",
        "package.json",
        "pnpm-workspace.yaml",
        "pnpm-lock.yaml",
        "turbo.json",
        ".npmrc",
    ):
        assert not excluded(source), (
            f"{source} is a Dockerfile COPY source but .dockerignore removes it; "
            "the image build fails with `excluded by .dockerignore`"
        )

    # 3. The per-app form is what keeps the two apart. `**/dist` cannot.
    assert "**/dist" not in patterns, (
        "`**/dist` matches every generated tree at any depth; list the per-app "
        "output directories instead"
    )
    for app in ("web", "admin", "jbrowse"):
        assert f"apps/{app}/dist" in patterns, f"missing an exclusion for apps/{app}/dist"


def test_worker_image_resolves_its_dependency_graph_once() -> None:
    """The worker image must not repeat the same locked resolution.

    `infra/docker/Dockerfile.worker` ran `uv sync --frozen --no-dev
    --no-install-project --project apps/worker` twice with byte-identical
    arguments: once after copying the manifests, then again after copying
    `apps/worker`. The second run was documented as installing the entry point,
    but `--no-install-project` makes it a no-op for that purpose -- `uv sync` is
    a full resolution pass from `uv.lock`, and repeating it means resolving the
    whole Celery/psycopg/analyses/htslib graph a second time on archive rebuilds.

    One resolution is enough: the package is never installed into `/opt/venv`,
    it is imported through the `PYTHONPATH` roots the runtime stage exports.
    """
    dockerfile = (ROOT / "infra/docker/Dockerfile.worker").read_text(encoding="utf-8")

    syncs = [
        line.strip()
        for line in dockerfile.splitlines()
        if line.strip().startswith("RUN ") and "uv sync" in line
    ]
    assert len(syncs) == 1, (
        "the worker image resolves its dependency graph more than once:\n"
        + "\n".join(syncs)
    )
    assert "--frozen" in syncs[0] and "--no-dev" in syncs[0]

    # The application must therefore be reachable from source, not from the
    # environment's site-packages.
    assert (
        'PYTHONPATH="/app/packages/jobs-py/src:/app/apps/worker/src"' in dockerfile
    ), "the worker runtime must import the application from the PYTHONPATH roots"


def test_api_image_resolves_its_dependency_graph_once() -> None:
    """Same invariant for the API image, so neither can quietly drift back."""
    dockerfile = (ROOT / "infra/docker/Dockerfile.api").read_text(encoding="utf-8")
    syncs = [
        line.strip()
        for line in dockerfile.splitlines()
        if line.strip().startswith("RUN ") and "uv sync" in line
    ]
    assert len(syncs) == 1, "\n".join(syncs)
    assert "--frozen" in syncs[0] and "--no-dev" in syncs[0]
    assert "WORKDIR /app/apps/api" in dockerfile


def test_documented_worker_runtime_matches_the_shipped_one() -> None:
    """The worker README must describe the toolchain and image that exist.

    It documented Python 3.13, `uv pip install -e .` and a bare
    `docker build -t soymutdb-worker .`. All three were wrong: the project
    requires 3.14 (as does the pinned image tag), dependencies are resolved from
    the locked project rather than ad hoc, and `apps/worker/` has no Dockerfile
    for `docker build .` to find -- the definition lives at
    `infra/docker/Dockerfile.worker` with the repository root as its context.

    Each wrong instruction is a dead end for whoever follows it, which is why
    they are pinned rather than left as prose.
    """
    readme = (ROOT / "apps/worker/README.md").read_text(encoding="utf-8")
    dockerfile = (ROOT / "infra/docker/Dockerfile.worker").read_text(encoding="utf-8")
    pyproject = (ROOT / "apps/worker/pyproject.toml").read_text(encoding="utf-8")

    # 1. The interpreter it claims, checked against the manifest rather than a
    #    literal, so a pin bump cannot leave the README behind.
    pinned = re.search(r'requires-python\s*=\s*"\s*>=\s*(\d+\.\d+)\s*"', pyproject)
    assert pinned, "apps/worker/pyproject.toml must declare requires-python"
    assert f"Python {pinned.group(1)}" in readme, (
        f"apps/worker/README.md must state Python {pinned.group(1)}"
    )
    for stale in ("Python 3.13", "Python 3.12", "Python 3.11"):
        assert stale not in readme, f"apps/worker/README.md still claims {stale}"

    # 2. The dependency-resolution command it recommends.
    assert "uv pip install -e ." not in readme, (
        "apps/worker is a locked uv project; `uv pip install -e .` bypasses "
        "uv.lock and is how a machine ends up on a different dependency set "
        "than the image"
    )
    assert "uv sync --frozen" in readme

    # 3. The build command it recommends must point at the real Dockerfile.
    assert "docker build -f infra/docker/Dockerfile.worker" in readme
    assert not (ROOT / "apps/worker/Dockerfile").exists(), (
        "apps/worker/Dockerfile does not exist, so the README must not imply it"
    )

    # 4. The Celery app path it prints must be the one the image uses.
    assert "soymutdb_worker.main:celery_app" in readme
    assert "-A soymutdb_worker.main:celery_app" in dockerfile
