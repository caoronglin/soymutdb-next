"""Async, read-only disposable-target identity guard.

The live engine/connection is intentionally injected.  This lane has no live
profile registry, provisioner, PostgreSQL, or SQLAlchemy side effect.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Protocol

from .rl_prepare_pg_profile import (
    rl_ProfileRecord,
    rl_ProfileRegistry,
    rl_digest,
    rl_prepare_pg_profile,
)


class rl_GuardError(ValueError):
    """Raised only for invalid guard inputs; preflight returns BLOCKED outcomes."""


@dataclass(frozen=True, slots=True)
class rl_ExpectedTuple:
    rl_system_identifier: str
    rl_database: str
    rl_role: str
    rl_marker: str
    rl_expires_at: datetime
    rl_run_id: str


class rl_ExpectedTupleRegistry(Protocol):
    def get(self, rl_profile_id: str) -> rl_ExpectedTuple | None:
        """Read an expected tuple from a future external provisioner."""


class rl_InMemoryExpectedTupleRegistry:
    def __init__(self, rl_expected: Mapping[str, rl_ExpectedTuple]):
        self.rl_expected = dict(rl_expected)

    def get(self, rl_profile_id: str) -> rl_ExpectedTuple | None:
        return self.rl_expected.get(rl_profile_id)


@dataclass(frozen=True, slots=True, repr=False)
class rl_ObservedIdentity:
    rl_system_identifier: str
    rl_database: str
    rl_endpoint_host: str | None
    rl_endpoint_port: int | None
    rl_marker: str | None

    def __repr__(self) -> str:
        return "rl_ObservedIdentity(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class rl_GuardOutcome:
    rl_status: str
    rl_reason: str | None
    rl_evidence: dict[str, object] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"rl_GuardOutcome(rl_status={self.rl_status!r}, rl_reason={self.rl_reason!r})"


class rl_AsyncConnection(Protocol):
    async def execute(self, rl_statement):
        """Execute one read-only preflight statement."""


class rl_ConnectionFactory(Protocol):
    def __call__(self, rl_profile: rl_ProfileRecord):
        """Create one guard-owned connection for a resolved profile."""


def rl_json_digest(rl_value: object) -> str:
    rl_bytes = json.dumps(rl_value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(rl_bytes).hexdigest()


def rl_now_utc() -> datetime:
    return datetime.now(UTC)


def rl_redacted_guard_evidence(
    *,
    profile,
    expected: rl_ExpectedTuple | None,
    observed: rl_ObservedIdentity | None,
    run_id: str,
    role: str,
    reason: str | None,
    status: str = "BLOCKED",
    evidence_persisted: bool | None = None,
    original_reason: str | None = None,
) -> dict[str, object]:
    rl_observed_database = observed.rl_database if observed is not None else None
    rl_observed_port = observed.rl_endpoint_port if observed is not None else None
    rl_system_identifier_digest = (
        rl_digest(observed.rl_system_identifier)
        if observed is not None and isinstance(observed.rl_system_identifier, str)
        and observed.rl_system_identifier
        else None
    )
    rl_marker_digest = (
        rl_digest(observed.rl_marker)
        if observed is not None and isinstance(observed.rl_marker, str) and observed.rl_marker
        else None
    )
    rl_registry_digest = None
    if expected is not None and all(
        isinstance(rl_value, str)
        for rl_value in (
            expected.rl_system_identifier,
            expected.rl_database,
            expected.rl_role,
            expected.rl_marker,
            expected.rl_run_id,
        )
    ) and hasattr(expected.rl_expires_at, "isoformat"):
        rl_registry_digest = rl_json_digest(
            {
                "system_identifier_digest": rl_digest(expected.rl_system_identifier),
                "database_digest": rl_digest(expected.rl_database),
                "role": expected.rl_role,
                "marker_digest": rl_digest(expected.rl_marker),
                "expires_at": expected.rl_expires_at.isoformat(),
                "run_id": expected.rl_run_id,
            }
        )
    return {
        "guard_event_version": "a0.guard.v2",
        "status": status,
        "reason": reason,
        "original_reason": original_reason,
        "run_id": run_id,
        "role": role,
        "profile_digest": profile.rl_profile_digest if profile is not None else None,
        "configured_identity_redacted": (
            profile.rl_configured_identity_redacted if profile is not None else None
        ),
        "registry_tuple_digest": rl_registry_digest,
        "identity_digest_version": "a0.identity.v1",
        "system_identifier_digest": rl_system_identifier_digest,
        "observed_database": rl_observed_database,
        "endpoint_context_digest": (
            rl_json_digest(
                {
                    "configured_host": profile.rl_host if profile is not None else None,
                    "observed_host": observed.rl_endpoint_host if observed is not None else None,
                    "port": rl_observed_port,
                }
            )
            if observed is not None
            else None
        ),
        "observed_port": rl_observed_port,
        "marker_digest": rl_marker_digest,
        "expires_at": (
            expected.rl_expires_at.isoformat()
            if expected is not None and hasattr(expected.rl_expires_at, "isoformat")
            else None
        ),
        "command_template_digest": rl_digest("a0.disposable-target.preflight.v1"),
        "owner": "rl_guard_evidence_owner",
        "reviewer": "rl_database_safety_reviewer",
        "evidence_persisted": evidence_persisted,
    }


def rl_blocked(
    *,
    reason: str,
    profile,
    expected: rl_ExpectedTuple | None,
    observed: rl_ObservedIdentity | None,
    run_id: str,
    role: str,
    status: str = "BLOCKED",
    evidence_persisted: bool | None = None,
    original_reason: str | None = None,
) -> rl_GuardOutcome:
    return rl_finalize_guard_outcome(
        status=status,
        reason=reason,
        profile=profile,
        expected=expected,
        observed=observed,
        run_id=run_id,
        role=role,
        evidence_persisted=evidence_persisted,
        original_reason=original_reason,
    )


def rl_guard_event_id(rl_event: Mapping[str, object]) -> str:
    rl_payload = {
        rl_key: rl_value for rl_key, rl_value in rl_event.items() if rl_key != "guard_event_id"
    }
    return rl_json_digest(rl_payload)


def rl_finalize_guard_outcome(
    *,
    status: str,
    reason: str | None,
    profile,
    expected: rl_ExpectedTuple | None,
    observed: rl_ObservedIdentity | None,
    run_id: str,
    role: str,
    evidence_persisted: bool | None = None,
    original_reason: str | None = None,
) -> rl_GuardOutcome:
    rl_event = rl_redacted_guard_evidence(
        profile=profile,
        expected=expected,
        observed=observed,
        run_id=run_id,
        role=role,
        reason=reason,
        status=status,
        evidence_persisted=evidence_persisted,
        original_reason=original_reason,
    )
    return rl_finalize_guard_event(
        event=rl_event,
        status=status,
        reason=reason,
    )


def rl_finalize_guard_event(
    *,
    event: Mapping[str, object],
    status: str,
    reason: str | None,
) -> rl_GuardOutcome:
    """Finalize a safe guard event once, including its content-derived ID."""

    rl_event = {
        **dict(event),
        "guard_event_version": "a0.guard.v2",
        "status": status,
        "reason": reason,
        "owner": "rl_guard_evidence_owner",
        "reviewer": "rl_database_safety_reviewer",
    }
    rl_event["guard_event_id"] = rl_guard_event_id(rl_event)
    return rl_GuardOutcome(
        rl_status=status,
        rl_reason=reason,
        rl_evidence=rl_event,
    )


async def rl_close_connection(rl_connection: rl_AsyncConnection) -> None:
    raise rl_GuardError("connection_factory_contract")


async def rl_open_connection(rl_resource):
    if inspect.isawaitable(rl_resource):
        rl_resource = await rl_resource
    rl_enter = getattr(rl_resource, "__aenter__", None)
    rl_exit = getattr(rl_resource, "__aexit__", None)
    if rl_enter is None or rl_exit is None or not callable(rl_enter) or not callable(rl_exit):
        raise rl_GuardError("connection_factory_contract")
    rl_connection = rl_enter()
    if not inspect.isawaitable(rl_connection):
        raise rl_GuardError("connection_factory_contract")
    rl_connection = await rl_connection
    if rl_connection is None or not hasattr(rl_connection, "execute"):
        raise rl_GuardError("connection_factory_contract")
    return rl_connection, rl_resource


async def rl_release_connection(
    rl_connection: rl_AsyncConnection,
    rl_context,
) -> None:
    rl_exit = getattr(rl_context, "__aexit__", None)
    if rl_exit is None:
        raise rl_GuardError("connection_factory_contract")
    rl_result = rl_exit(None, None, None)
    if not inspect.isawaitable(rl_result):
        raise rl_GuardError("connection_factory_contract")
    await rl_result


def rl_caller_has_pg_override(rl_caller_env: Mapping[str, str] | None) -> bool:
    if not rl_caller_env:
        return False
    return any(rl_name.upper().startswith("PG") for rl_name in rl_caller_env)


async def rl_read_observed_identity(rl_connection: rl_AsyncConnection) -> rl_ObservedIdentity:
    # 为什么：一次只读查询绑定 database、endpoint、cluster identity 与 marker。
    rl_statement = """
        SELECT current_database(),
               inet_server_addr()::text,
               inet_server_port(),
               (pg_control_system()).system_identifier,
               current_setting('soymutdb_a0.disposable_marker', true)
    """
    rl_result = await rl_connection.execute(rl_statement)
    rl_row = rl_result.first()
    if rl_row is None:
        raise rl_GuardError("identity_query_empty")
    try:
        rl_database, rl_host, rl_port, rl_system_identifier, rl_marker = tuple(rl_row)
    except (TypeError, ValueError) as rl_error:
        raise rl_GuardError("identity_query_shape") from rl_error
    return rl_ObservedIdentity(
        rl_system_identifier=rl_system_identifier,
        rl_database=rl_database,
        rl_endpoint_host=rl_host,
        rl_endpoint_port=rl_port,
        rl_marker=rl_marker,
    )


async def rl_preflight_disposable_target(
    *,
    profile_id: str,
    role: str,
    run_id: str,
    profile_registry: rl_ProfileRegistry,
    expected_registry: rl_ExpectedTupleRegistry,
    connection: rl_AsyncConnection | None = None,
    connection_factory: rl_ConnectionFactory | None = None,
    evidence_path: Path | None = None,
    caller_env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> rl_GuardOutcome:
    """Validate one observed target without changing it or creating a live engine."""

    rl_profile = None
    rl_expected = None
    rl_observed = None
    rl_outcome: rl_GuardOutcome | None = None
    try:
        if rl_caller_has_pg_override(caller_env):
            rl_outcome = rl_blocked(
                reason="caller_environment_override",
                profile=None,
                expected=None,
                observed=None,
                run_id=run_id,
                role=role,
            )
        if rl_outcome is None:
            rl_profile = rl_prepare_pg_profile(
                profile_id=profile_id,
                registry=profile_registry,
                role=role,
                run_id=run_id,
            )
            rl_expected = expected_registry.get(profile_id)
            if rl_expected is None:
                rl_outcome = rl_blocked(
                    reason="registry_missing",
                    profile=rl_profile,
                    expected=None,
                    observed=None,
                    run_id=run_id,
                    role=role,
                )
            elif not isinstance(rl_expected, rl_ExpectedTuple):
                raise rl_GuardError("expected_tuple_contract")
            elif not all(
                isinstance(rl_value, str)
                for rl_value in (
                    rl_expected.rl_system_identifier,
                    rl_expected.rl_database,
                    rl_expected.rl_role,
                    rl_expected.rl_marker,
                    rl_expected.rl_run_id,
                )
            ) or not isinstance(rl_expected.rl_expires_at, datetime):
                raise rl_GuardError("expected_tuple_contract")
            else:
                rl_now = now or rl_now_utc()
                rl_expected_expiry = (
                    rl_expected.rl_expires_at.replace(tzinfo=UTC)
                    if rl_expected.rl_expires_at.tzinfo is None
                    else rl_expected.rl_expires_at
                )
                if rl_expected_expiry <= rl_now:
                    rl_outcome = rl_blocked(
                        reason="registry_expired",
                        profile=rl_profile,
                        expected=rl_expected,
                        observed=None,
                        run_id=run_id,
                        role=role,
                    )
                elif rl_expected.rl_run_id != run_id:
                    rl_outcome = rl_blocked(
                        reason="run_mismatch",
                        profile=rl_profile,
                        expected=rl_expected,
                        observed=None,
                        run_id=run_id,
                        role=role,
                    )
                elif rl_expected.rl_role != role:
                    rl_outcome = rl_blocked(
                        reason="role_mismatch",
                        profile=rl_profile,
                        expected=rl_expected,
                        observed=None,
                        run_id=run_id,
                        role=role,
                    )
                elif rl_expected.rl_database != rl_profile.rl_bare_database_name:
                    rl_outcome = rl_blocked(
                        reason="profile_database_mismatch",
                        profile=rl_profile,
                        expected=rl_expected,
                        observed=None,
                        run_id=run_id,
                        role=role,
                    )

        if rl_outcome is None:
            if connection is not None:
                raise rl_GuardError("connection_injection_forbidden")
            if connection_factory is None:
                raise rl_GuardError("connection_factory_required")
            rl_resource = connection_factory(rl_profile)
            rl_connection, rl_context = await rl_open_connection(rl_resource)
            try:
                try:
                    rl_observed = await rl_read_observed_identity(rl_connection)
                except rl_GuardError as rl_error:
                    rl_outcome = rl_blocked(
                        reason=str(rl_error),
                        profile=rl_profile,
                        expected=rl_expected,
                        observed=None,
                        run_id=run_id,
                        role=role,
                    )
            finally:
                try:
                    await rl_release_connection(rl_connection, rl_context)
                except BaseException as rl_close_error:
                    raise rl_GuardError("connection_cleanup_failure") from rl_close_error

        if rl_outcome is None and rl_observed is not None:
            rl_observed_reason = None
            if not rl_observed.rl_system_identifier:
                rl_observed_reason = "missing_system_identifier"
            elif not rl_observed.rl_database:
                rl_observed_reason = "missing_database"
            elif rl_observed.rl_database != rl_expected.rl_database:
                rl_observed_reason = "database_mismatch"
            elif rl_observed.rl_endpoint_host is None or rl_observed.rl_endpoint_port is None:
                rl_observed_reason = "missing_endpoint"
            elif rl_observed.rl_system_identifier != rl_expected.rl_system_identifier:
                rl_observed_reason = "system_identifier_mismatch"
            elif rl_observed.rl_marker is None:
                rl_observed_reason = "missing_marker"
            elif rl_observed.rl_marker != rl_expected.rl_marker:
                rl_observed_reason = "marker_mismatch"
            if rl_observed_reason is not None:
                rl_outcome = rl_blocked(
                    reason=rl_observed_reason,
                    profile=rl_profile,
                    expected=rl_expected,
                    observed=rl_observed,
                    run_id=run_id,
                    role=role,
                )
            else:
                rl_outcome = rl_finalize_guard_outcome(
                    status="READY",
                    reason=None,
                    profile=rl_profile,
                    expected=rl_expected,
                    observed=rl_observed,
                    run_id=run_id,
                    role=role,
                )
    except rl_GuardError as rl_error:
        rl_outcome = rl_blocked(
            reason=str(rl_error),
            profile=rl_profile,
            expected=rl_expected,
            observed=rl_observed,
            run_id=run_id,
            role=role,
        )
    except (ValueError, TypeError, AttributeError):
        rl_outcome = rl_blocked(
            reason="profile_or_identity_contract",
            profile=rl_profile,
            expected=rl_expected,
            observed=rl_observed,
            run_id=run_id,
            role=role,
        )
    except Exception:
        rl_outcome = rl_blocked(
            reason="connection_failure",
            profile=rl_profile,
            expected=rl_expected,
            observed=rl_observed,
            run_id=run_id,
            role=role,
        )

    if rl_outcome is None:
        rl_outcome = rl_blocked(
            reason="profile_or_identity_contract",
            profile=rl_profile,
            expected=rl_expected,
            observed=rl_observed,
            run_id=run_id,
            role=role,
        )

    if evidence_path is not None:
        rl_persisted_event = rl_finalize_guard_event(
            event=rl_outcome.rl_evidence,
            status=rl_outcome.rl_status,
            reason=rl_outcome.rl_reason,
        )
        rl_persisted_event.rl_evidence["evidence_persisted"] = True
        rl_persisted_event.rl_evidence["guard_event_id"] = rl_guard_event_id(
            rl_persisted_event.rl_evidence
        )
        try:
            Path(evidence_path).parent.mkdir(parents=True, exist_ok=True)
            with Path(evidence_path).open("a", encoding="utf-8") as rl_stream:
                rl_stream.write(json.dumps(rl_persisted_event.rl_evidence, sort_keys=True) + "\n")
            rl_outcome = rl_persisted_event
        except BaseException:
            rl_original_reason = rl_outcome.rl_reason
            rl_failed_event = dict(rl_outcome.rl_evidence)
            rl_failed_event["evidence_persisted"] = False
            rl_failed_event["original_reason"] = rl_original_reason
            rl_outcome = rl_finalize_guard_outcome(
                status="BLOCKED",
                reason="evidence_write_failure",
                profile=rl_profile,
                expected=rl_expected,
                observed=rl_observed,
                run_id=run_id,
                role=role,
                evidence_persisted=False,
                original_reason=rl_original_reason,
            )
    return rl_outcome


def rl_compare_observed_identity(
    rl_source: rl_ObservedIdentity,
    rl_restore: rl_ObservedIdentity,
) -> rl_GuardOutcome:
    # 为什么：hostname、IP 和 service alias 可能指向同一 cluster；只有实际 system identifier 加 current_database 才能证明 distinctness。
    rl_same_key = (
        rl_source.rl_system_identifier,
        rl_source.rl_database,
    ) == (
        rl_restore.rl_system_identifier,
        rl_restore.rl_database,
    )
    rl_evidence = {
        "identity_digest_version": "a0.identity.v1",
        "source_system_identifier_digest": rl_digest(rl_source.rl_system_identifier),
        "restore_system_identifier_digest": rl_digest(rl_restore.rl_system_identifier),
        "source_database_digest": rl_digest(rl_source.rl_database),
        "restore_database_digest": rl_digest(rl_restore.rl_database),
        "source_endpoint_context_digest": rl_json_digest(
            {"host": rl_source.rl_endpoint_host, "port": rl_source.rl_endpoint_port}
        ),
        "restore_endpoint_context_digest": rl_json_digest(
            {"host": rl_restore.rl_endpoint_host, "port": rl_restore.rl_endpoint_port}
        ),
    }
    return rl_finalize_guard_event(
        event=rl_evidence,
        status="BLOCKED" if rl_same_key else "READY",
        reason="same_observed_identity" if rl_same_key else None,
    )


class rl_SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _rl_message: str) -> None:
        raise SystemExit(2)


def rl_parse_args(rl_argv: list[str] | None = None) -> argparse.Namespace:
    rl_parser = rl_SafeArgumentParser(add_help=True)
    rl_selector = rl_parser.add_mutually_exclusive_group(required=True)
    rl_selector.add_argument("--profile-env")
    rl_selector.add_argument("--profile-id")
    rl_parser.add_argument("--role", required=True)
    rl_parser.add_argument("--run-id", required=True)
    rl_parser.add_argument("--evidence")
    return rl_parser.parse_args(rl_argv)


def rl_main(rl_argv: list[str] | None = None) -> int:
    rl_namespace = rl_parse_args(rl_argv)
    raise rl_GuardError("profile, registry, and connection must be injected")


if __name__ == "__main__":
    asyncio.run(rl_main())
