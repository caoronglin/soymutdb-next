"""Pure async unit contracts for the A0 disposable-target identity guard."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from tools.a0.rl_disposable_target import (
    rl_ExpectedTuple,
    rl_InMemoryExpectedTupleRegistry,
    rl_ObservedIdentity,
    rl_compare_observed_identity,
    rl_preflight_disposable_target,
)
from tools.a0.rl_prepare_pg_profile import rl_InMemoryProfileRegistry, rl_ProfileSpec


class rl_Result:
    def __init__(self, rl_row):
        self.rl_row = rl_row

    def first(self):
        return self.rl_row


class rl_Connection:
    def __init__(self, rl_row):
        self.rl_row = rl_row
        self.rl_queries: list[str] = []
        self.rl_closed = False

    async def execute(self, rl_statement):
        self.rl_queries.append(str(rl_statement))
        return rl_Result(self.rl_row)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_rl_args):
        self.rl_closed = True
        return False


class rl_ConnectionFactory:
    def __init__(self, rl_connection: rl_Connection):
        self.rl_connection = rl_connection
        self.rl_profiles = []

    def __call__(self, rl_profile):
        self.rl_profiles.append(rl_profile)
        return self.rl_connection


class rl_BareConnection:
    def __init__(self):
        self.rl_queries = 0
        self.rl_closes = 0

    async def execute(self, _rl_statement):
        self.rl_queries += 1
        return rl_Result(None)

    async def close(self):
        self.rl_closes += 1


class rl_CountingContextConnection:
    def __init__(self, rl_row, *, rl_query_error: BaseException | None = None):
        self.rl_row = rl_row
        self.rl_query_error = rl_query_error
        self.rl_enter_count = 0
        self.rl_exit_count = 0
        self.rl_query_count = 0

    async def __aenter__(self):
        self.rl_enter_count += 1
        return self

    async def __aexit__(self, *_rl_args):
        self.rl_exit_count += 1
        return False

    async def execute(self, _rl_statement):
        self.rl_query_count += 1
        if self.rl_query_error is not None:
            raise self.rl_query_error
        return rl_Result(self.rl_row)


def rl_canonical_digest(rl_event: dict[str, object], rl_id_field: str) -> str:
    rl_payload = {
        rl_key: rl_value for rl_key, rl_value in rl_event.items() if rl_key != rl_id_field
    }
    rl_bytes = json.dumps(rl_payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(rl_bytes).hexdigest()


def rl_make_profile_registry() -> rl_InMemoryProfileRegistry:
    rl_spec = rl_ProfileSpec(
        rl_profile_id="profile-a0",
        rl_host="localhost",
        rl_port=5432,
        rl_user="a0_guard",
        rl_database="synthetic_a0",
        rl_role="schema",
        rl_run_id="run-a0",
        rl_secret_handle="raw-password",
    )
    return rl_InMemoryProfileRegistry({"profile-a0": rl_spec})


def rl_make_expected_registry(
    *,
    rl_system_identifier: str = "cluster-a0",
    rl_database: str = "synthetic_a0",
    rl_role: str = "schema",
    rl_marker: str = "opaque-marker-a0",
    rl_expires_at: datetime | None = None,
    rl_run_id: str = "run-a0",
) -> rl_InMemoryExpectedTupleRegistry:
    rl_expected = rl_ExpectedTuple(
        rl_system_identifier=rl_system_identifier,
        rl_database=rl_database,
        rl_role=rl_role,
        rl_marker=rl_marker,
        rl_expires_at=rl_expires_at or datetime.now(UTC) + timedelta(minutes=10),
        rl_run_id=rl_run_id,
    )
    return rl_InMemoryExpectedTupleRegistry({"profile-a0": rl_expected})


def rl_make_connection(
    *,
    rl_database: str = "synthetic_a0",
    rl_host: str | None = "127.0.0.1",
    rl_port: int | None = 5432,
    rl_system_identifier: str | None = "cluster-a0",
    rl_marker: str | None = "opaque-marker-a0",
) -> rl_Connection:
    return rl_Connection(
        (
            rl_database,
            rl_host,
            rl_port,
            rl_system_identifier,
            rl_marker,
        )
    )


def rl_make_connection_factory(**rl_kwargs) -> tuple[rl_ConnectionFactory, rl_Connection]:
    rl_connection = rl_make_connection(**rl_kwargs)
    return rl_ConnectionFactory(rl_connection), rl_connection


@pytest.mark.asyncio
async def test_preflight_reads_identity_and_emits_digest_only_evidence(tmp_path) -> None:
    rl_connection_factory, rl_connection = rl_make_connection_factory()
    rl_outcome = await rl_preflight_disposable_target(
        profile_id="profile-a0",
        role="schema",
        run_id="run-a0",
        profile_registry=rl_make_profile_registry(),
        expected_registry=rl_make_expected_registry(),
        connection_factory=rl_connection_factory,
        evidence_path=tmp_path / "guard.jsonl",
    )

    assert rl_outcome.rl_status == "READY"
    assert "current_database" in rl_connection.rl_queries[0]
    assert "inet_server_addr" in rl_connection.rl_queries[0]
    assert "inet_server_port" in rl_connection.rl_queries[0]
    assert "pg_control_system" in rl_connection.rl_queries[0]
    assert "soymutdb_a0.disposable_marker" in rl_connection.rl_queries[0]

    rl_evidence = json.dumps(rl_outcome.rl_evidence, ensure_ascii=False)
    assert "cluster-a0" not in rl_evidence
    assert "opaque-marker-a0" not in rl_evidence
    assert "raw-password" not in rl_evidence
    assert "postgresql://" not in rl_evidence
    assert rl_outcome.rl_evidence["identity_digest_version"] == "a0.identity.v1"
    assert rl_outcome.rl_evidence["system_identifier_digest"].startswith("sha256:")
    assert rl_outcome.rl_evidence["marker_digest"].startswith("sha256:")
    assert rl_connection_factory.rl_profiles[0].rl_profile_id == "profile-a0"
    assert rl_connection.rl_closed is True

    rl_file_text = (tmp_path / "guard.jsonl").read_text()
    assert "cluster-a0" not in rl_file_text
    assert "opaque-marker-a0" not in rl_file_text
    assert json.loads(rl_file_text) == rl_outcome.rl_evidence
    assert rl_outcome.rl_evidence["status"] == "READY"
    assert rl_outcome.rl_evidence["guard_event_id"] == rl_canonical_digest(
        rl_outcome.rl_evidence, "guard_event_id"
    )
    assert rl_outcome.rl_evidence["owner"] == "rl_guard_evidence_owner"


@pytest.mark.asyncio
async def test_bare_factory_resource_is_blocked_before_query_or_close() -> None:
    rl_bare_connection = rl_BareConnection()

    rl_outcome = await rl_preflight_disposable_target(
        profile_id="profile-a0",
        role="schema",
        run_id="run-a0",
        profile_registry=rl_make_profile_registry(),
        expected_registry=rl_make_expected_registry(),
        connection_factory=lambda _rl_profile: rl_bare_connection,
    )

    assert rl_outcome.rl_status == "BLOCKED"
    assert rl_outcome.rl_reason == "connection_factory_contract"
    assert rl_bare_connection.rl_queries == 0
    assert rl_bare_connection.rl_closes == 0


@pytest.mark.asyncio
async def test_context_factory_enters_and_exits_once_when_query_fails() -> None:
    rl_connection = rl_CountingContextConnection(
        None, rl_query_error=RuntimeError("query failure must not escape")
    )

    rl_outcome = await rl_preflight_disposable_target(
        profile_id="profile-a0",
        role="schema",
        run_id="run-a0",
        profile_registry=rl_make_profile_registry(),
        expected_registry=rl_make_expected_registry(),
        connection_factory=lambda _rl_profile: rl_connection,
    )

    assert rl_outcome.rl_status == "BLOCKED"
    assert rl_outcome.rl_reason == "connection_failure"
    assert rl_connection.rl_enter_count == 1
    assert rl_connection.rl_exit_count == 1
    assert rl_connection.rl_query_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rl_connection_kwargs,rl_expected_kwargs,rl_reason",
    [
        ({"rl_system_identifier": None}, {}, "missing_system_identifier"),
        ({"rl_database": "wrong_db"}, {}, "database_mismatch"),
        ({"rl_marker": None}, {}, "missing_marker"),
        ({"rl_marker": "wrong-marker"}, {}, "marker_mismatch"),
        ({}, {"rl_system_identifier": "wrong-cluster"}, "system_identifier_mismatch"),
        ({}, {"rl_expires_at": datetime.now(UTC) - timedelta(seconds=1)}, "registry_expired"),
        ({}, {"rl_run_id": "other-run"}, "run_mismatch"),
        ({}, {"rl_role": "other-role"}, "role_mismatch"),
    ],
)
async def test_preflight_failures_are_fail_closed(
    rl_connection_kwargs, rl_expected_kwargs, rl_reason
) -> None:
    rl_connection_factory, rl_connection = rl_make_connection_factory(**rl_connection_kwargs)
    rl_outcome = await rl_preflight_disposable_target(
        profile_id="profile-a0",
        role="schema",
        run_id="run-a0",
        profile_registry=rl_make_profile_registry(),
        expected_registry=rl_make_expected_registry(**rl_expected_kwargs),
        connection_factory=rl_connection_factory,
    )

    assert rl_outcome.rl_status == "BLOCKED"
    assert rl_outcome.rl_reason == rl_reason
    if rl_reason == "missing_system_identifier":
        assert rl_connection.rl_closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rl_name",
    ["PGSERVICE", "PGOPTIONS", "PGPASSWORD", "pghost", "PGPORT", "pguser", "PGDATABASE", "PGPASSFILE", "PGAPPNAME"],
)
async def test_preflight_rejects_caller_profile_overrides_before_connection(rl_name: str) -> None:
    rl_connection_factory, rl_connection = rl_make_connection_factory()
    rl_outcome = await rl_preflight_disposable_target(
        profile_id="profile-a0",
        role="schema",
        run_id="run-a0",
        profile_registry=rl_make_profile_registry(),
        expected_registry=rl_make_expected_registry(),
        connection_factory=rl_connection_factory,
        caller_env={rl_name: "caller-value"},
    )

    assert rl_outcome.rl_status == "BLOCKED"
    assert rl_outcome.rl_reason == "caller_environment_override"
    assert rl_connection.rl_queries == []
    assert rl_connection_factory.rl_profiles == []


@pytest.mark.asyncio
async def test_preflight_closes_factory_connection_when_identity_query_fails() -> None:
    rl_connection_factory, rl_connection = rl_make_connection_factory(rl_system_identifier=None)

    rl_outcome = await rl_preflight_disposable_target(
        profile_id="profile-a0",
        role="schema",
        run_id="run-a0",
        profile_registry=rl_make_profile_registry(),
        expected_registry=rl_make_expected_registry(),
        connection_factory=rl_connection_factory,
    )

    assert rl_outcome.rl_status == "BLOCKED"
    assert rl_outcome.rl_reason == "missing_system_identifier"
    assert rl_connection.rl_closed is True


@pytest.mark.asyncio
async def test_preflight_binds_profile_database_before_factory_call() -> None:
    rl_connection_factory, _ = rl_make_connection_factory()

    rl_outcome = await rl_preflight_disposable_target(
        profile_id="profile-a0",
        role="schema",
        run_id="run-a0",
        profile_registry=rl_make_profile_registry(),
        expected_registry=rl_make_expected_registry(rl_database="other_database"),
        connection_factory=rl_connection_factory,
    )

    assert rl_outcome.rl_status == "BLOCKED"
    assert rl_outcome.rl_reason == "profile_database_mismatch"
    assert rl_connection_factory.rl_profiles == []


@pytest.mark.asyncio
async def test_evidence_write_failure_blocks_ready_outcome(tmp_path) -> None:
    rl_connection_factory, _ = rl_make_connection_factory()
    rl_evidence_path = tmp_path / "evidence-dir"
    rl_evidence_path.mkdir()

    rl_outcome = await rl_preflight_disposable_target(
        profile_id="profile-a0",
        role="schema",
        run_id="run-a0",
        profile_registry=rl_make_profile_registry(),
        expected_registry=rl_make_expected_registry(),
        connection_factory=rl_connection_factory,
        evidence_path=rl_evidence_path,
    )

    assert rl_outcome.rl_status == "BLOCKED"
    assert rl_outcome.rl_reason == "evidence_write_failure"
    assert rl_outcome.rl_evidence["status"] == "BLOCKED"
    assert rl_outcome.rl_evidence["reason"] == "evidence_write_failure"
    assert rl_outcome.rl_evidence["guard_event_id"] == rl_canonical_digest(
        rl_outcome.rl_evidence, "guard_event_id"
    )


@pytest.mark.asyncio
async def test_evidence_write_failure_preserves_precise_block_reason(tmp_path) -> None:
    rl_connection_factory, _ = rl_make_connection_factory(rl_system_identifier=None)
    rl_evidence_path = tmp_path / "evidence-dir"
    rl_evidence_path.mkdir()

    rl_outcome = await rl_preflight_disposable_target(
        profile_id="profile-a0",
        role="schema",
        run_id="run-a0",
        profile_registry=rl_make_profile_registry(),
        expected_registry=rl_make_expected_registry(),
        connection_factory=rl_connection_factory,
        evidence_path=rl_evidence_path,
    )

    assert rl_outcome.rl_status == "BLOCKED"
    assert rl_outcome.rl_reason == "evidence_write_failure"
    assert rl_outcome.rl_evidence["status"] == "BLOCKED"
    assert rl_outcome.rl_evidence["reason"] == "evidence_write_failure"
    assert rl_outcome.rl_evidence["original_reason"] == "missing_system_identifier"


def test_aliases_with_same_observed_identity_are_blocked() -> None:
    rl_source = rl_ObservedIdentity(
        rl_system_identifier="cluster-a0",
        rl_database="synthetic_a0",
        rl_endpoint_host="localhost",
        rl_endpoint_port=5432,
        rl_marker="marker-source",
    )
    rl_restore = rl_ObservedIdentity(
        rl_system_identifier="cluster-a0",
        rl_database="synthetic_a0",
        rl_endpoint_host="127.0.0.1",
        rl_endpoint_port=5432,
        rl_marker="marker-restore",
    )

    rl_outcome = rl_compare_observed_identity(rl_source, rl_restore)

    assert rl_outcome.rl_status == "BLOCKED"
    assert rl_outcome.rl_reason == "same_observed_identity"
    assert rl_outcome.rl_evidence["status"] == "BLOCKED"
    assert rl_outcome.rl_evidence["guard_event_id"] == rl_canonical_digest(
        rl_outcome.rl_evidence, "guard_event_id"
    )
    assert "cluster-a0" not in json.dumps(rl_outcome.rl_evidence)
    assert "marker-source" not in json.dumps(rl_outcome.rl_evidence)


def test_different_observed_cluster_or_database_can_continue() -> None:
    rl_source = rl_ObservedIdentity(
        rl_system_identifier="cluster-a0",
        rl_database="synthetic_a0",
        rl_endpoint_host="service-source",
        rl_endpoint_port=5432,
        rl_marker="marker-source",
    )
    rl_restore = rl_ObservedIdentity(
        rl_system_identifier="cluster-b0",
        rl_database="synthetic_restore",
        rl_endpoint_host="10.0.0.2",
        rl_endpoint_port=5432,
        rl_marker="marker-restore",
    )

    rl_outcome = rl_compare_observed_identity(rl_source, rl_restore)

    assert rl_outcome.rl_status == "READY"
    assert rl_outcome.rl_evidence["status"] == "READY"
    assert rl_outcome.rl_evidence["guard_event_id"] == rl_canonical_digest(
        rl_outcome.rl_evidence, "guard_event_id"
    )
    assert rl_outcome.rl_evidence["source_system_identifier_digest"].startswith("sha256:")
    assert rl_outcome.rl_evidence["restore_system_identifier_digest"].startswith("sha256:")
