"""Pure unit contracts for the shell-free PostgreSQL client launcher."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from tools.a0.rl_prepare_pg_profile import rl_InMemoryProfileRegistry, rl_ProfileSpec
from tools.a0.rl_run_pg_client import (
    rl_ArchiveHandle,
    rl_build_client_argv,
    rl_ClientError,
    rl_InMemoryArchiveRegistry,
    rl_run_pg_client,
)


def rl_canonical_digest(rl_record: dict[str, object], rl_id_field: str) -> str:
    rl_payload = {
        rl_key: rl_value for rl_key, rl_value in rl_record.items() if rl_key != rl_id_field
    }
    rl_bytes = json.dumps(rl_payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(rl_bytes).hexdigest()


class rl_Completed:
    def __init__(
        self, rl_returncode: int = 0, rl_stdout: bytes = b"", rl_stderr: bytes = b"", **rl_extra
    ):
        self.returncode = rl_returncode
        self.stdout = rl_stdout
        self.stderr = rl_stderr
        for rl_name, rl_value in rl_extra.items():
            setattr(self, rl_name, rl_value)


def rl_make_profile_registry() -> rl_InMemoryProfileRegistry:
    rl_spec = rl_ProfileSpec(
        rl_profile_id="profile-a0",
        rl_host="127.0.0.1",
        rl_port=5432,
        rl_user="a0_runner",
        rl_database="synthetic_a0",
        rl_role="restore",
        rl_run_id="run-a0",
        rl_secret_handle="super-secret-password",
    )
    return rl_InMemoryProfileRegistry({"profile-a0": rl_spec})


def rl_make_archive_registry(tmp_path: Path) -> tuple[rl_InMemoryArchiveRegistry, Path]:
    rl_archive = tmp_path / "archive.dump"
    rl_archive.write_bytes(b"custom archive")
    return (
        rl_InMemoryArchiveRegistry({"archive-a0": rl_ArchiveHandle("archive-a0", rl_archive)}),
        rl_archive,
    )


def test_restore_uses_exact_internal_argv_and_redacted_evidence(tmp_path: Path) -> None:
    rl_archive_registry, rl_archive = rl_make_archive_registry(tmp_path)
    rl_calls = []

    def rl_runner(*rl_args, **rl_kwargs):
        rl_calls.append((rl_args, rl_kwargs))
        return rl_Completed()

    rl_outcome = rl_run_pg_client(
        operation="restore",
        profile_id="profile-a0",
        archive_ref="archive-a0",
        role="restore",
        run_id="run-a0",
        registry=rl_make_profile_registry(),
        archive_registry=rl_archive_registry,
        runner=rl_runner,
        runtime_root=tmp_path / "runtime",
    )

    assert rl_outcome.rl_status == "OK"
    assert len(rl_calls) == 1
    (rl_argv,), rl_kwargs = rl_calls[0]
    assert rl_argv == [
        "pg_restore",
        "--dbname=synthetic_a0",
        "--no-password",
        "--exit-on-error",
        "--single-transaction",
        "--no-owner",
        "--no-privileges",
        str(rl_archive),
    ]
    assert rl_kwargs["shell"] is False
    assert rl_kwargs["capture_output"] is True
    assert rl_kwargs["check"] is False
    assert "PGPASSWORD" not in rl_kwargs["env"]
    assert "PGSERVICE" not in rl_kwargs["env"]
    assert "PGOPTIONS" not in rl_kwargs["env"]

    rl_evidence = json.dumps(rl_outcome.rl_evidence, ensure_ascii=False)
    assert "super-secret-password" not in rl_evidence
    assert "postgresql://" not in rl_evidence
    assert "synthetic_a0" not in rl_evidence
    assert str(rl_archive) not in rl_evidence


@pytest.mark.parametrize(
    "rl_result",
    [
        rl_Completed(rl_stdout=b"CREATE TABLE leaked_sql;"),
        rl_Completed(rl_returncode=1, rl_stderr=b"database failure"),
        rl_Completed(rl_partial_restore=True),
    ],
)
def test_restore_failures_are_blocking_and_never_emit_raw_streams(
    tmp_path: Path, rl_result
) -> None:
    rl_archive_registry, _ = rl_make_archive_registry(tmp_path)

    def rl_runner(*_rl_args, **_rl_kwargs):
        return rl_result

    rl_outcome = rl_run_pg_client(
        operation="restore",
        profile_id="profile-a0",
        archive_ref="archive-a0",
        role="restore",
        run_id="run-a0",
        registry=rl_make_profile_registry(),
        archive_registry=rl_archive_registry,
        runner=rl_runner,
        runtime_root=tmp_path / "runtime",
    )

    assert rl_outcome.rl_status == "BLOCKED"
    rl_evidence = json.dumps(rl_outcome.rl_evidence, ensure_ascii=False)
    assert "CREATE TABLE leaked_sql" not in rl_evidence
    assert "database failure" not in rl_evidence
    assert "super-secret-password" not in rl_evidence


def test_missing_archive_blocks_before_runner(tmp_path: Path) -> None:
    rl_archive_registry = rl_InMemoryArchiveRegistry({})
    rl_call_count = 0

    def rl_runner(*_rl_args, **_rl_kwargs):
        nonlocal rl_call_count
        rl_call_count += 1
        return rl_Completed()

    rl_outcome = rl_run_pg_client(
        operation="restore",
        profile_id="profile-a0",
        archive_ref="missing-archive",
        role="restore",
        run_id="run-a0",
        registry=rl_make_profile_registry(),
        archive_registry=rl_archive_registry,
        runner=rl_runner,
        runtime_root=tmp_path / "runtime",
    )

    assert rl_outcome.rl_status == "BLOCKED"
    assert rl_call_count == 0


@pytest.mark.parametrize("rl_operation", ["dump", "list", "restore"])
def test_operation_argv_has_no_destructive_or_arbitrary_flags(
    tmp_path: Path, rl_operation: str
) -> None:
    rl_archive_registry, rl_archive = rl_make_archive_registry(tmp_path)
    rl_record = __import__(
        "tools.a0.rl_prepare_pg_profile", fromlist=["rl_prepare_pg_profile"]
    ).rl_prepare_pg_profile(profile_id="profile-a0", registry=rl_make_profile_registry())

    rl_argv = rl_build_client_argv(
        operation=rl_operation,
        profile=rl_record,
        archive_path=rl_archive,
        restricted_output_path=tmp_path / "dump.custom",
    )

    assert "--clean" not in rl_argv
    assert "--create" not in rl_argv
    assert "--jobs" not in rl_argv
    assert all(rl_flag not in rl_argv for rl_flag in ["--sql", "--url", "--password"])


def test_arbitrary_executable_or_argv_is_rejected(tmp_path: Path) -> None:
    rl_archive_registry, rl_archive = rl_make_archive_registry(tmp_path)
    rl_record = __import__(
        "tools.a0.rl_prepare_pg_profile", fromlist=["rl_prepare_pg_profile"]
    ).rl_prepare_pg_profile(profile_id="profile-a0", registry=rl_make_profile_registry())

    with pytest.raises(rl_ClientError):
        rl_build_client_argv(
            operation="restore",
            profile=rl_record,
            archive_path=rl_archive,
            executable="sh",
        )


def test_client_cli_contract_rejects_sql_path_and_arbitrary_argv() -> None:
    from tools.a0.rl_run_pg_client import rl_parse_args

    for rl_bad_args in (
        ["--operation", "restore", "--sql", "DROP DATABASE"],
        ["--operation", "restore", "--argv", "sh"],
        ["--operation", "restore", "--url", "postgresql://secret"],
        ["--operation", "restore", "--archive-ref", "/tmp/real-path"],
    ):
        with pytest.raises(SystemExit):
            rl_parse_args(rl_bad_args)


def test_restore_cleanup_failure_blocks_even_after_zero_exit(tmp_path: Path) -> None:
    rl_archive_registry, _ = rl_make_archive_registry(tmp_path)

    def rl_runner(*_rl_args, **_rl_kwargs):
        return rl_Completed()

    def rl_cleanup_failure(_rl_material):
        raise OSError("cleanup blocked")

    rl_outcome = rl_run_pg_client(
        operation="restore",
        profile_id="profile-a0",
        archive_ref="archive-a0",
        role="restore",
        run_id="run-a0",
        registry=rl_make_profile_registry(),
        archive_registry=rl_archive_registry,
        runner=rl_runner,
        runtime_root=tmp_path / "runtime",
        cleanup=rl_cleanup_failure,
    )

    assert rl_outcome.rl_status == "BLOCKED"


def test_launcher_record_contains_redacted_stable_fields(tmp_path: Path) -> None:
    rl_archive_registry, rl_archive = rl_make_archive_registry(tmp_path)

    def rl_runner(*_rl_args, **_rl_kwargs):
        return rl_Completed(rl_stderr=b"diagnostic")

    rl_outcome = rl_run_pg_client(
        operation="restore",
        profile_id="profile-a0",
        archive_ref="archive-a0",
        role="restore",
        run_id="run-a0",
        registry=rl_make_profile_registry(),
        archive_registry=rl_archive_registry,
        runner=rl_runner,
        runtime_root=tmp_path / "runtime",
    )

    assert rl_outcome.rl_status == "OK"
    assert rl_outcome.rl_evidence["launcher_record_version"] == "a0.launcher.v1"
    assert rl_outcome.rl_evidence["launcher_record_id"] == rl_canonical_digest(
        rl_outcome.rl_evidence, "launcher_record_id"
    )
    assert rl_outcome.rl_evidence["operation"] == "restore"
    assert rl_outcome.rl_evidence["run_id"] == "run-a0"
    assert rl_outcome.rl_evidence["role"] == "restore"
    assert rl_outcome.rl_evidence["profile_digest"].startswith("sha256:")
    assert rl_outcome.rl_evidence["exit_code"] == 0
    assert rl_outcome.rl_evidence["stdout_digest"].startswith("sha256:")
    assert rl_outcome.rl_evidence["stderr_digest"].startswith("sha256:")
    assert rl_outcome.rl_evidence["cleanup_status"] == "passed"
    assert rl_outcome.rl_evidence["archive_ref"] == "archive-a0"
    assert rl_outcome.rl_evidence["reason"] is None
    assert isinstance(rl_outcome.rl_evidence["redacted_argv"], list)
    assert rl_outcome.rl_evidence["runner_invoked"] is True
    assert rl_outcome.rl_evidence["status"] == "OK"
    assert rl_outcome.rl_evidence["owner"] == "rl_client_evidence_owner"
    assert rl_outcome.rl_evidence["reviewer"] == "rl_database_safety_reviewer"
    assert rl_outcome.rl_evidence["finished_at"] >= rl_outcome.rl_evidence["started_at"]
    rl_evidence_text = json.dumps(rl_outcome.rl_evidence, ensure_ascii=False)
    assert str(rl_archive) not in rl_evidence_text


def test_raw_path_archive_registry_return_is_blocked_before_runner(tmp_path: Path) -> None:
    rl_archive = tmp_path / "archive.dump"
    rl_archive.write_bytes(b"custom archive")
    rl_archive_registry = rl_InMemoryArchiveRegistry({"archive-a0": rl_archive})
    rl_call_count = 0

    def rl_runner(*_rl_args, **_rl_kwargs):
        nonlocal rl_call_count
        rl_call_count += 1
        return rl_Completed()

    rl_outcome = rl_run_pg_client(
        operation="restore",
        profile_id="profile-a0",
        archive_ref="archive-a0",
        role="restore",
        run_id="run-a0",
        registry=rl_make_profile_registry(),
        archive_registry=rl_archive_registry,
        runner=rl_runner,
        runtime_root=tmp_path / "runtime",
    )

    assert rl_outcome.rl_status == "BLOCKED"
    assert rl_outcome.rl_reason == "archive_handle_contract"
    assert rl_call_count == 0
    assert rl_outcome.rl_evidence["cleanup_status"] == "not_started"
    assert str(rl_archive) not in json.dumps(rl_outcome.rl_evidence)


def test_early_invalid_operation_returns_complete_nonexecuted_record(tmp_path: Path) -> None:
    rl_outcome = rl_run_pg_client(
        operation="DROP /tmp/raw-password",
        profile_id="profile-a0",
        role="restore",
        run_id="run-a0",
        registry=rl_make_profile_registry(),
        runner=lambda *_rl_args, **_rl_kwargs: rl_Completed(),
        runtime_root=tmp_path / "runtime",
    )

    assert rl_outcome.rl_status == "BLOCKED"
    assert rl_outcome.rl_evidence["launcher_record_version"] == "a0.launcher.v1"
    assert rl_outcome.rl_evidence["launcher_record_id"] == rl_canonical_digest(
        rl_outcome.rl_evidence, "launcher_record_id"
    )
    assert rl_outcome.rl_evidence["operation"] == "unknown"
    assert rl_outcome.rl_evidence["profile_digest"] is None
    assert rl_outcome.rl_evidence["runner_invoked"] is False
    assert rl_outcome.rl_evidence["exit_code"] is None
    assert rl_outcome.rl_evidence["stdout_digest"].startswith("sha256:")
    assert rl_outcome.rl_evidence["stderr_digest"].startswith("sha256:")
    assert rl_outcome.rl_evidence["cleanup_status"] == "not_started"
    assert rl_outcome.rl_evidence["status"] == "BLOCKED"
    assert "DROP /tmp/raw-password" not in json.dumps(rl_outcome.rl_evidence)


def test_invalid_absolute_archive_ref_is_not_retained_in_evidence(tmp_path: Path) -> None:
    rl_outcome = rl_run_pg_client(
        operation="restore",
        profile_id="profile-a0",
        archive_ref="/restricted/archive.dump",
        role="restore",
        run_id="run-a0",
        registry=rl_make_profile_registry(),
        archive_registry=rl_InMemoryArchiveRegistry({}),
        runner=lambda *_rl_args, **_rl_kwargs: rl_Completed(),
        runtime_root=tmp_path / "runtime",
    )

    assert rl_outcome.rl_status == "BLOCKED"
    assert "/restricted/archive.dump" not in json.dumps(rl_outcome.rl_evidence)


def test_runner_exception_is_blocked_and_runtime_cleanup_is_attempted(tmp_path: Path) -> None:
    rl_archive_registry, _ = rl_make_archive_registry(tmp_path)
    rl_runtime_root = tmp_path / "runtime"

    def rl_runner(*_rl_args, **_rl_kwargs):
        raise RuntimeError("raw runner failure must not escape")

    rl_outcome = rl_run_pg_client(
        operation="restore",
        profile_id="profile-a0",
        archive_ref="archive-a0",
        role="restore",
        run_id="run-a0",
        registry=rl_make_profile_registry(),
        archive_registry=rl_archive_registry,
        runner=rl_runner,
        runtime_root=rl_runtime_root,
    )

    assert rl_outcome.rl_status == "BLOCKED"
    assert rl_outcome.rl_reason == "runner_exception"
    assert rl_outcome.rl_evidence["cleanup_status"] == "passed"
    assert rl_outcome.rl_evidence["runner_invoked"] is True
    assert rl_outcome.rl_evidence["exit_code"] is None
    assert rl_outcome.rl_evidence["reason"] == "runner_exception"
    assert rl_outcome.rl_evidence["launcher_record_id"] == rl_canonical_digest(
        rl_outcome.rl_evidence, "launcher_record_id"
    )
    assert "raw runner failure" not in json.dumps(rl_outcome.rl_evidence)
    assert not rl_runtime_root.exists()
