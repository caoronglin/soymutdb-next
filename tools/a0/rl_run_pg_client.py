"""Shell-free, allowlisted PostgreSQL client launcher for A0 unit contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from .rl_prepare_pg_profile import (
    rl_CleanupOutcome,
    rl_ProfileRecord,
    rl_ProfileRegistry,
    rl_build_sanitized_env,
    rl_cleanup_runtime,
    rl_create_pgpass,
    rl_prepare_pg_profile,
)


class rl_ClientError(ValueError):
    """Raised for an operation or launcher contract violation."""


class rl_ArchiveRegistry(Protocol):
    def get(self, rl_archive_ref: str) -> object | None:
        """Resolve one opaque archive reference to a typed test/provisioner handle."""


@dataclass(frozen=True, slots=True)
class rl_ArchiveHandle:
    """Opaque archive seam; restricted path policy remains outside this task."""

    rl_archive_ref: str
    rl_archive_path: Path = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.rl_archive_ref, str):
            raise rl_ClientError("invalid archive handle")
        rl_validate_archive_ref(self.rl_archive_ref)
        if not isinstance(self.rl_archive_path, Path):
            raise rl_ClientError("invalid archive handle")


class rl_InMemoryArchiveRegistry:
    def __init__(self, rl_archives: Mapping[str, object]):
        self.rl_archives = dict(rl_archives)

    def get(self, rl_archive_ref: str) -> object | None:
        return self.rl_archives.get(rl_archive_ref)


@dataclass(frozen=True, slots=True, repr=False)
class rl_ClientOutcome:
    rl_status: str
    rl_evidence: dict[str, object] = field(default_factory=dict)
    rl_reason: str | None = None

    def __repr__(self) -> str:
        return f"rl_ClientOutcome(rl_status={self.rl_status!r}, rl_reason={self.rl_reason!r})"


def rl_sha256_bytes(rl_value: bytes) -> str:
    return "sha256:" + hashlib.sha256(rl_value).hexdigest()


def rl_validate_archive_ref(rl_archive_ref: str) -> str:
    if (
        not isinstance(rl_archive_ref, str)
        or not rl_archive_ref
        or len(rl_archive_ref) > 128
        or any(ord(rl_char) < 0x21 or ord(rl_char) == 0x7F for rl_char in rl_archive_ref)
        or "/" in rl_archive_ref
        or "\\" in rl_archive_ref
    ):
        raise rl_ClientError("invalid archive reference")
    return rl_archive_ref


def rl_build_client_argv(
    *,
    operation: str,
    profile: rl_ProfileRecord,
    archive_path: Path | None = None,
    restricted_output_path: Path | None = None,
    executable: str | None = None,
    extra_argv: Sequence[str] | None = None,
) -> list[str]:
    """Build fixed argv; callers cannot supply executable, SQL or flags."""

    if executable is not None or extra_argv is not None:
        raise rl_ClientError("arbitrary executable or argv is forbidden")
    if operation not in {"dump", "list", "restore"}:
        raise rl_ClientError("unsupported operation")

    if operation == "dump":
        if restricted_output_path is None:
            raise rl_ClientError("dump output is unavailable")
        return [
            "pg_dump",
            "--format=custom",
            "--no-password",
            "--no-owner",
            "--no-privileges",
            f"--file={restricted_output_path}",
        ]

    if archive_path is None:
        raise rl_ClientError("archive is unavailable")
    rl_archive = str(archive_path)
    if operation == "list":
        return ["pg_restore", "--list", "--no-password", rl_archive]

    return [
        "pg_restore",
        "--dbname=" + profile.rl_bare_database_name,
        "--no-password",
        "--exit-on-error",
        "--single-transaction",
        "--no-owner",
        "--no-privileges",
        rl_archive,
    ]


class rl_SubprocessRunner(Protocol):
    def __call__(self, *rl_args, **rl_kwargs):
        """Compatible subset of ``subprocess.run``."""


def rl_clock_value(rl_clock: Callable[[], object] | None) -> str:
    try:
        rl_value = datetime.now(UTC) if rl_clock is None else rl_clock()
    except BaseException:
        return "clock-error"
    if isinstance(rl_value, datetime):
        return rl_value.isoformat()
    if not isinstance(rl_value, str) or not rl_value or any(
        ord(rl_char) < 0x20 or ord(rl_char) == 0x7F for rl_char in rl_value
    ):
        return "clock-invalid"
    return rl_value


def rl_safe_launcher_token(rl_value: object) -> str | None:
    if not isinstance(rl_value, str) or not 1 <= len(rl_value) <= 128:
        return None
    if any(
        rl_char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
        for rl_char in rl_value
    ):
        return None
    return rl_value


def rl_safe_archive_ref(rl_value: object) -> str | None:
    if not isinstance(rl_value, str):
        return None
    try:
        return rl_validate_archive_ref(rl_value)
    except rl_ClientError:
        return None


def rl_launcher_record(
    *,
    operation: str,
    profile: rl_ProfileRecord | None,
    archive_ref: str | None,
    argv: Sequence[str],
    returncode: int | None,
    stdout: bytes,
    stderr: bytes,
    cleanup_status: str,
    blocking_reason: str | None,
    runner_invoked: bool,
    status: str,
    started_at: str,
    finished_at: str,
) -> dict[str, object]:
    """Build the one final safe launcher record, excluding its content ID."""

    rl_redacted_argv: list[str] = []
    for rl_index, rl_arg in enumerate(argv):
        if rl_arg.startswith("--file="):
            rl_redacted_argv.append("--file=<restricted-output>")
        elif rl_arg.startswith("--dbname="):
            rl_redacted_argv.append("--dbname=<profile-database>")
        elif operation in {"list", "restore"} and rl_index == len(argv) - 1:
            rl_redacted_argv.append("<opaque-archive>")
        else:
            rl_redacted_argv.append(rl_arg)

    rl_safe_operation = operation if operation in {"dump", "list", "restore"} else "unknown"
    return {
        "launcher_record_version": "a0.launcher.v1",
        "operation": rl_safe_operation,
        "run_id": profile.rl_run_id if profile is not None else None,
        "role": profile.rl_role if profile is not None else None,
        "profile_digest": profile.rl_profile_digest if profile is not None else None,
        "archive_ref": archive_ref,
        "runner_invoked": runner_invoked,
        "exit_code": returncode,
        "stdout_digest": rl_sha256_bytes(stdout),
        "stderr_digest": rl_sha256_bytes(stderr),
        "started_at": started_at,
        "finished_at": finished_at,
        "redacted_argv_template": f"{rl_safe_operation}:fixed-allowlist",
        "redacted_argv": rl_redacted_argv,
        "cleanup_status": cleanup_status,
        "status": status,
        "reason": blocking_reason,
        "owner": "rl_client_evidence_owner",
        "reviewer": "rl_database_safety_reviewer",
    }


def rl_launcher_record_id(rl_record: Mapping[str, object]) -> str:
    rl_payload = {
        rl_key: rl_value for rl_key, rl_value in rl_record.items() if rl_key != "launcher_record_id"
    }
    rl_bytes = json.dumps(rl_payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(rl_bytes).hexdigest()


def rl_finalize_launcher_record(rl_record: Mapping[str, object]) -> dict[str, object]:
    rl_final = dict(rl_record)
    rl_final["launcher_record_id"] = rl_launcher_record_id(rl_final)
    return rl_final


def rl_redacted_evidence(
    *,
    operation: str,
    profile: rl_ProfileRecord,
    returncode: int | None,
    stdout: bytes = b"",
    stderr: bytes = b"",
    reason: str | None = None,
) -> dict[str, object]:
    """Compatibility helper returning the same safe record shape as the launcher."""

    return rl_finalize_launcher_record(
        rl_launcher_record(
            operation=operation,
            profile=profile,
            archive_ref=None,
            argv=(),
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            cleanup_status="not_started",
            blocking_reason=reason,
            runner_invoked=False,
            status="BLOCKED" if reason is not None else "OK",
            started_at="",
            finished_at="",
        )
    )


def rl_run_pg_client(
    *,
    operation: str,
    registry: rl_ProfileRegistry,
    profile_id: str | None = None,
    profile_env: str | None = None,
    environ: Mapping[str, str] | None = None,
    role: str,
    run_id: str,
    archive_registry: rl_ArchiveRegistry | None = None,
    archive_ref: str | None = None,
    runner: rl_SubprocessRunner = subprocess.run,
    runtime_root: Path,
    restricted_output_path: Path | None = None,
    cleanup: Callable[[rl_CleanupOutcome], object] | None = None,
    clock: Callable[[], object] | None = None,
) -> rl_ClientOutcome:
    """Run the fixed client and create one final fail-closed launcher record."""

    rl_profile: rl_ProfileRecord | None = None
    rl_material = None
    rl_argv: list[str] = []
    rl_stdout = b""
    rl_stderr = b""
    rl_returncode: int | None = None
    rl_runner_invoked = False
    rl_status = "BLOCKED"
    rl_reason: str | None = "client_contract_violation"
    rl_cleanup_status = "not_started"
    rl_started_at = rl_clock_value(clock)

    def rl_reason_for_error(rl_error: BaseException) -> str:
        rl_message = str(rl_error)
        if rl_message == "archive is unavailable":
            return "archive_unavailable"
        if rl_message in {"archive handle contract", "invalid archive handle"}:
            return "archive_handle_contract"
        if rl_message == "runner exception":
            return "runner_exception"
        if rl_message == "stream capture failure":
            return "stream_capture_failure"
        return "client_contract_violation"

    try:
        if operation not in {"dump", "list", "restore"}:
            raise rl_ClientError("unsupported operation")
        rl_profile = rl_prepare_pg_profile(
            registry=registry,
            profile_id=profile_id,
            profile_env=profile_env,
            environ=environ,
            role=role,
            run_id=run_id,
        )

        rl_archive_path: Path | None = None
        if operation in {"list", "restore"}:
            if archive_registry is None or archive_ref is None:
                raise rl_ClientError("archive reference is required")
            rl_archive_ref = rl_validate_archive_ref(archive_ref)
            rl_archive_candidate = archive_registry.get(rl_archive_ref)
            if not isinstance(rl_archive_candidate, rl_ArchiveHandle):
                raise rl_ClientError("archive handle contract")
            if rl_archive_candidate.rl_archive_ref != rl_archive_ref:
                raise rl_ClientError("archive handle contract")
            rl_archive_path = rl_archive_candidate.rl_archive_path
            if not rl_archive_path.is_file():
                raise rl_ClientError("archive is unavailable")

        rl_material = rl_create_pgpass(rl_profile, runtime_root=runtime_root)
        rl_cleanup_status = "pending"
        rl_env = rl_build_sanitized_env(
            rl_profile,
            base_env={} if environ is None else environ,
            passfile=rl_material.rl_passfile,
        )
        rl_argv = rl_build_client_argv(
            operation=operation,
            profile=rl_profile,
            archive_path=rl_archive_path,
            restricted_output_path=restricted_output_path,
        )
        try:
            rl_runner_invoked = True
            rl_completed = runner(
                rl_argv,
                shell=False,
                env=rl_env,
                capture_output=True,
                check=False,
            )
        except BaseException as rl_runner_error:
            raise rl_ClientError("runner exception") from rl_runner_error

        try:
            rl_stdout = bytes(getattr(rl_completed, "stdout", b"") or b"")
            rl_stderr = bytes(getattr(rl_completed, "stderr", b"") or b"")
            rl_returncode = int(getattr(rl_completed, "returncode", 1))
        except BaseException as rl_stream_error:
            raise rl_ClientError("stream capture failure") from rl_stream_error

        rl_partial_restore = bool(getattr(rl_completed, "rl_partial_restore", False))
        rl_stdout_unexpected = operation == "restore" and bool(rl_stdout)
        if rl_returncode != 0:
            rl_reason = "client_nonzero_exit"
        elif rl_partial_restore:
            rl_reason = "partial_restore"
        elif rl_stdout_unexpected:
            rl_reason = "restore_stdout_not_empty"
        else:
            rl_status = "OK"
            rl_reason = None
    except BaseException as rl_error:
        rl_reason = rl_reason_for_error(rl_error)
    finally:
        if rl_material is not None:
            rl_cleanup_outcome = rl_cleanup_runtime(rl_material, remove_tree=shutil.rmtree)
            if cleanup is not None:
                try:
                    cleanup(rl_cleanup_outcome)
                except BaseException:
                    rl_cleanup_outcome = rl_CleanupOutcome(rl_blocked=True, rl_error_kind="cleanup")
            if rl_cleanup_outcome.rl_blocked:
                rl_cleanup_status = "failed"
                rl_status = "BLOCKED"
                rl_reason = "cleanup_failure"
            else:
                rl_cleanup_status = "passed"

    rl_profile_for_record = rl_profile if rl_runner_invoked else None
    rl_finished_at = rl_clock_value(clock)
    rl_record = rl_launcher_record(
        operation=operation if operation in {"dump", "list", "restore"} else "unknown",
        profile=rl_profile_for_record,
        archive_ref=rl_safe_archive_ref(archive_ref),
        argv=rl_argv,
        returncode=rl_returncode,
        stdout=rl_stdout,
        stderr=rl_stderr,
        cleanup_status=rl_cleanup_status,
        blocking_reason=rl_reason,
        runner_invoked=rl_runner_invoked,
        status=rl_status,
        started_at=rl_started_at,
        finished_at=rl_finished_at,
    )
    if rl_profile_for_record is None:
        rl_record["role"] = rl_safe_launcher_token(role)
        rl_record["run_id"] = rl_safe_launcher_token(run_id)
    return rl_ClientOutcome(
        rl_status=rl_status,
        rl_reason=rl_reason,
        rl_evidence=rl_finalize_launcher_record(rl_record),
    )


class rl_SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _rl_message: str) -> None:
        raise SystemExit(2)


def rl_parse_args(rl_argv: list[str] | None = None) -> argparse.Namespace:
    rl_parser = rl_SafeArgumentParser(add_help=True)
    rl_parser.add_argument("--operation", choices=("dump", "list", "restore"), required=True)
    rl_selector = rl_parser.add_mutually_exclusive_group(required=True)
    rl_selector.add_argument("--profile-env")
    rl_selector.add_argument("--profile-id")
    rl_parser.add_argument("--archive-ref")
    rl_parser.add_argument("--run-id", required=True)
    rl_parser.add_argument("--role", required=True)
    rl_parser.add_argument("--evidence")
    return rl_parser.parse_args(rl_argv)


def rl_main(rl_argv: list[str] | None = None) -> int:
    rl_parse_args(rl_argv)
    raise rl_ClientError("profile and archive registries must be injected")


if __name__ == "__main__":
    rl_main()
