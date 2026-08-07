"""Pure unit contracts for the A0 PostgreSQL profile resolver."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import tools.a0.rl_prepare_pg_profile as rl_profile_module

from tools.a0.rl_prepare_pg_profile import (
    rl_InMemoryProfileRegistry,
    rl_ProfileSpec,
    rl_build_sanitized_env,
    rl_cleanup_runtime,
    rl_create_pgpass,
    rl_escape_pgpass_field,
    rl_parse_args,
    rl_prepare_pg_profile,
    rl_ProfileError,
    rl_render_pgpass_line,
)


def rl_make_registry(**rl_overrides) -> rl_InMemoryProfileRegistry:
    rl_values = {
        "rl_profile_id": "profile-a0",
        "rl_host": "127.0.0.1",
        "rl_port": 5432,
        "rl_user": "a0_runner",
        "rl_database": "synthetic_a0",
        "rl_role": "schema",
        "rl_run_id": "run-a0",
        "rl_secret_handle": "p:a\\ssword",
    }
    rl_values.update(rl_overrides)
    rl_spec = rl_ProfileSpec(**rl_values)
    return rl_InMemoryProfileRegistry({rl_spec.rl_profile_id: rl_spec})


def test_resolver_accepts_only_opaque_profile_selector() -> None:
    rl_registry = rl_make_registry()

    rl_record = rl_prepare_pg_profile(
        profile_id="profile-a0",
        registry=rl_registry,
        role="schema",
        run_id="run-a0",
    )

    assert rl_record.rl_bare_database_name == "synthetic_a0"
    assert rl_record.rl_role == "schema"
    assert rl_record.rl_run_id == "run-a0"
    assert "p:a" not in repr(rl_record)
    assert "postgresql" not in repr(rl_record)


@pytest.mark.parametrize(
    "rl_kwargs",
    [
        {"profile_id": "postgresql://user:password@example/db"},
        {"profile_id": "user:password@example"},
        {"profile_id": "synthetic_a0"},
        {"profile_env": "RL_PROFILE", "environ": {}},
        {"profile_env": "postgresql://bad", "environ": {"postgresql://bad": "profile-a0"}},
    ],
)
def test_resolver_rejects_url_password_database_or_non_opaque_selector(rl_kwargs) -> None:
    with pytest.raises(rl_ProfileError):
        rl_prepare_pg_profile(registry=rl_make_registry(), **rl_kwargs)


def test_profile_env_resolves_an_opaque_value_without_shell_exports() -> None:
    rl_record = rl_prepare_pg_profile(
        profile_env="RL_PROFILE",
        environ={"RL_PROFILE": "profile-a0"},
        registry=rl_make_registry(),
    )

    assert rl_record.rl_profile_id == "profile-a0"
    assert "export" not in repr(rl_record).lower()


@pytest.mark.parametrize(
    "rl_field,rl_value",
    [
        ("rl_host", "127.0.0.1\nmalicious"),
        ("rl_host", "127.0.0.1\x00malicious"),
        ("rl_user", "a0\tuser"),
        ("rl_database", "bad database"),
        ("rl_role", "schema;drop"),
        ("rl_profile_id", "profile/../../secret"),
    ],
)
def test_profile_components_fail_closed_on_control_or_invalid_name(rl_field: str, rl_value: str) -> None:
    rl_registry = rl_make_registry(**{rl_field: rl_value})

    with pytest.raises(rl_ProfileError):
        rl_prepare_pg_profile(profile_id="profile-a0", registry=rl_registry)


@pytest.mark.parametrize("rl_name", ["PGSERVICE", "PGOPTIONS", "PGPASSWORD", "PGHOST"])
def test_caller_pg_overrides_are_rejected(rl_name: str) -> None:
    rl_record = rl_prepare_pg_profile(profile_id="profile-a0", registry=rl_make_registry())

    with pytest.raises(rl_ProfileError):
        rl_build_sanitized_env(rl_record, base_env={rl_name: "caller-controlled"})


def test_pgpass_escapes_colon_and_backslash_and_uses_restricted_modes(tmp_path: Path) -> None:
    assert rl_escape_pgpass_field(r"a:b\c") == r"a\:b\\c"
    assert rl_render_pgpass_line("host", "5432", "db", "user", r"a:b\c") == (
        "host:5432:db:user:a\\:b\\\\c\n"
    )

    rl_record = rl_prepare_pg_profile(profile_id="profile-a0", registry=rl_make_registry())
    rl_runtime_root = tmp_path / "runtime"
    rl_material = rl_create_pgpass(rl_record, runtime_root=rl_runtime_root)

    assert os.stat(rl_runtime_root).st_mode & 0o777 == 0o700
    assert os.stat(rl_material.rl_passfile).st_mode & 0o777 == 0o600
    assert rl_material.rl_passfile.read_text() == (
        "127.0.0.1:5432:synthetic_a0:a0_runner:p\\:a\\\\ssword\n"
    )


def test_pgpass_rendering_round_trips_libpq_escaped_fields() -> None:
    rl_fields = (r"host:part\zone", r"54:32", r"db\name:part", r"user:part\zone", r"pass:word\z")

    rl_rendered = rl_render_pgpass_line(*rl_fields)

    assert rl_profile_module.rl_parse_pgpass_line(rl_rendered) == rl_fields


@pytest.mark.parametrize("rl_bad_value", ["password\nnext", "password\rnext", "password\x00"])
def test_pgpass_rendering_rejects_newline_and_control_values(rl_bad_value: str) -> None:
    with pytest.raises(rl_ProfileError):
        rl_render_pgpass_line("host", "5432", "db", "user", rl_bad_value)


def test_cleanup_failure_is_a_blocking_outcome(tmp_path: Path) -> None:
    rl_record = rl_prepare_pg_profile(profile_id="profile-a0", registry=rl_make_registry())
    rl_material = rl_create_pgpass(rl_record, runtime_root=tmp_path / "runtime")

    def rl_fail_cleanup(_rl_path: Path) -> None:
        raise OSError("simulated cleanup failure")

    rl_outcome = rl_cleanup_runtime(rl_material, remove_tree=rl_fail_cleanup)

    assert rl_outcome.rl_blocked is True
    assert "simulated cleanup failure" not in repr(rl_outcome)
    assert str(rl_material.rl_passfile) not in repr(rl_outcome)


@pytest.mark.parametrize(
    "rl_argv",
    [
        ["--profile-id", "profile-a0", "postgresql://secret"],
        ["--profile-id", "profile-a0", "--password", "secret"],
        ["--profile-id", "profile-a0", "--database", "synthetic_a0"],
        ["--profile-id", "profile-a0", "--url", "postgresql://secret"],
    ],
)
def test_cli_rejects_target_inputs_without_echoing_them(rl_argv, capsys) -> None:
    with pytest.raises(SystemExit):
        rl_parse_args(rl_argv)

    rl_captured = capsys.readouterr()
    assert "postgresql://secret" not in rl_captured.out + rl_captured.err
    assert "secret" not in rl_captured.out + rl_captured.err
