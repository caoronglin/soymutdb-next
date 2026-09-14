"""Focused regression tests for scripts/compose-local.sh env-file semantics.

The production Compose file is release-only: every service image and credential
is a fail-closed ``${NAME:?…}`` reference. ``scripts/compose-local.sh`` supplies
safe local fallbacks for the names that are neither set in the shell nor given a
*non-empty* value by the selected ``--env-file``, because Compose treats an empty
``NAME=`` exactly like an unset one.

These tests drive the real wrapper with a fake ``docker`` on ``PATH`` and inspect
the argv and environment it passes, so they pin the resolution order without
needing a Docker daemon or any real secret:

* an empty env-file value is not a satisfied required variable;
* a non-empty env-file value is left for Compose (never exported, never logged);
* the shell environment wins over the env-file;
* COMPOSE_PROFILES resolves as SOYMUTDB_LOCAL_PROFILES > shell > env-file > core.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_LOCAL = ROOT / "scripts/compose-local.sh"

# Names the wrapper may export or read. The test environment is scrubbed of them
# so a developer's shell cannot decide the outcome of a case.
_MANAGED = frozenset(
    {
        "API_IMAGE",
        "WORKER_IMAGE",
        "MCP_IMAGE",
        "MIGRATE_IMAGE",
        "MIGRATE_CLICKHOUSE_IMAGE",
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
        "COMPOSE_PROFILES",
        "SOYMUTDB_LOCAL_ENV_FILE",
        "SOYMUTDB_LOCAL_IMAGE_TAG",
        "SOYMUTDB_LOCAL_PROFILES",
        "SOYMUTDB_CI_DOCKER_BUILD_EXTRA_ARGS",
    }
)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\nset -eu\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _run_wrapper(
    tmp_path: Path,
    env_text: str,
    *,
    extra_env: dict[str, str] | None = None,
    args: tuple[str, ...] = ("config",),
) -> tuple[subprocess.CompletedProcess[str], list[str], dict[str, str]]:
    """Run the wrapper against a fixture env file through a fake docker.

    Returns the completed process, the fake docker argv, and the environment the
    wrapper handed to docker.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_path = tmp_path / "docker.argv"
    captured_env_path = tmp_path / "docker.env"
    _write_executable(
        bin_dir / "docker",
        "\n".join(
            (
                'printf \'%s\\n\' "$@" > "$FAKE_DOCKER_ARGV"',
                'env > "$FAKE_DOCKER_ENV"',
            )
        ),
    )

    compose_env = tmp_path / "soymutdb.env"
    compose_env.write_text(env_text, encoding="utf-8")

    env = {name: value for name, value in os.environ.items() if name not in _MANAGED}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["SOYMUTDB_LOCAL_ENV_FILE"] = str(compose_env)
    env["FAKE_DOCKER_ARGV"] = str(argv_path)
    env["FAKE_DOCKER_ENV"] = str(captured_env_path)
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(
        ["bash", str(COMPOSE_LOCAL), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"wrapper failed:\n{result.stderr}"

    argv = argv_path.read_text(encoding="utf-8").splitlines()
    captured = {}
    for line in captured_env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            name, value = line.split("=", 1)
            captured[name] = value
    return result, argv, captured


def _profile_flags(argv: list[str]) -> list[str]:
    return [
        argv[index + 1]
        for index, token in enumerate(argv)
        if token == "--profile" and index + 1 < len(argv)
    ]


# ---------------------------------------------------------------------------
# Empty env-file values must not satisfy a production `${NAME:?…}` reference.
# ---------------------------------------------------------------------------
def test_empty_env_file_value_falls_back_to_development_default(tmp_path: Path) -> None:
    _result, _argv, captured = _run_wrapper(
        tmp_path,
        "# an unset credential\nPOSTGRES_PASSWORD=\nCLICKHOUSE_PASSWORD=   # empty\n",
    )
    assert captured["POSTGRES_PASSWORD"] == "soymutdb_dev_password"
    assert captured["CLICKHOUSE_PASSWORD"] == "soymutdb_dev_password"


def test_quoted_empty_env_file_value_falls_back(tmp_path: Path) -> None:
    _result, _argv, captured = _run_wrapper(
        tmp_path,
        "POSTGRES_PASSWORD=\"\"\nREDIS_PASSWORD=''\n",
    )
    assert captured["POSTGRES_PASSWORD"] == "soymutdb_dev_password"
    assert captured["REDIS_PASSWORD"] == "soymutdb_dev_password"


def test_empty_image_ref_falls_back_to_local_tag(tmp_path: Path) -> None:
    _result, _argv, captured = _run_wrapper(tmp_path, "API_IMAGE_REF=\n")
    assert captured["API_IMAGE_REF"] == "soymutdb-api:local"


# ---------------------------------------------------------------------------
# Non-empty env-file values are authoritative and must stay out of logs/env.
# ---------------------------------------------------------------------------
def test_non_empty_env_file_value_is_left_to_compose(tmp_path: Path) -> None:
    secret = "file-only-postgres-secret"
    result, _argv, captured = _run_wrapper(tmp_path, f"POSTGRES_PASSWORD={secret}\n")
    # The wrapper must not export an env-file value; Compose reads it from
    # --env-file. A leaked value would show up in docker's environment.
    assert "POSTGRES_PASSWORD" not in captured
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_non_empty_image_ref_is_left_to_compose(tmp_path: Path) -> None:
    reference = f"ghcr.io/example/api@sha256:{'1' * 64}"
    _result, _argv, captured = _run_wrapper(tmp_path, f"API_IMAGE_REF={reference}\n")
    assert "API_IMAGE_REF" not in captured


# ---------------------------------------------------------------------------
# Shell environment wins over the env-file, without leaking the file value.
# ---------------------------------------------------------------------------
def test_shell_value_wins_over_env_file_value(tmp_path: Path) -> None:
    file_secret = "file-postgres-secret"
    shell_secret = "shell-postgres-secret"
    result, _argv, captured = _run_wrapper(
        tmp_path,
        f"POSTGRES_PASSWORD={file_secret}\n",
        extra_env={"POSTGRES_PASSWORD": shell_secret},
    )
    assert captured["POSTGRES_PASSWORD"] == shell_secret
    assert file_secret not in result.stdout
    assert file_secret not in result.stderr
    # Neither the shell secret nor the file secret may be echoed in the log.
    assert shell_secret not in result.stdout
    assert shell_secret not in result.stderr


def test_empty_shell_value_does_not_mask_env_file_value(tmp_path: Path) -> None:
    """An empty shell entry must not satisfy a required variable either.

    Compose gives the shell precedence, so `POSTGRES_PASSWORD=` would win over
    the env file's value and fail `${POSTGRES_PASSWORD:?…}`. The wrapper drops
    the empty shell entry (without copying the file's value into its own
    environment) so Compose reads the usable value from `--env-file`.
    """
    file_secret = "file-only-postgres-secret"
    result, _argv, captured = _run_wrapper(
        tmp_path,
        f"POSTGRES_PASSWORD={file_secret}\n",
        extra_env={"POSTGRES_PASSWORD": ""},
    )
    assert "POSTGRES_PASSWORD" not in captured
    assert file_secret not in result.stdout
    assert file_secret not in result.stderr


def test_empty_shell_and_empty_env_file_fall_back(tmp_path: Path) -> None:
    _result, _argv, captured = _run_wrapper(
        tmp_path,
        "POSTGRES_PASSWORD=\n",
        extra_env={"POSTGRES_PASSWORD": ""},
    )
    assert captured["POSTGRES_PASSWORD"] == "soymutdb_dev_password"


# ---------------------------------------------------------------------------
# Profile resolution order.
# ---------------------------------------------------------------------------
def test_env_file_profiles_apply_when_shell_profile_unset(tmp_path: Path) -> None:
    _result, argv, _captured = _run_wrapper(
        tmp_path,
        "COMPOSE_PROFILES=blast,analyses\nPOSTGRES_PASSWORD=fixture\n",
    )
    assert _profile_flags(argv) == ["blast", "analyses"]


def test_empty_env_file_profiles_fall_back_to_core(tmp_path: Path) -> None:
    _result, argv, _captured = _run_wrapper(tmp_path, "COMPOSE_PROFILES=\n")
    assert _profile_flags(argv) == ["core"]


def test_shell_profiles_win_over_env_file_profiles(tmp_path: Path) -> None:
    _result, argv, _captured = _run_wrapper(
        tmp_path,
        "COMPOSE_PROFILES=blast\n",
        extra_env={"COMPOSE_PROFILES": "analyses"},
    )
    assert _profile_flags(argv) == ["analyses"]


def test_local_profile_switch_wins_over_shell_and_env_file(tmp_path: Path) -> None:
    _result, argv, captured = _run_wrapper(
        tmp_path,
        "COMPOSE_PROFILES=blast\n",
        extra_env={"COMPOSE_PROFILES": "analyses", "SOYMUTDB_LOCAL_PROFILES": "mcp"},
    )
    assert _profile_flags(argv) == ["mcp"]
    # The env file's list must not reach Compose: it unions the env value with
    # the `--profile` flags, so the wrapper exports the resolved list to mask it.
    assert captured["COMPOSE_PROFILES"] == "mcp"


def test_profiles_default_to_core_when_nothing_is_set(tmp_path: Path) -> None:
    _result, argv, _captured = _run_wrapper(tmp_path, "POSTGRES_PASSWORD=fixture\n")
    assert _profile_flags(argv) == ["core"]


# ---------------------------------------------------------------------------
# Compose-legal env-file syntax: a final line without a trailing newline.
# ---------------------------------------------------------------------------
def test_env_file_without_trailing_newline_is_fully_read(tmp_path: Path) -> None:
    _result, argv, _captured = _run_wrapper(tmp_path, "COMPOSE_PROFILES=blast")
    assert _profile_flags(argv) == ["blast"]
