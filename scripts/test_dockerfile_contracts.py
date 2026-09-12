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

import re
import subprocess
import sys
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
        service = services[service_name]
        assert isinstance(service.get("build"), dict), (
            f"{service_name} has no local build definition; the production "
            "topology could then only run from a registry"
        )
        assert service["build"].get("dockerfile"), service_name
        assert local_tag.split(":", 1)[0] in local_tag

    base_text = COMPOSE.read_text(encoding="utf-8")
    for variable in (
        "API_IMAGE",
        "WORKER_IMAGE",
        "MCP_IMAGE",
        "MIGRATE_IMAGE",
        "MIGRATE_CLICKHOUSE_IMAGE",
    ):
        assert f"${{{variable}:-" in base_text, variable

    # The wrappers exist and are wired to the same list.
    for script in ("scripts/compose-local.sh", "scripts/list-images.sh"):
        assert (ROOT / script).is_file(), script
    compose_local = (ROOT / "scripts/compose-local.sh").read_text(encoding="utf-8")
    assert "soymutdb_image_entry" in compose_local
    assert "docker-compose.yml" in compose_local


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
