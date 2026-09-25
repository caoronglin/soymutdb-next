import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import yaml

from compose_loader import load_compose

ROOT = Path(__file__).resolve().parents[1]
NODE_VERSION = "24.19.0"
PNPM_VERSION = "12.5.1"
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
DATA_SERVICES = ("postgres", "clickhouse", "redis", "minio")
# Release services that the local wrapper rebuilds from the checkout. The
# production file declares no `build:` for any of them: a release host pulls a
# signed digest and must never build from source. scripts/compose-local.sh is
# the only builder, sourcing scripts/list-images.sh and running `docker build`
# directly before Compose starts.
RELEASE_SERVICES = {
    "api",
    "worker-default",
    "worker-blast",
    "worker-ingest",
    "worker-analyses",
    "beat",
    "mcp-server",
    "migrate",
    "migrate-clickhouse",
}
PLATFORM_CATALOG = {
    "react": "19.2.0",
    "react-dom": "19.2.0",
    "typescript": "5.9.3",
    "vite": "6.4.3",
    "antd": "6.6.1",
    # Vue mainline (plan.md §2, Phase D): the migrated portal consumes these
    # through the same reviewed catalog decision as the React platform.
    "vue": "3.5.43",
    "@vitejs/plugin-vue": "6.0.9",
    "vitest": "3.2.7",
    "vue-router": "5.3.1",
    "pinia": "4.0.3",
    "@tanstack/vue-query": "5.103.2",
    "antdv-next": "1.5.4",
    "tailwindcss": "4.3.3",
    "@tailwindcss/vite": "4.3.3",
}


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _compose() -> dict:
    # Compose-specific tags (`!reset`) are understood by the shared loader.
    return load_compose(ROOT / "docker-compose.yml")


def _compose_tags(path: Path) -> set[str]:
    """All YAML node tags in a Compose document.

    Walking parsed nodes, rather than searching raw text, means a comment that
    merely mentions `!reset` can neither satisfy nor defeat the assertion.
    """
    tags: set[str] = set()
    stack = [yaml.compose(path.read_text(encoding="utf-8"))]
    while stack:
        node = stack.pop()
        assert node is not None
        tags.add(node.tag)
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                stack.extend((key, value))
        elif isinstance(node, yaml.SequenceNode):
            stack.extend(node.value)
    return tags


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


def _plain(value: object) -> str:
    """Serialize parsed configuration for substring assertions."""
    return json.dumps(value, ensure_ascii=False)


def _pipeline_source() -> str:
    """The single source of truth for delivery/build pipeline configuration."""
    return (ROOT / ".cnb.yml").read_text(encoding="utf-8")


def test_node_and_pnpm_toolchain_is_exact_in_jobs_that_build_assets() -> None:
    package = _json("package.json")

    assert (ROOT / ".nvmrc").read_text(encoding="utf-8").strip() == NODE_VERSION
    assert (ROOT / ".node-version").read_text(encoding="utf-8").strip() == NODE_VERSION
    assert package["packageManager"] == f"pnpm@{PNPM_VERSION}"
    assert package["engines"] == {"node": ">=24.0.0 <25", "pnpm": PNPM_VERSION}

    # CNB is the primary delivery pipeline. Every pipeline that builds or tests
    # the workspace must pin the exact Node release; the smoke pipeline runs the
    # same Playwright suites, so it shares the pin.
    pipeline_sources = [ROOT / ".cnb.yml"] + sorted((ROOT / ".cnb/pipelines").glob("*.yml"))
    for path in pipeline_sources:
        text = path.read_text(encoding="utf-8")
        assert "node:22" not in text, path
        assert "node:20" not in text, path
        if "node:" in text:
            assert f"node:{NODE_VERSION}" in text, path
    assert f"node:{NODE_VERSION}" in (ROOT / ".cnb.yml").read_text(encoding="utf-8")

    # Publication consumes the already-built, checksummed web artifact;
    # installing a JS toolchain in the publisher would invite a second,
    # non-identical build.
    pages = yaml.safe_load(_pipeline_source())
    deploy_job = _plain(
        next(p for p in pages["main"]["push"] if p["name"] == "publish")
    )
    assert "pnpm install" not in deploy_job
    assert "pnpm --filter" not in deploy_job
    # The publisher delegates to scripts/stage-pages-publication.sh, which is the
    # single place that runs the verifier. Keeping the verifier call inside a
    # script (rather than in the stage body) is also what makes the stage
    # shell-independent: CNB executes a stage body with `sh`.
    assert "stage-pages-publication.sh" in deploy_job
    stage = (ROOT / "scripts/stage-pages-publication.sh").read_text(encoding="utf-8")
    assert "verify-pages-artifact.sh" in stage
    for script in (
        "scripts/build-pages-artifact.sh",
        "scripts/verify-pages-artifact.sh",
        "scripts/stage-pages-publication.sh",
    ):
        assert (ROOT / script).is_file(), script

    ci_text = _plain(next(p for p in pages["main"]["push"] if p["name"] == "verify"))
    assert "Build the checksummed Pages artifact" in ci_text
    assert "scripts/verify-pages-artifact.sh" in ci_text
    assert "Upload GitHub Pages demo artifact" in ci_text


def workspace_catalog() -> dict:
    return yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))["catalog"]


def test_frontend_platform_lines_remain_bounded() -> None:
    """The React line and the Vue line both stay pinned, each where it is used.

    `apps/web` is the Vue portal, so it carries no React dependency at all; the
    React line is bounded where a React app actually ships (admin, JBrowse), and
    the Vue line is bounded in the portal.
    """
    root_package = _json("package.json")
    workspace = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))

    assert root_package["devDependencies"]["typescript"].startswith("^5.9.")
    assert workspace["overrides"]["react"] == "19.2.0"
    assert workspace["overrides"]["react-dom"] == "19.2.0"

    for app in ("admin", "jbrowse"):
        package = _json(f"apps/{app}/package.json")
        assert package["dependencies"]["react"].startswith("^19.2.")
        assert package["dependencies"]["react-dom"].startswith("^19.2.")
        assert package["devDependencies"]["typescript"].startswith("^5.9.")
        assert package["devDependencies"]["vite"].startswith("^6.")

    portal = _json("apps/web/package.json")
    for dependency in ("react", "react-dom", "antd", "echarts", "@tanstack/react-router"):
        assert dependency not in portal["dependencies"], (
            f"apps/web still depends on {dependency}: the portal is Vue-only"
        )
    # The portal consumes Vue through the same reviewed catalog decision as the
    # React line consumes React, so the assertion is on the catalog entry.
    assert portal["dependencies"]["vue"] == "catalog:"
    assert workspace["catalog"]["vue"] == "3.5.43"
    assert portal["devDependencies"]["typescript"] == "catalog:"
    assert portal["devDependencies"]["vite"] == "catalog:"
    assert workspace["catalog"]["typescript"] == "5.9.3"
    assert workspace["catalog"]["vite"] == "6.4.3"


def test_tiptap_family_stays_above_the_redos_advisory() -> None:
    """Every @tiptap/* pin must clear GHSA-j95f-988m-3j2f.

    The governance gate runs `pnpm audit --audit-level high` and blocks on a
    nonzero exit, so a transitive high advisory under one of these pins is a
    build failure. The advisory is only patched from 3.30.5, and it is a
    **production** dependency of the admin rich-text editor -- not dev-only.

    The family is pinned explicitly in apps/admin rather than through a
    workspace override, so this is the one place a pin can silently fall back
    under the fix. Assert every pin, and that they all agree: @tiptap/core and
    @tiptap/pm must resolve as a matching pair or the editor fails to load.
    """
    patched = (3, 30, 5)
    package = _json("apps/admin/package.json")
    pins = {name: value for name, value in package["dependencies"].items() if name.startswith("@tiptap/")}

    assert pins, "apps/admin must pin its @tiptap/* dependencies explicitly"
    for name, raw in pins.items():
        value = re.sub(r"^[^\d]*", "", str(raw))
        resolved = tuple(int(part) for part in value.split(".")[:3])
        assert resolved >= patched, (
            f"{name} is {raw}; GHSA-j95f-988m-3j2f is only patched from "
            f"{'.'.join(str(p) for p in patched)}, and the governance gate "
            "fails the build on it"
        )

    versions = {str(value) for value in pins.values()}
    assert len(versions) == 1, (
        f"the @tiptap/* family must move in lockstep, found {sorted(versions)}"
    )


def test_workspace_security_override_holds_the_js_yaml_floor() -> None:
    """The js-yaml floor must clear GHSA-2883-xcg3-v3hh.

    `js-yaml` is reached transitively (api-client > openapi-typescript >
    @redocly/openapi-core), so it cannot be pinned in a package.json; the
    workspace `overrides` block is the only lever. Assert the resolved FLOOR,
    not merely that the key exists -- a floor lowered below 4.3.2 re-introduces
    the high-severity advisory while still looking configured.
    """
    workspace = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))
    raw = workspace["overrides"].get("js-yaml")
    assert raw is not None, (
        "js-yaml has a blocking high advisory (GHSA-2883-xcg3-v3hh); keep the "
        "security floor in pnpm-workspace.yaml `overrides`"
    )
    resolved = tuple(int(part) for part in str(raw).split("."))
    assert resolved >= (4, 3, 2), f"js-yaml floor {raw} is below the patched 4.3.2"


def test_workspace_catalog_pins_platform_dependencies() -> None:
    workspace = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))

    assert workspace["catalog"] == PLATFORM_CATALOG


def test_dependency_build_scripts_are_fail_closed_except_for_esbuild() -> None:
    workspace = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))

    # vue-demi's postinstall selects the installed Vue runtime for the VueUse
    # line; everything else stays denied by default.
    assert workspace["allowBuilds"] == {"esbuild": True, "vue-demi": True}


def test_antd_consumers_resolve_from_workspace_catalog() -> None:
    """AntD stays a catalog decision for the React apps that still use it.

    The portal moved to `@soymutdb/ui-vue` (Antdv Next behind a facade), so it no
    longer resolves AntD at all — that is the point of the facade.
    """
    for app in ("admin",):
        package = _json(f"apps/{app}/package.json")
        assert package["dependencies"]["antd"] == "catalog:"

    portal = _json("apps/web/package.json")
    assert "antd" not in portal["dependencies"]
    assert "@soymutdb/ui-vue" in portal["dependencies"]


def test_pro_components_dependency_is_removed_after_source_migration() -> None:
    for app in ("web", "admin"):
        package = _json(f"apps/{app}/package.json")
        assert "@ant-design/pro-components" not in package["dependencies"]
    assert "@ant-design/pro-components" not in workspace_catalog()

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
    # Every release service has its OWN digest reference. The migration services
    # used to borrow API_IMAGE_REF / WORKER_IMAGE_REF, which pinned the migration
    # step to the API's tag while api itself moved to a digest — an upgrade that
    # updated only the digest references would then run the previous release's
    # migrations.
    service_refs = {
        "migrate": "MIGRATE_IMAGE_REF",
        "api": "API_IMAGE_REF",
        "migrate-clickhouse": "MIGRATE_CLICKHOUSE_IMAGE_REF",
        "worker-default": "WORKER_IMAGE_REF",
        "worker-blast": "WORKER_IMAGE_REF",
        "worker-ingest": "WORKER_IMAGE_REF",
        "worker-analyses": "WORKER_IMAGE_REF",
        "beat": "WORKER_IMAGE_REF",
        "mcp-server": "MCP_IMAGE_REF",
        "jbrowse": "JBROWSE_IMAGE_REF",
    }
    assert len(set(service_refs.values())) == len(
        {"MIGRATE_IMAGE_REF", "API_IMAGE_REF", "MIGRATE_CLICKHOUSE_IMAGE_REF",
         "WORKER_IMAGE_REF", "MCP_IMAGE_REF", "JBROWSE_IMAGE_REF"}
    )

    for service_name, variable_name in service_refs.items():
        service = services[service_name]
        assert service["image"].startswith(f"${{{variable_name}:?")
        assert "image@sha256" in service["image"]
        # No release service may declare a `build:`. The production file is
        # release-only: a host that can build from a checkout is a host that can
        # run unsigned code. Local builds belong to scripts/compose-local.sh,
        # which runs `docker build` for the images scripts/list-images.sh names.
        assert "build" not in service, (
            f"{service_name} must not carry a Compose build definition"
        )

    env = _example_env()
    digest_ref = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}$")
    for variable_name in set(service_refs.values()):
        assert digest_ref.fullmatch(env[variable_name]), (variable_name, env[variable_name])
    assert set(env["COMPOSE_PROFILES"].split(",")) == {"core", "blast", "analyses", "mcp"}

    # The local-build override is a separate post-merge file. It cannot prevent
    # base interpolation, so the wrapper also supplies safe local values for all
    # production required references before Compose reads either file.
    base_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "x-service-local-" not in base_text
    assert "x-service-build" not in base_text
    for service_name in RELEASE_SERVICES:
        assert "build" not in services[service_name], service_name

def test_local_compose_wrapper_uses_a_post_merge_override() -> None:
    """Local image names must actually replace release refs in Compose.

    The production file carries no `build:` to reset, so docker-compose.local.yml
    only rewrites `image:` scalars. Building is the wrapper's job: it sources
    scripts/list-images.sh and calls `docker build` per entry.
    """
    local = (ROOT / "docker-compose.local.yml").read_text(encoding="utf-8")
    wrapper = (ROOT / "scripts/compose-local.sh").read_text(encoding="utf-8")

    assert "docker-compose.local.yml" in wrapper
    assert "-f \"${REPO_ROOT}/docker-compose.yml\"" in wrapper
    assert "-f \"${REPO_ROOT}/docker-compose.local.yml\"" in wrapper
    # Local builds are direct `docker build` invocations driven by the shared
    # image list, not Compose build definitions.
    assert "scripts/list-images.sh" in wrapper
    assert "docker build" in wrapper
    assert "soymutdb_image_entry" in wrapper
    for variable in (
        "API_IMAGE",
        "WORKER_IMAGE",
        "MCP_IMAGE",
        "MIGRATE_IMAGE",
        "MIGRATE_CLICKHOUSE_IMAGE",
    ):
        assert f'image: "${{{variable}:-' in local
    # The local file must not carry a build definition for any service (or a
    # `!reset`); the production base declares none to remove either. The build
    # check runs against parsed service definitions; `!reset` is a parsed YAML
    # node tag, so a comment that merely mentions it cannot satisfy the check.
    local_path = ROOT / "docker-compose.local.yml"
    local_services = load_compose(local_path)["services"]
    for service_name, service in local_services.items():
        assert "build" not in service, service_name
    assert "!reset" not in _compose_tags(local_path)
    assert "!override" not in _compose_tags(local_path)

    required = (
        "API_IMAGE_REF",
        "WORKER_IMAGE_REF",
        "MIGRATE_IMAGE_REF",
        "MIGRATE_CLICKHOUSE_IMAGE_REF",
        "MCP_IMAGE_REF",
        "JBROWSE_IMAGE_REF",
        "POSTGRES_PASSWORD",
        "CLICKHOUSE_PASSWORD",
        "REDIS_PASSWORD",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "GRAFANA_PASSWORD",
        "SOYMUTDB_MCP_API_TOKEN",
    )
    for variable in required:
        assert f"set_compose_default {variable} " in wrapper

    # Model the resolved service slots after the overlay: image is a normal
    # scalar replacement, and neither file contributes a build definition.
    base = _compose()["services"]
    overlay = load_compose(ROOT / "docker-compose.local.yml")["services"]
    for service_name in RELEASE_SERVICES:
        assert overlay[service_name]["image"] != base[service_name]["image"]
        assert "build" not in base[service_name], service_name
        assert "build" not in overlay[service_name], service_name


# ---------------------------------------------------------------------------
# Local compose wrapper: empty env-file values and profile precedence
# ---------------------------------------------------------------------------
_STUB_DOCKER_COMPOSE_LOCAL = """#!/usr/bin/env bash
echo "DOCKER_ARGS=$*"
echo "POSTGRES_PASSWORD=${POSTGRES_PASSWORD-<unset>}"
"""


def _run_compose_local_with_stub(
    env_file_text: str | None,
    *,
    shell_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the real wrapper with a stub `docker`, so no daemon is needed.

    The stub echoes the resolved arguments and the POSTGRES_PASSWORD it
    inherited. `--env-file` values are Compose's, not the wrapper's, so a
    non-empty file value must show up as `<unset>` in the child (the wrapper
    must not shadow it with the development fallback).
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        docker = bin_dir / "docker"
        docker.write_text(_STUB_DOCKER_COMPOSE_LOCAL, encoding="utf-8")
        docker.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["SOYMUTDB_LOCAL_ENV_FILE"] = "/dev/null"
        for name in (
            "SOYMUTDB_LOCAL_PROFILES",
            "COMPOSE_PROFILES",
            "POSTGRES_PASSWORD",
            "CLICKHOUSE_PASSWORD",
            "REDIS_PASSWORD",
            "MINIO_ROOT_USER",
            "MINIO_ROOT_PASSWORD",
            "GRAFANA_PASSWORD",
            "SOYMUTDB_MCP_API_TOKEN",
        ):
            env.pop(name, None)
        if env_file_text is not None:
            env_file = tmp_path / "soymutdb.env"
            env_file.write_text(env_file_text, encoding="utf-8")
            env["SOYMUTDB_LOCAL_ENV_FILE"] = str(env_file)
        if shell_env:
            env.update(shell_env)
        return subprocess.run(
            ["bash", "scripts/compose-local.sh", "config"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


def test_compose_local_treats_empty_env_file_values_as_unset() -> None:
    """`${NAME:?}` fails on an empty value, so an empty entry must fall back.

    A `.env` line `POSTGRES_PASSWORD=` satisfies neither Compose's `:?` check
    nor the apps. The wrapper has to treat it as unset and export the
    development default, while a real file value is left to Compose (not
    shadowed by that default).
    """
    empty = _run_compose_local_with_stub("POSTGRES_PASSWORD=\n")
    assert empty.returncode == 0, empty.stderr
    assert "POSTGRES_PASSWORD=soymutdb_dev_password" in empty.stdout

    for quoted in ('POSTGRES_PASSWORD=""\n', "POSTGRES_PASSWORD=''\n"):
        result = _run_compose_local_with_stub(quoted)
        assert result.returncode == 0, result.stderr
        assert "POSTGRES_PASSWORD=soymutdb_dev_password" in result.stdout, result.stdout

    real = _run_compose_local_with_stub("POSTGRES_PASSWORD=operator_pw\n")
    assert real.returncode == 0, real.stderr
    # The wrapper must not export the fallback over the file's value; Compose
    # reads the file itself.
    assert "POSTGRES_PASSWORD=<unset>" in real.stdout, real.stdout


def test_compose_local_profiles_honor_the_env_file_with_shell_precedence() -> None:
    """COMPOSE_PROFILES is a value, not a flag; the wrapper must resolve it.

    Compose reads COMPOSE_PROFILES from the selected env file, so `--profile`
    flags computed without it would start a different set than a direct
    `docker compose` run. Precedence stays SOYMUTDB_LOCAL_PROFILES > shell
    COMPOSE_PROFILES > env-file COMPOSE_PROFILES > `core`.
    """
    from_file = _run_compose_local_with_stub("COMPOSE_PROFILES=core,blast\n")
    assert from_file.returncode == 0, from_file.stderr
    assert "--profile core --profile blast" in from_file.stdout + from_file.stderr

    shell_wins = _run_compose_local_with_stub(
        "COMPOSE_PROFILES=core,blast\n",
        shell_env={"COMPOSE_PROFILES": "analyses"},
    )
    assert "--profile analyses" in shell_wins.stdout + shell_wins.stderr
    assert "--profile blast" not in shell_wins.stdout + shell_wins.stderr

    wrapper_wins = _run_compose_local_with_stub(
        "COMPOSE_PROFILES=core,blast\n",
        shell_env={"SOYMUTDB_LOCAL_PROFILES": "mcp", "COMPOSE_PROFILES": "analyses"},
    )
    assert "--profile mcp" in wrapper_wins.stdout + wrapper_wins.stderr
    assert "--profile analyses" not in wrapper_wins.stdout + wrapper_wins.stderr


# ---------------------------------------------------------------------------
# Cloud preview data layer: all four services, encoded password
# ---------------------------------------------------------------------------
_STUB_DOCKER_DATA_LAYER_OK = """#!/usr/bin/env bash
if [[ "${1:-}" == "info" ]]; then
  exit 0
fi
if [[ "${1:-}" == "compose" ]]; then
  shift
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project-directory|--env-file|-f|--profile) shift 2 ;;
      -*) shift ;;
      *) break ;;
    esac
  done
  case "${1:-}" in
    ps)
      if [[ -n "${STUB_POLL_LOG:-}" ]]; then
        echo "${@: -1}" >> "${STUB_POLL_LOG}"
      fi
      echo healthy
      exit 0
      ;;
    up|logs) exit 0 ;;
  esac
fi
exit 0
"""

_STUB_DOCKER_DATA_LAYER_UP_FAILS = """#!/usr/bin/env bash
if [[ "${1:-}" == "info" ]]; then
  exit 0
fi
if [[ "${1:-}" == "compose" ]]; then
  shift
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project-directory|--env-file|-f|--profile) shift 2 ;;
      -*) shift ;;
      *) break ;;
    esac
  done
  case "${1:-}" in
    ps)
      echo healthy
      exit 0
      ;;
    up) exit 1 ;;
    logs) exit 0 ;;
  esac
fi
exit 0
"""


def _run_data_layer(
    password: str, *, docker_body: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        docker = bin_dir / "docker"
        docker.write_text(docker_body, encoding="utf-8")
        docker.chmod(0o755)
        poll_log = tmp_path / "poll.log"
        poll_log.write_text("", encoding="utf-8")
        harness = tmp_path / "harness.sh"
        harness.write_text(
            f"set -uo pipefail\n"
            "export SOYMUTDB_DEV_MODE=full\n"
            "export SOYMUTDB_DEV_INSTALL=0\n"
            "export SOYMUTDB_DEV_DATA_LAYER=on\n"
            "export SOYMUTDB_DEV_FRONTEND=off\n"
            "export SOYMUTDB_DEV_LOG_DIR='" + str(tmp_path / "logs") + "'\n"
            "source scripts/start-cloud-dev.sh\n"
            "if data_layer_start; then rc=0; else rc=$?; fi\n"
            'echo "RC=$rc"\n'
            'echo "DATABASE_URL=${SOYMUTDB_DATABASE_URL-}"\n',
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["STUB_POLL_LOG"] = str(poll_log)
        env["POSTGRES_PASSWORD"] = password
        env.pop("SOYMUTDB_DATABASE_URL", None)
        completed = subprocess.run(
            ["bash", str(harness)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        polled = [
            line for line in poll_log.read_text(encoding="utf-8").splitlines() if line
        ]
        return completed, polled


def test_start_cloud_dev_waits_for_all_four_data_services() -> None:
    result, polled = _run_data_layer("secret", docker_body=_STUB_DOCKER_DATA_LAYER_OK)
    assert result.returncode == 0, result.stderr
    assert "RC=0" in result.stdout
    assert sorted(set(polled)) == sorted(DATA_SERVICES), polled


def test_start_cloud_dev_url_encodes_the_compose_password() -> None:
    password = "p@ss:w/rd?#[]"
    result, _ = _run_data_layer(password, docker_body=_STUB_DOCKER_DATA_LAYER_OK)
    assert result.returncode == 0, result.stderr
    assert (
        "DATABASE_URL=postgresql+asyncpg://soymutdb:"
        "p%40ss%3Aw%2Frd%3F%23%5B%5D@127.0.0.1:5432/soymutdb"
    ) in result.stdout, result.stdout + result.stderr


def test_start_cloud_dev_reports_per_service_state_and_logs_on_failure() -> None:
    result, _ = _run_data_layer(
        "secret", docker_body=_STUB_DOCKER_DATA_LAYER_UP_FAILS
    )
    assert result.returncode == 0, result.stderr
    assert "RC=1" in result.stdout
    assert "DATABASE_URL=\n" in result.stdout
    assert "per-service state follows" in result.stderr
    for service in DATA_SERVICES:
        assert f"logs for {service} (tail 40):" in result.stderr, result.stderr


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

    # The whole deploy tree is copied, so deploy/scripts keeps its canonical
    # relative path inside the release directory.
    assert 'cp -a "${PROJECT_ROOT}/deploy" "${RELEASE_DIR}/deploy"' in script
    assert '"${INSTALL_DIR}/scripts"' not in script
    assert '"${RELEASE_DIR}/scripts"' not in script


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
    golden = (ROOT / "scripts/release-contract.golden.sh").read_text(encoding="utf-8")

    shared = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")

    assert "Validate production Compose profiles (Docker-only CI gate)" in workflow
    for profile in sorted(PROFILES):
        assert f'"core,{profile}"' in shared or profile == "core"

    # The digest merge/sign contract lives in one reviewed script so the CNB
    # release path can never drift from the GitHub mirror.
    assert "scripts/release-contract.golden.sh" in workflow
    assert "docker manifest inspect --verbose" in golden
    assert "${RELEASE_OUTPUT_DIR}/oci-image-refs.txt" in golden
    assert 'digest_ref="${image%:*}@${digest}"' in golden
    assert 'docker manifest inspect "${digest_ref}"' in golden
    assert "sha256sum oci-image-refs.txt" in golden
    assert "GITHUB_STEP_SUMMARY" in golden
    assert "release-contract-sha256" in golden


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
    # The workflow passes the architecture through the environment; the shared
    # script derives every image tag from it.
    assert "SOYMUTDB_CI_ARCH: ${{ matrix.arch }}" in docker_job
    verification = (ROOT / "scripts/build-release-image.sh").read_text(encoding="utf-8")
    # Every tag is derived from SOYMUTDB_CI_ARCH through the shared image list,
    # so a platform build cannot tag an image for the other architecture.
    assert 'soymutdb-${name}:ci-${ARCH}' in verification
    image_list = (ROOT / "scripts/list-images.sh").read_text(encoding="utf-8")
    assert '"api|.|infra/docker/Dockerfile.api"' in image_list

    # CNB builds the same two native architectures with the same script.
    cnb = yaml.safe_load(_pipeline_source())
    cnb_images = [
        _plain(pipeline)
        for pipeline in cnb["main"]["push"]
        if pipeline["name"].startswith("docker-images")
    ]
    assert len(cnb_images) == 2
    for pipeline_text in cnb_images:
        assert "scripts/ci-job-steps.sh run image-build" in pipeline_text
    assert "amd64" in cnb_images[0]
    assert "arm64" in cnb_images[1]
    assert "cnb:arch:arm64" in cnb_images[1]

    # The build/runtime-smoke/scan/SBOM/export source used to live inline in the
    # workflow. It now lives in a single script that both the GitHub mirror and
    # the CNB pipeline call, preserving order and per-platform image identity.
    assert "scripts/build-release-image.sh" in docker_job

    build = verification.index("Build release images (${PLATFORM})")
    smoke = verification.index("Smoke test API runtime image (hard gate)")
    architecture = verification.index("Assert actual native image architecture (hard gate)")
    scan = verification.index('step "Trivy scan ${image_name} image (hard gate)"')
    sbom = verification.index('step "Generate ${image_name} SPDX SBOM"')
    export = verification.index("Export validated runtime images")
    assert build < smoke < architecture < scan < sbom < export


def test_ci_asserts_built_image_architecture_before_security_scan() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    docker_job = _workflow_job(workflow, "docker-build")

    assert "scripts/build-release-image.sh" in docker_job
    verification = (ROOT / "scripts/build-release-image.sh").read_text(encoding="utf-8")
    assertion = "Assert actual native image architecture (hard gate)"
    gate_start = verification.index(assertion)
    scan_start = verification.index("trivy_scan() {")
    gate = verification[gate_start:scan_start]

    # The architecture proof reads the image the shared builder tagged and, for
    # every image of the set, asserts the image's OWN architecture rather than
    # the tag it was pushed under.
    assert "docker image inspect --format '{{.Architecture}}'" in verification
    assert 'image="soymutdb-${image_name}:ci-${ARCH}"' in gate
    assert 'actual="$(image_arch "${image_name}")"' in gate
    # The loop iterates the shared image list, so an image cannot be built and
    # then left out of the architecture proof by a stale hard-coded name.
    assert 'for image_name in "${IMAGE_NAMES[@]}"; do' in gate
    assert 'test "${actual}" = "${ARCH}"' in gate
    assert (
        verification.index("Smoke test migrate-clickhouse runtime image (hard gate)")
        < gate_start
        < scan_start
        < verification.index('step "Trivy scan ${image_name} image (hard gate)"')
    )


def test_ci_merges_only_validated_platform_packages() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    publish_job = _workflow_job(workflow, "publish-images")

    golden = (ROOT / "scripts/release-contract.golden.sh").read_text(encoding="utf-8")

    assert "needs: [docker-build, kubernetes-kind]" in publish_job
    assert "pattern: validated-runtime-images-*" in publish_job
    assert "scripts/release-contract.golden.sh" in publish_job
    # The script enumerates both platforms itself, so a missing package fails
    # there rather than being silently skipped here.
    assert 'for arch in amd64 arm64' in golden
    assert "docker manifest create" in golden
    assert "docker manifest push" in golden
    assert "linux/amd64" in golden
    assert "linux/arm64" in golden
    assert "Verify merged manifest platforms" in golden
    assert "docker build" not in publish_job
    assert "docker build" not in golden


def test_ci_checksums_all_platform_package_metadata_before_upload() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    docker_job = _workflow_job(workflow, "docker-build")
    verification = (ROOT / "scripts/build-release-image.sh").read_text(encoding="utf-8")
    export_step = verification[verification.index("Export validated runtime images") :]
    checksum_command = export_step[export_step.index("sha256sum") :]

    assert "validated-runtime-images-${ARCH}.txt" in export_step
    assert "platform.txt" in checksum_command
    assert "sbom-" in checksum_command
    assert "SHA256SUMS" in checksum_command
    golden = (ROOT / "scripts/release-contract.golden.sh").read_text(encoding="utf-8")
    assert "sha256sum -c SHA256SUMS" in golden


def test_release_signing_is_keyless_and_job_scoped() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    docker_job = _workflow_job(workflow, "docker-build")
    publish_job = _workflow_job(workflow, "publish-images")
    golden = (ROOT / "scripts/release-contract.golden.sh").read_text(encoding="utf-8")

    # The verifier never holds a signing identity.
    assert "id-token: write" not in docker_job

    # Signing is keyless: it happens through a Sigstore identity token minted by
    # the publishing pipeline, and the cosign installer is SHA-pinned there.
    installer = re.search(
        r"cosign-installer@(?P<revision>\S+)",
        publish_job,
    )
    assert installer is not None, "the GitHub publish job must pin cosign-installer"
    assert re.fullmatch(r"[0-9a-f]{40}", installer.group("revision"))

    # The CNB release pipeline does not inline a cosign installer: it delegates
    # to the golden script, which installs cosign itself and verifies the
    # download against the published checksums before executing it. That is
    # strictly stronger than trusting a floating action tag, but only if the
    # checksum verification actually happens — so assert it.
    release_pipeline = yaml.safe_load(
        (ROOT / ".cnb/pipelines/release.yml").read_text(encoding="utf-8")
    )
    release_scripts = [
        stage["script"]
        for stage in release_pipeline["stages"]
        if "script" in stage
    ]
    joined = "\n".join(release_scripts)
    # Assert on executable stage bodies, not comments: a `cosign` mention in the
    # explanatory header is fine, an inlined installer is not.
    assert "cosign" not in joined, (
        "the CNB release pipeline must not inline cosign; "
        "scripts/release-contract.golden.sh owns the signing toolchain"
    )
    assert "release-contract.golden.sh" in joined
    assert "sha256sum -c" in golden or "cosign_checksums" in golden
    for command in (
        "cosign sign --yes",
        "cosign attest --yes --type slsaprovenance",
        "cosign attest --yes --type spdxjson",
        "cosign verify",
        "cosign verify-attestation",
    ):
        assert command in golden
    # CNB mints the OIDC token locally and publishes the same contract.
    cnb_release = (ROOT / ".cnb/pipelines/release.yml").read_text(encoding="utf-8")
    assert "sigstore" in cnb_release.lower()
    assert "scripts/release-contract.golden.sh" in cnb_release
    assert "token.actions.githubusercontent.com" in golden


def test_release_contract_carries_sbom_provenance_and_source_identity() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    docker_job = _workflow_job(workflow, "docker-build")
    publish_job = _workflow_job(workflow, "publish-images")
    golden = (ROOT / "scripts/release-contract.golden.sh").read_text(encoding="utf-8")
    cnb_release = (ROOT / ".cnb/pipelines/release.yml").read_text(encoding="utf-8")

    assert "scripts/build-release-image.sh" in docker_job
    verification = (ROOT / "scripts/build-release-image.sh").read_text(encoding="utf-8")
    assert verification.count("--format spdx-json") == 2
    # One SBOM step, one loop. The per-image names come from the shared list, and
    # the provenance files are generated from the same list in the publisher, so
    # "add an image" cannot leave the SBOMs and the manifest out of step.
    assert verification.count('step "Generate ${image_name} SPDX SBOM"') == 1
    assert 'sbom-${image_name}-${ARCH}.spdx.json' in verification
    assert 'expected_provenance+=("${RELEASE_OUTPUT_DIR}/provenance-${image_name}.json")' in golden
    image_list = (ROOT / "scripts/list-images.sh").read_text(encoding="utf-8")
    for image_name in ("api", "worker", "mcp", "jbrowse", "migrate", "migrate-clickhouse"):
        assert f'"{image_name}|' in image_list, image_name
    assert "release-manifest.json" in golden
    assert "schema_version" in golden
    # Source identity comes from the pipeline's own revision and repository
    # variables, so the contract is portable between GitHub and CNB.
    assert "SOURCE_REPOSITORY" in golden
    assert "SOURCE_REVISION" in golden
    assert "provenance_sha256" in golden
    assert "release-manifest.sigstore.json" in golden
    assert "sha256sum release-manifest.json" in golden
    assert "Upload signed OCI release contract" in publish_job
    assert "scripts/release-contract.golden.sh" in cnb_release
    assert "oci-release-contract" in cnb_release


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
    assert f"pnpm {PNPM_VERSION}" in adr
    assert "Ant Design 6" in adr
    assert "image@sha256" in adr
    assert "core,jbrowse,blast,analyses,mcp,cloudflare-tunnel" in adr
    assert "Docker acceptance runs in CI" in adr
    assert "Rollback" in adr


# ---------------------------------------------------------------------------
# deploy/scripts/upgrade.sh — the compose invocation contract
# ---------------------------------------------------------------------------
# `docker compose` interpolates the WHOLE compose file when the command line is
# parsed, so anything the file declares as required (`${NAME:?message}`) must
# already be in the environment of the process that runs compose. Two ordering
# mistakes are easy to make and both were present, which is why they are pinned
# here instead of left to a reviewer's memory.
def _upgrade_source() -> str:
    return UPGRADE.read_text(encoding="utf-8")


def _compose_variable_names(compose: dict) -> set[str]:
    """Every `${NAME:?…}` reference in the production Compose file.

    Compose demands these during interpolation, i.e. before it selects a
    service. They are the exact set `upgrade.sh` must have exported by the time
    its first `docker compose` call runs.
    """
    text = json.dumps(compose, ensure_ascii=False)
    return set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*):\?", text))


def test_upgrade_loads_env_before_the_first_compose_command() -> None:
    """`.env` must be sourced before the COMPOSE array is built and used.

    Regression the ordering produces. `docker compose config -q` is step 1 of
    the release, and it interpolates `docker-compose.yml`, which deliberately
    fails closed on `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}` and
    friends. With the array constructed first, that first validation died with

        error while interpolating services.postgres.environment.POSTGRES_PASSWORD:
        required variable POSTGRES_PASSWORD is missing a value

    and the operator saw "compose config failed" instead of "missing .env" --
    pointing at a compose file that was fine.

    Three properties are asserted, in the order bash evaluates them:
      1. `.env` is sourced before the COMPOSE array is assigned;
      2. no compose invocation precedes either;
      3. the array carries `--env-file`, so compose and the script read the same
         file regardless of the caller's cwd or already-exported variables.
    """
    source = _upgrade_source()

    source_env = source.index('if [[ -f "${COMPOSE_DIR}/.env" ]]')
    build_array = source.index("COMPOSE=(docker compose")

    assert source_env < build_array, (
        "upgrade.sh must source .env before building the COMPOSE array; "
        "compose interpolates ${NAME:?…} while parsing the command line"
    )
    # The FIRST use of the array is inside the helper functions above the .env
    # load, so anchor the ordering on the first *statement that runs* the array
    # at the top level -- a call site, not a function body. Anchoring on
    # `"${COMPOSE[@]}"` alone would compare against a definition that has not
    # executed yet and would fail on a correct file.
    first_invocation = source.index('"${COMPOSE[@]}"', build_array)
    assert build_array < first_invocation, (
        "the COMPOSE array must be constructed before it is used"
    )

    array_line = source[build_array : source.index("\n", build_array)]
    assert "--env-file" in array_line, (
        "the COMPOSE array must pass --env-file so compose and the script read "
        f"the same .env: {array_line}"
    )

    # And the variables the file requires are exactly the ones .env provides for.
    required = _compose_variable_names(_compose())
    assert required, "docker-compose.yml must keep its fail-fast references"
    env_example = (ROOT / "deploy/.env.example").read_text(encoding="utf-8")
    for name in sorted(required):
        assert f"{name}=" in env_example, (
            f"{name} is required by docker-compose.yml but missing from "
            "deploy/.env.example; a fresh install would have nothing to fill in"
        )


def test_upgrade_rollback_survives_a_stale_or_incomplete_environment() -> None:
    """Rolling back must swap images, not re-demand the caller's environment.

    `rollback()` re-runs `docker compose up -d` to bring the previous release
    back. It passed only the four `*_IMAGE_REF` variables, which is enough when
    the caller happens to still hold every other `${NAME:?…}` -- and the failure
    when it does not is

        required variable POSTGRES_PASSWORD is missing a value

    during a rollback, i.e. an error message that names neither the rollback nor
    the real cause. The data-layer credentials are therefore re-exported
    explicitly, while the *application* configuration (`SOYMUTDB_*`) is
    deliberately left to the current environment: a rollback restores the code,
    it does not reintroduce last release's secrets.
    """
    source = _upgrade_source()
    rollback = source[source.index("rollback() {") : source.index("# Step 7:")]

    for name in (
        "POSTGRES_PASSWORD",
        "CLICKHOUSE_PASSWORD",
        "REDIS_PASSWORD",
        "GRAFANA_PASSWORD",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
    ):
        assert name in rollback, (
            f"rollback() must re-export {name}; compose interpolates it before "
            "selecting a service, and its absence aborts the rollback"
        )

    # Every required variable is either re-exported or deliberately an
    # application setting that must NOT be rolled back. Anything else means a
    # new required reference can be added to compose without rollback noticing.
    application_prefixes = ("SOYMUTDB_",)
    reexported = set(re.findall(r"^\s*([A-Z_]+)=\"", rollback, re.MULTILINE))
    uncovered = {
        name
        for name in _compose_variable_names(_compose())
        if name not in reexported and not name.startswith(application_prefixes)
    }
    assert not uncovered, (
        "these required compose variables are neither re-exported by rollback() "
        f"nor intentionally application-scoped: {sorted(uncovered)}"
    )

    # The image swap itself must stay: an in-place restart is not a rollback.
    # Each recorded ref has to appear on both sides -- read from the state file
    # and assigned onto the compose invocation.
    for recorded, applied in (
        ("OLD_API_REF", "API_IMAGE_REF"),
        ("OLD_WORKER_REF", "WORKER_IMAGE_REF"),
        ("OLD_MCP_REF", "MCP_IMAGE_REF"),
        ("OLD_JBROWSE_REF", "JBROWSE_IMAGE_REF"),
    ):
        assert f"{applied}=\"${{{recorded}}}\"" in rollback, (
            f"rollback() must run compose with {applied} set to the recorded "
            f"{recorded}; a restart on the new images is not a rollback"
        )
