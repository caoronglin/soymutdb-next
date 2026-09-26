"""Static contracts for the release images and the shared image list.

Every release image is described once, in scripts/list-images.sh, and consumed by
the verify pipeline, the publisher, the COPY guard and the Compose topology. A
mistake in that list is expensive and quiet: a Dockerfile that is built but not
exported, an image that is scanned but never published, or — the case that
motivated these tests — a *migration* image that is published but that nobody
verifies runs the migration.

These checks need no Docker daemon: they read the Dockerfiles and the list.
"""

from __future__ import annotations

import gzip
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE_LIST = ROOT / "scripts/list-images.sh"
BUILD_RELEASE_IMAGE = ROOT / "scripts/build-release-image.sh"
GOLDEN = ROOT / "scripts/release-contract.golden.sh"
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / "deploy/.env.example"

sys.path.insert(0, str(ROOT / "scripts"))
from compose_loader import load_compose  # noqa: E402


def _image_entries() -> list[tuple[str, str, str]]:
    """`name|context|dockerfile` triples, resolved by the list script itself.

    The list is shell, not data, and it already has consumers that resolve it
    that way (`source scripts/list-images.sh; soymutdb_image_entry`). Reading it
    with the same shell function means this suite fails for the same reason the
    pipeline would, instead of re-implementing the parsing and agreeing with
    itself.
    """
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; soymutdb_image_entry',
            "bash",
            str(IMAGE_LIST),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    entries = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        assert len(parts) == 3, line
        entries.append((parts[0], parts[1], parts[2]))
    return entries


def test_image_list_entries_point_at_committed_dockerfiles() -> None:
    entries = _image_entries()

    assert entries, "scripts/list-images.sh declares no images"

    names = [name for name, _, _ in entries]
    assert len(names) == len(set(names)), f"duplicate image names: {names}"

    for name, context, dockerfile in entries:
        assert re.fullmatch(r"[a-z][a-z0-9-]*", name), name
        path = ROOT / dockerfile
        assert path.is_file(), f"{name}: missing Dockerfile {dockerfile}"
        # `git check-ignore` rather than `exists()`: `.gitignore` once had an
        # unanchored pattern that hid `.cnb/env/` from every checkout while the
        # files sat in the working tree and every test still passed.
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", dockerfile],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert ignored.returncode != 0, f"{dockerfile} is ignored by .gitignore"
        tracked = subprocess.run(
            ["git", "ls-files", "--cached", "--error-unmatch", dockerfile],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert tracked.returncode == 0, f"{dockerfile} is not tracked by git"
        # The build context must exist and must contain the Dockerfile's dir.
        assert (ROOT / context).is_dir(), f"{name}: missing build context {context}"


def test_every_image_has_an_architecture_proof_a_smoke_gate_and_a_scan() -> None:
    entries = _image_entries()
    verification = BUILD_RELEASE_IMAGE.read_text(encoding="utf-8")

    # The three phases all iterate the shared list, so this is a statement that
    # nothing bypasses them, not a per-image enumeration that could drift.
    assert 'source "${REPO_ROOT}/scripts/list-images.sh"' in verification
    assert "done < <(soymutdb_image_entry)" in verification
    assert 'for image_name in "${IMAGE_NAMES[@]}"; do' in verification
    assert verification.count('trivy_scan "soymutdb-${image_name}:ci-${ARCH}"') == 1
    assert verification.count('trivy_sbom "soymutdb-${image_name}:ci-${ARCH}"') == 1
    assert 'validated_images+=("soymutdb-${image_name}:ci-${ARCH}")' in verification

    # A smoke gate is the one phase that is NOT a loop: each image asserts
    # something different (an import, a task registry, `nginx -t`, `alembic
    # heads`). Require one per image, or an image could be built, scanned and
    # exported without anything ever having started it.
    for name, _, _ in entries:
        tag = f'"soymutdb-{name}:ci-${{ARCH}}"'
        assert tag in verification, (
            f"{name} has no smoke gate in scripts/build-release-image.sh: the image "
            "would be built and exported without ever being started"
        )


def test_migration_images_are_smoked_on_what_an_upgrade_actually_runs() -> None:
    """`alembic heads` and the ClickHouse payload, not just "the container starts"."""
    verification = BUILD_RELEASE_IMAGE.read_text(encoding="utf-8")

    migrate = verification[verification.index("Smoke test migrate runtime image") :]
    assert "alembic heads" in migrate, (
        "the migrate image must resolve its migration graph offline; a missing "
        "migrations directory is exactly the failure this gate exists to catch"
    )

    clickhouse = verification[verification.index("Smoke test migrate-clickhouse") :]
    for payload in (
        "/opt/soymutdb/migrate_clickhouse_lib.py",
        "/opt/soymutdb/upgrade_variant_facts_schema.sql",
        "/opt/soymutdb/migrate-clickhouse.sh",
    ):
        assert payload in clickhouse, payload


def _instructions(text: str) -> str:
    """A Dockerfile with its comment lines removed.

    Every one of these Dockerfiles explains what it deliberately does NOT
    install, so a naive substring scan matches the explanation. Assertions about
    instructions must read instructions.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_migrate_dockerfile_keeps_the_alembic_contract() -> None:
    text = _instructions(
        (ROOT / "infra/docker/Dockerfile.migrate").read_text(encoding="utf-8")
    )

    # apps/api depends on `soymutdb-jobs` by path, so the sync cannot resolve
    # without the package in the build context, and a COPY after the sync would
    # let the venv disagree with the lockfile.
    copy_position = text.index("COPY packages/jobs-py ./packages/jobs-py")
    sync_position = text.index("uv sync --frozen")
    assert copy_position < sync_position, (
        "apps/api depends on `soymutdb-jobs` by path, so the sync cannot resolve "
        "the lockfile unless the package is already in the build context"
    )

    # No COPY may follow the sync in the BUILDER stage. A COPY into the runtime
    # stage is fine (it copies the finished venv, not sources) — and the
    # distinction matters, because the rule the check enforces is "the venv was
    # installed from the tree that is shipped", not "this file contains one COPY".
    builder = text[: text.index("FROM python:3.14.6-slim AS runtime")]
    after_sync = builder[sync_position:]
    # The sources themselves are the ONE allowed late copy: the venv was built
    # with `--no-install-project`, so the project's own code has to arrive
    # afterwards. What must not appear is a copy of a file that declares
    # dependencies (a manifest or a lockfile), because that would install a set
    # the sync above never saw.
    for forbidden in ("COPY apps/api/pyproject.toml", "COPY apps/api/uv.lock",
                      "COPY packages/jobs-py"):
        assert forbidden not in after_sync, (
            f"{forbidden} after `uv sync --frozen` in the builder: the venv was "
            "installed from a different dependency set than the image ships"
        )
    assert "COPY apps/api ./apps/api" in after_sync

    # WORKDIR is load-bearing: alembic.ini resolves `script_location =
    # migrations` and env.py imports `app.*` relatively, so the Compose command
    # (`alembic upgrade head`) only works from here.
    assert "WORKDIR /app/apps/api" in text
    assert "HEALTHCHECK" not in text, (
        "a one-shot migration job has no meaningful health state; the platform "
        "waits for service_completed_successfully"
    )


def test_migrate_clickhouse_dockerfile_is_not_a_second_worker() -> None:
    text = _instructions(
        (ROOT / "infra/docker/Dockerfile.migrate-clickhouse").read_text(
            encoding="utf-8"
        )
    )
    assert "FROM python:3.14.6-slim" in text

    for heavy in (
        "ncbi-blast+",
        "samtools",
        "bcftools",
        "bedtools",
        "scanpy",
        "leidenalg",
        "celery",
    ):
        assert heavy not in text, (
            f"{heavy} in the ClickHouse migrator puts the worker runtime back "
            "behind a script that only needs clickhouse-connect"
        )

    # The same paths the worker image uses, because the script and the SQL are
    # shared verbatim rather than forked per image.
    for destination in (
        "/opt/soymutdb/migrate-clickhouse.sh",
        "/opt/soymutdb/migrate_clickhouse_lib.py",
        "/opt/soymutdb/upgrade_variant_facts_schema.sql",
    ):
        assert destination in text, destination

    # `migrate-clickhouse.sh` defaults to `${ROOT}/../venv/bin/python`; the
    # virtualenv is built here so the Compose service needs no per-image
    # `CLICKHOUSE_MIGRATION_PYTHON` override.
    assert "CLICKHOUSE_MIGRATION_ROOT=/opt/soymutdb" in text
    assert "/opt/venv" in text


def test_images_copy_every_workspace_path_dependency_before_sync() -> None:
    """A workspace path dependency must exist before `uv sync --frozen`.

    `apps/api` and `apps/worker` resolve `soymutdb-jobs` and
    `soymutdb-import-protocol` from the workspace by path. A Dockerfile that
    copies only some of them fails the sync with:

        error: Failed to determine installation plan
          Caused by: Distribution not found at: file:///app/packages/<name>

    which is how the image build broke after `import-protocol` was added to the
    API/worker dependencies but never to the Docker build context.
    """
    pairs = (
        (
            "apps/api/uv.lock",
            ("infra/docker/Dockerfile.api", "infra/docker/Dockerfile.migrate"),
        ),
        ("apps/worker/uv.lock", ("infra/docker/Dockerfile.worker",)),
    )
    for lock_path, dockerfiles in pairs:
        lock = (ROOT / lock_path).read_text(encoding="utf-8")
        packages = sorted(
            set(re.findall(r'directory = "(?:\.\./)+packages/([a-z0-9-]+)"', lock))
        )
        assert packages, f"{lock_path} declares no workspace path dependencies"
        for dockerfile in dockerfiles:
            text = _instructions((ROOT / dockerfile).read_text(encoding="utf-8"))
            sync = text.index("uv sync --frozen")
            for name in packages:
                needle = f"COPY packages/{name} ./packages/{name}"
                assert needle in text, (
                    f"{dockerfile} does not COPY packages/{name}; `uv sync --frozen` "
                    "cannot resolve the lockfile without it"
                )
                assert text.index(needle) < sync, (
                    f"{dockerfile} COPYs packages/{name} after `uv sync --frozen`; "
                    "the venv would be built without it"
                )


def test_static_app_images_supply_their_build_time_origins() -> None:
    """The web/admin/jbrowse builds fail closed without their origins.

    The vite configs and the JBrowse `_headers` injector require
    `VITE_API_BASE_URL` (and the CSP/frame origins) at build time. A Dockerfile
    that runs the build without them fails with:

        Error: [jbrowse-headers] VITE_API_BASE_URL is required …

    which is how the image build broke once the earlier compose and COPY
    failures were cleared.
    """
    required = {
        "infra/docker/Dockerfile.web": ("VITE_API_BASE_URL", "VITE_JBROWSE_BASE_URL"),
        "infra/docker/Dockerfile.admin": ("VITE_API_BASE_URL",),
        "apps/jbrowse/Dockerfile": (
            "VITE_API_BASE_URL",
            "VITE_JBROWSE_DATA_URL",
            "SOYMUTDB_PORTAL_ORIGIN",
            "SOYMUTDB_ADMIN_ORIGIN",
        ),
    }
    for dockerfile, variables in required.items():
        text = _instructions((ROOT / dockerfile).read_text(encoding="utf-8"))
        build = text.index("pnpm --filter @soymutdb/")
        for variable in variables:
            assert variable in text, f"{dockerfile} never sets {variable}"
            assert text.index(variable) < build, (
                f"{dockerfile} only references {variable} after the app build; the "
                "build would fail closed without it"
            )


def test_runtime_smoke_provides_production_grade_settings() -> None:
    """The API/migrate smoke boots the app under production settings.

    `Settings` rejects the development default for `analytics_ip_salt` and
    requires at least 32 characters, so a smoke run without it fails before the
    app imports:

        ValidationError: analytics_ip_salt must not use the development default
    """
    text = (ROOT / "scripts/build-release-image.sh").read_text(encoding="utf-8")
    assert "Smoke test API runtime image" in text
    salts = re.findall(r"-e SOYMUTDB_ANALYTICS_IP_SALT=(\S+)", text)
    assert salts, "no smoke run provides SOYMUTDB_ANALYTICS_IP_SALT"
    for salt in salts:
        assert len(salt) >= 32, (
            f"analytics salt {salt!r} is shorter than the 32-character floor the "
            "settings validator enforces"
        )


def test_local_build_override_discards_the_release_image_requirement() -> None:
    compose = load_compose(COMPOSE)
    services = compose["services"]

    local_buildable = {
        "api": "soymutdb-api:local",
        "worker-default": "soymutdb-worker:local",
        "worker-blast": "soymutdb-worker:local",
        "worker-ingest": "soymutdb-worker:local",
        "worker-analyses": "soymutdb-worker:local",
        "beat": "soymutdb-worker:local",
        "mcp-server": "soymutdb-mcp:local",
        "migrate": "soymutdb-migrate:local",
        "migrate-clickhouse": "soymutdb-migrate-clickhouse:local",
    }
    for service_name, local_tag in local_buildable.items():
        # Release services reference signed digests and declare no build, so a
        # production host can never build from a checkout.
        assert "build" not in services[service_name], (
            f"{service_name} must not carry a Compose build definition; the "
            "local wrapper builds with `docker build` instead"
        )
        assert local_tag.split(":", 1)[0] in local_tag

    # Local image selection belongs to the explicit post-merge override. The
    # production file must remain release-only and fail closed.
    local_override = (ROOT / "docker-compose.local.yml").read_text(encoding="utf-8")
    local_services = load_compose(ROOT / "docker-compose.local.yml")["services"]
    for service_name, service in local_services.items():
        assert "build" not in service, service_name
    assert "!reset" not in local_override
    for variable in (
        "API_IMAGE",
        "WORKER_IMAGE",
        "MCP_IMAGE",
        "MIGRATE_IMAGE",
        "MIGRATE_CLICKHOUSE_IMAGE",
    ):
        assert f"${{{variable}:-" in local_override, variable

    # The wrappers exist and are wired to the same list. Local builds are direct
    # `docker build` invocations sourced from scripts/list-images.sh.
    for script in ("scripts/compose-local.sh", "scripts/list-images.sh"):
        assert (ROOT / script).is_file(), script
    compose_local = (ROOT / "scripts/compose-local.sh").read_text(encoding="utf-8")
    assert "soymutdb_image_entry" in compose_local
    assert "docker build" in compose_local
    assert "docker-compose.yml" in compose_local
    assert "docker-compose.local.yml" in compose_local


def test_compose_migration_services_use_their_own_digest_references() -> None:
    services = load_compose(COMPOSE)["services"]
    env = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            env[name] = value

    references = {
        "migrate": "MIGRATE_IMAGE_REF",
        "migrate-clickhouse": "MIGRATE_CLICKHOUSE_IMAGE_REF",
    }
    for service_name, variable in references.items():
        image = services[service_name]["image"]
        assert image.startswith(f"${{{variable}:?"), (service_name, image)
        assert "image@sha256" in image
        assert re.fullmatch(
            r"ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}",
            env[variable],
        ), (variable, env[variable])

    # Neither migration service may borrow another service's reference: that is
    # the coupling that let an upgrade run the previous release's migrations.
    api_reference = services["api"]["image"]
    worker_reference = services["worker-default"]["image"]
    for service_name in references:
        assert services[service_name]["image"] not in (api_reference, worker_reference)
    assert "CLICKHOUSE_MIGRATION_PYTHON" not in services["migrate-clickhouse"].get(
        "environment", {}
    ), "the migrator image provides the interpreter at the script's default path"


def test_publisher_and_verifier_agree_on_the_image_set() -> None:
    entries = _image_entries()
    names = {name for name, _, _ in entries}
    golden = GOLDEN.read_text(encoding="utf-8")

    assert 'source "${REPO_ROOT}/scripts/list-images.sh"' in golden
    assert "RUNTIME_IMAGES=()" in golden
    assert 'RUNTIME_IMAGES+=("${image_name}")' in golden
    # The manifest validator compares the FULL name list against the value
    # generated from the same source, so a package that carries an extra image
    # (a leftover tar from an image that was removed) fails instead of being
    # loaded and then silently skipped at push time.
    assert 'expected_image_names_json="$(printf' in golden
    assert "(.images | length == ($expected | length))" in golden
    assert "([.images[].name] | sort) == $expected" in golden
    assert "diff <(printf" in golden

    # Every image the verify pipeline builds must be one the publisher knows,
    # and vice versa — one list, two consumers.
    assert names
    assert "soymutdb_remote_image_name" in golden


def test_compose_loader_understands_platform_tags() -> None:
    """Both Compose-only tags must survive a plain `yaml.safe_load` replacement."""
    loader = (ROOT / "scripts" / "compose_loader.py").read_text(encoding="utf-8")
    assert "!reset" in loader
    assert "!override" in loader

    # The four suites that parse the production topology use it, rather than
    # each keeping a private copy of the constructor (the copies had already
    # drifted: one knew `!reset`, the other did not).
    for relative in (
        "scripts/test_development_compose_contract.py",
        "scripts/test_platform_delivery_contracts.py",
        "scripts/test_production_compose_contract.py",
        "scripts/test_dockerfile_contracts.py",
        "scripts/dependency_governance.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "compose_loader import" in text, relative


def test_precompress_refreshes_stale_archives(tmp_path: Path) -> None:
    """`precompress.sh` must refresh a stale .gz and stay safe to re-run.

    `gzip -k` refuses to overwrite an existing .gz ("already exists; not
    overwritten") and leaves the OLD body in place, so a changed source kept its
    previous compressed payload — which nginx gzip_static then served. Fonts are
    the case that matters most, because .woff/.woff2/.ttf are compressed only
    here, never by the build chain.

    Note on severity: this is a staleness bug, not a build breaker. The script
    uses `-exec … \;`, and only `-exec … +` propagates a command failure, so a
    refusal here could not abort an image build. An earlier revision of this
    plan claimed otherwise; the probe that "proved" it had used `+`.

    No Docker daemon is needed: the script is plain POSIX sh.
    """
    script = ROOT / "infra" / "docker" / "precompress.sh"
    assert script.is_file()

    payload = b"console.log('x');\n" * 200
    source = tmp_path / "app.js"
    archive = tmp_path / "app.js.gz"
    source.write_bytes(payload)

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(script), str(tmp_path)],
            capture_output=True,
            text=True,
            check=False,
        )

    first = run()
    assert first.returncode == 0, first.stderr
    assert archive.is_file()
    assert gzip.decompress(archive.read_bytes()) == payload

    # Re-running on an up-to-date tree must be a no-op, not a warning storm.
    second = run()
    assert second.returncode == 0, second.stderr
    assert gzip.decompress(archive.read_bytes()) == payload

    # The regression: a .gz older than its source must be replaced, not left
    # stale (`gzip -k` alone would keep the old body and print a warning).
    os.utime(archive, (1_000_000, 1_000_000))
    updated = payload + b"// changed\n"
    source.write_bytes(updated)
    now = time.time()
    os.utime(source, (now, now))

    third = run()
    assert third.returncode == 0, third.stderr
    assert gzip.decompress(archive.read_bytes()) == updated
