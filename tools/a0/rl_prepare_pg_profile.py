"""Restricted, injectable PostgreSQL profile resolution primitives.

This module deliberately does not talk to a registry service.  A provisioner can
provide an implementation of the tiny registry protocol later; unit tests use
``rl_InMemoryProfileRegistry`` only.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Protocol
from urllib.parse import quote


class rl_ProfileError(ValueError):
    """Raised when a profile selector or component is unsafe or unavailable."""


class rl_ProfileRegistry(Protocol):
    def get(self, rl_profile_id: str) -> "rl_ProfileSpec | None":
        """Return one restricted profile specification, or ``None``."""


@dataclass(frozen=True, slots=True)
class rl_ProfileSpec:
    """The provisioner-owned, injectable profile tuple used by A0.

    ``rl_secret_handle`` is deliberately opaque to callers.  The resolver only
    keeps it in process memory long enough to build a mode-0600 passfile.
    """

    rl_profile_id: str
    rl_host: str
    rl_port: int
    rl_user: str
    rl_database: str
    rl_role: str
    rl_run_id: str
    rl_secret_handle: str = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class rl_ProfileRecord:
    """Resolved profile with raw connection material hidden from repr/evidence."""

    rl_profile_id: str
    rl_host: str
    rl_port: int
    rl_user: str
    rl_bare_database_name: str
    rl_role: str
    rl_run_id: str
    rl_profile_digest: str
    rl_configured_identity_redacted: dict[str, object]
    rl_asyncpg_url: str = field(repr=False)
    rl_secret_handle: str = field(repr=False)

    def __repr__(self) -> str:
        return (
            "rl_ProfileRecord("
            f"rl_profile_id={self.rl_profile_id!r}, "
            f"rl_role={self.rl_role!r}, "
            f"rl_run_id={self.rl_run_id!r}, "
            f"rl_profile_digest={self.rl_profile_digest!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class rl_PgpassMaterial:
    """Restricted runtime material.  Its path is not an evidence field."""

    rl_runtime_root: Path
    rl_passfile: Path

    def __repr__(self) -> str:
        return "rl_PgpassMaterial(<restricted>)"


@dataclass(frozen=True, slots=True, repr=False)
class rl_CleanupOutcome:
    rl_blocked: bool
    rl_error_kind: str | None = None

    def __repr__(self) -> str:
        return f"rl_CleanupOutcome(rl_blocked={self.rl_blocked!r})"


class rl_InMemoryProfileRegistry:
    """Small test/provisioner adapter; it performs no I/O."""

    def __init__(self, rl_profiles: Mapping[str, rl_ProfileSpec]):
        self.rl_profiles = dict(rl_profiles)

    def get(self, rl_profile_id: str) -> rl_ProfileSpec | None:
        return self.rl_profiles.get(rl_profile_id)


rl_SAFE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
rl_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
rl_DATABASE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
rl_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
rl_HOST_RE = re.compile(r"^[A-Za-z0-9._:[\]-]{1,253}$")
rl_MAX_COMPONENT_LENGTH = 512


def rl_reject_control(rl_name: str, rl_value: str) -> str:
    if not isinstance(rl_value, str) or not rl_value:
        raise rl_ProfileError(f"invalid {rl_name}")
    if len(rl_value) > rl_MAX_COMPONENT_LENGTH:
        raise rl_ProfileError(f"invalid {rl_name}")
    # 为什么：控制字符会改变环境、日志或 passfile 的边界，必须 fail-close。
    if any(ord(rl_char) < 0x20 or ord(rl_char) == 0x7F for rl_char in rl_value):
        raise rl_ProfileError(f"invalid {rl_name}")
    return rl_value


def rl_validate_profile_id(rl_profile_id: str) -> str:
    rl_profile_id = rl_reject_control("profile_id", rl_profile_id)
    if not rl_PROFILE_ID_RE.fullmatch(rl_profile_id):
        raise rl_ProfileError("invalid profile_id")
    return rl_profile_id


def rl_validate_role(rl_role: str) -> str:
    rl_role = rl_reject_control("role", rl_role)
    if not rl_SAFE_NAME_RE.fullmatch(rl_role):
        raise rl_ProfileError("invalid role")
    return rl_role


def rl_validate_run_id(rl_run_id: str) -> str:
    rl_run_id = rl_reject_control("run_id", rl_run_id)
    if not rl_PROFILE_ID_RE.fullmatch(rl_run_id):
        raise rl_ProfileError("invalid run_id")
    return rl_run_id


def rl_validate_database(rl_database: str) -> str:
    rl_database = rl_reject_control("database", rl_database)
    if not rl_DATABASE_RE.fullmatch(rl_database):
        raise rl_ProfileError("invalid database")
    return rl_database


def rl_validate_host(rl_host: str) -> str:
    rl_host = rl_reject_control("host", rl_host)
    if not rl_HOST_RE.fullmatch(rl_host) or any(
        rl_token in rl_host for rl_token in ("/", "@", "?", "#", "%")
    ):
        raise rl_ProfileError("invalid host")
    return rl_host


def rl_validate_port(rl_port: int) -> int:
    if isinstance(rl_port, bool) or not isinstance(rl_port, int) or not 1 <= rl_port <= 65535:
        raise rl_ProfileError("invalid port")
    return rl_port


def rl_validate_env_name(rl_name: str) -> str:
    rl_name = rl_reject_control("profile_env", rl_name)
    if not rl_ENV_NAME_RE.fullmatch(rl_name):
        raise rl_ProfileError("invalid profile_env")
    return rl_name


def rl_validate_profile_spec(rl_spec: rl_ProfileSpec) -> rl_ProfileSpec:
    if not isinstance(rl_spec, rl_ProfileSpec):
        raise rl_ProfileError("invalid profile specification")
    rl_validate_profile_id(rl_spec.rl_profile_id)
    rl_validate_host(rl_spec.rl_host)
    rl_validate_port(rl_spec.rl_port)
    rl_reject_control("user", rl_spec.rl_user)
    rl_validate_database(rl_spec.rl_database)
    rl_validate_role(rl_spec.rl_role)
    rl_validate_run_id(rl_spec.rl_run_id)
    # 为什么：secret 只允许作为 passfile 输入，不能携带换行或字段分隔符。
    rl_reject_control("secret_handle", rl_spec.rl_secret_handle)
    return rl_spec


def rl_digest(rl_value: str) -> str:
    return "sha256:" + hashlib.sha256(rl_value.encode("utf-8")).hexdigest()


def rl_prepare_pg_profile(
    *,
    registry: rl_ProfileRegistry,
    profile_id: str | None = None,
    profile_env: str | None = None,
    environ: Mapping[str, str] | None = None,
    role: str | None = None,
    run_id: str | None = None,
) -> rl_ProfileRecord:
    """Resolve one opaque selector into restricted in-process profile material."""

    if (profile_id is None) == (profile_env is None):
        raise rl_ProfileError("exactly one opaque profile selector is required")

    if profile_env is not None:
        rl_env_name = rl_validate_env_name(profile_env)
        rl_environment = os.environ if environ is None else environ
        rl_selected_id = rl_environment.get(rl_env_name)
        if rl_selected_id is None:
            raise rl_ProfileError("profile environment is unavailable")
        rl_selected_id = rl_validate_profile_id(rl_selected_id)
    else:
        rl_selected_id = rl_validate_profile_id(profile_id or "")

    rl_spec = registry.get(rl_selected_id)
    if rl_spec is None:
        raise rl_ProfileError("profile is unavailable")
    rl_validate_profile_spec(rl_spec)

    rl_expected_role = rl_validate_role(role) if role is not None else rl_spec.rl_role
    rl_expected_run_id = rl_validate_run_id(run_id) if run_id is not None else rl_spec.rl_run_id
    if rl_expected_role != rl_spec.rl_role or rl_expected_run_id != rl_spec.rl_run_id:
        raise rl_ProfileError("profile context mismatch")

    rl_host = rl_validate_host(rl_spec.rl_host)
    rl_port = rl_validate_port(rl_spec.rl_port)
    rl_user = rl_reject_control("user", rl_spec.rl_user)
    rl_database = rl_validate_database(rl_spec.rl_database)
    rl_secret = rl_reject_control("secret_handle", rl_spec.rl_secret_handle)
    rl_profile_digest = rl_digest(
        "|".join(
            (
                "a0.profile.v1",
                rl_spec.rl_profile_id,
                rl_host,
                str(rl_port),
                rl_user,
                rl_database,
                rl_expected_role,
                rl_expected_run_id,
            )
        )
    )
    rl_configured_identity_redacted = {
        "host": rl_host,
        "port": rl_port,
        "user_digest": rl_digest(rl_user),
        "database_digest": rl_digest(rl_database),
    }
    # URL 只在受限 process memory 中保留；不进入 argv、repr、日志或 evidence。
    rl_asyncpg_url = (
        "postgresql+asyncpg://"
        f"{quote(rl_user, safe='')}:{quote(rl_secret, safe='')}@"
        f"{rl_host}:{rl_port}/{quote(rl_database, safe='')}"
    )
    return rl_ProfileRecord(
        rl_profile_id=rl_spec.rl_profile_id,
        rl_host=rl_host,
        rl_port=rl_port,
        rl_user=rl_user,
        rl_bare_database_name=rl_database,
        rl_role=rl_expected_role,
        rl_run_id=rl_expected_run_id,
        rl_profile_digest=rl_profile_digest,
        rl_configured_identity_redacted=rl_configured_identity_redacted,
        rl_asyncpg_url=rl_asyncpg_url,
        rl_secret_handle=rl_secret,
    )


def rl_build_sanitized_env(
    rl_profile: rl_ProfileRecord,
    *,
    base_env: Mapping[str, str] | None = None,
    passfile: Path | None = None,
) -> dict[str, str]:
    """Build a minimal libpq environment without inheriting caller PG state."""

    rl_source_env = {} if base_env is None else dict(base_env)
    for rl_name, rl_value in rl_source_env.items():
        rl_reject_control(rl_name, rl_value)
        # 为什么：caller-controlled PG* can redirect a supposedly guarded action.
        if rl_name.upper().startswith("PG"):
            raise rl_ProfileError("caller PostgreSQL environment override")

    rl_env = {
        "PATH": rl_source_env.get("PATH", "/usr/bin:/bin"),
        "LC_ALL": "C",
        "LANG": "C",
        "PGHOST": rl_profile.rl_host,
        "PGPORT": str(rl_profile.rl_port),
        "PGUSER": rl_profile.rl_user,
        "PGDATABASE": rl_profile.rl_bare_database_name,
    }
    if passfile is not None:
        rl_env["PGPASSFILE"] = str(passfile)
    return rl_env


def rl_escape_pgpass_field(rl_value: str) -> str:
    rl_reject_control("pgpass_field", rl_value)
    # 为什么：先转义反斜杠再转义冒号，才能保持 libpq 字段边界。
    return rl_value.replace("\\", "\\\\").replace(":", "\\:")


def rl_parse_pgpass_line(rl_line: str) -> tuple[str, str, str, str, str]:
    """Parse one libpq-style pgpass line using its backslash grammar."""

    if not isinstance(rl_line, str) or not rl_line.endswith("\n"):
        raise rl_ProfileError("invalid pgpass line")
    rl_body = rl_line[:-1]
    if "\r" in rl_body:
        raise rl_ProfileError("invalid pgpass line")

    rl_fields: list[str] = []
    rl_field: list[str] = []
    rl_index = 0
    while rl_index < len(rl_body):
        rl_char = rl_body[rl_index]
        if rl_char == "\\":
            rl_index += 1
            if rl_index >= len(rl_body):
                raise rl_ProfileError("invalid pgpass escape")
            rl_field.append(rl_body[rl_index])
        elif rl_char == ":":
            rl_fields.append("".join(rl_field))
            rl_field = []
        else:
            rl_field.append(rl_char)
        rl_index += 1
    rl_fields.append("".join(rl_field))
    if len(rl_fields) != 5:
        raise rl_ProfileError("invalid pgpass field count")
    for rl_field_value in rl_fields:
        rl_reject_control("pgpass_field", rl_field_value)
    return tuple(rl_fields)  # type: ignore[return-value]


def rl_render_pgpass_line(
    rl_host: str,
    rl_port: str,
    rl_database: str,
    rl_user: str,
    rl_password: str,
) -> str:
    return ":".join(
        rl_escape_pgpass_field(rl_field)
        for rl_field in (rl_host, rl_port, rl_database, rl_user, rl_password)
    ) + "\n"


def rl_create_pgpass(
    rl_profile: rl_ProfileRecord,
    *,
    runtime_root: Path,
) -> rl_PgpassMaterial:
    """Create a mode-0700 runtime root and mode-0600 passfile."""

    rl_runtime_root = Path(runtime_root)
    rl_runtime_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    rl_runtime_root.chmod(0o700)
    if stat.S_IMODE(rl_runtime_root.stat().st_mode) != 0o700:
        raise rl_ProfileError("runtime root permissions are unsafe")

    rl_fd, rl_name = tempfile.mkstemp(prefix="rl-pgpass-", dir=rl_runtime_root)
    rl_passfile = Path(rl_name)
    try:
        os.fchmod(rl_fd, 0o600)
        rl_content = rl_render_pgpass_line(
            rl_profile.rl_host,
            str(rl_profile.rl_port),
            rl_profile.rl_bare_database_name,
            rl_profile.rl_user,
            rl_profile.rl_secret_handle,
        )
        with os.fdopen(rl_fd, "w", encoding="utf-8", newline="") as rl_stream:
            rl_stream.write(rl_content)
        if stat.S_IMODE(rl_passfile.stat().st_mode) != 0o600:
            raise rl_ProfileError("passfile permissions are unsafe")
    except BaseException:
        try:
            os.close(rl_fd)
        except OSError:
            pass
        try:
            rl_passfile.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return rl_PgpassMaterial(rl_runtime_root=rl_runtime_root, rl_passfile=rl_passfile)


def rl_cleanup_runtime(
    rl_material: rl_PgpassMaterial,
    *,
    remove_tree: Callable[[Path], object] | None = None,
) -> rl_CleanupOutcome:
    try:
        if remove_tree is None:
            shutil.rmtree(rl_material.rl_runtime_root)
        else:
            remove_tree(rl_material.rl_runtime_root)
    except BaseException as rl_error:
        # 只记录错误类别；路径、secret 和底层消息不能进入 evidence。
        return rl_CleanupOutcome(rl_blocked=True, rl_error_kind=type(rl_error).__name__)
    return rl_CleanupOutcome(rl_blocked=False)


class rl_SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _rl_message: str) -> None:
        # argparse 默认会回显未知参数，可能把 secret/URL 带到 stderr；这里静默拒绝。
        raise SystemExit(2)


def rl_parse_args(rl_argv: list[str] | None = None) -> argparse.Namespace:
    rl_parser = rl_SafeArgumentParser(add_help=True)
    rl_selector = rl_parser.add_mutually_exclusive_group(required=True)
    rl_selector.add_argument("--profile-env")
    rl_selector.add_argument("--profile-id")
    rl_parser.add_argument("--role")
    rl_parser.add_argument("--run-id")
    rl_parser.add_argument("--evidence")
    rl_namespace = rl_parser.parse_args(rl_argv)
    if rl_namespace.profile_env is not None:
        rl_validate_env_name(rl_namespace.profile_env)
    if rl_namespace.profile_id is not None:
        rl_validate_profile_id(rl_namespace.profile_id)
    if rl_namespace.role is not None:
        rl_validate_role(rl_namespace.role)
    if rl_namespace.run_id is not None:
        rl_validate_run_id(rl_namespace.run_id)
    return rl_namespace


def rl_main(rl_argv: list[str] | None = None) -> int:
    """Parse only the safe selector contract; registry actions are library-injected."""

    rl_parse_args(rl_argv)
    raise rl_ProfileError("profile registry must be injected")


if __name__ == "__main__":
    rl_main()
