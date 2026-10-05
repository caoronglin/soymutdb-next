"""Contracts for the WeCom (企业微信) integration — W5.

## Why this module exists, and why it holds no HTTP client

The audited plan (`docs/aegis/plans/2026-10-02-audited-optimization-execution.md`
§W5) requires four capabilities — Bitable sync, form intake, inbound callbacks
and document search — and it states the precondition plainly: the concrete
product, official API, tenant authorisation, service account, rate limits and
SDK versions are **not yet confirmed**. The same section forbids the failure
mode this file is built to prevent: writing "integration complete" without
credentials.

So the split is deliberate:

* everything that is a *local policy or state machine* lives here and in
  `policy.py` / `outbox.py`, fully implemented, because none of it depends on
  an endpoint we have not seen;
* everything that would touch a WeCom or Tencent Docs endpoint is a
  `Protocol` plus an explicitly unverified implementation that refuses to run.

`UnverifiedIntegrationError` is therefore not a bug state. It is the honest
answer to "this is wired but not bound", and it is what keeps a half-built
integration from being mistaken for a working one.

## Naming discipline

No method here names a real WeCom endpoint, parameter or payload field. Those
names are the things the plan says must be confirmed first, and inventing them
would bake a guess into the type system, where it is much harder to notice than
in a comment. Transport-specific concerns are raised, not answered: see
`PendingConfirmation` in `README.md` for the full list.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

# --------------------------------------------------------------------------------------
# Unverified state
# --------------------------------------------------------------------------------------


class IntegrationUnverified(RuntimeError):
    """Raised when an unconfirmed WeCom capability is actually invoked.

    Distinct from a transport or permission error on purpose. A caller that
    catches this knows nothing was attempted, no request left the process and
    no state changed — so a disabled integration degrades exactly like the
    existing best-effort group robot, instead of surfacing a 500.
    """


class Unverified:
    """The single implementation every unconfirmed capability resolves to.

    Callable, awaitable and context-manageable so that it can stand in for a
    real client without the caller needing to know which it got. Any attribute
    that is not explicitly defined raises the same error.
    """

    __slots__ = ("_capability",)

    def __init__(self, capability: str) -> None:
        object.__setattr__(self, "_capability", capability)

    def _refuse(self, member: str) -> IntegrationUnverified:
        return IntegrationUnverified(
            f"{self._capability}.{member} is not bound: the WeCom product, API "
            f"surface, tenant authorisation and rate limits are unconfirmed. See "
            f"soymutdb_worker/wecom/README.md. No request was attempted."
        )

    def __getattr__(self, member: str) -> Unverified:
        if member.startswith("__") and member.endswith("__"):
            raise AttributeError(member)
        return Unverified(f"{self._capability}.{member}")

    def __call__(self, *args: object, **kwargs: object) -> IntegrationUnverified:
        raise self._refuse("__call__")

    def __repr__(self) -> str:
        return f"<Unverified {object.__getattribute__(self, '_capability')}>"


# --------------------------------------------------------------------------------------
# Shared value objects
# --------------------------------------------------------------------------------------


class OutboundStatus(StrEnum):
    """Lifecycle of one outbox record.

    ``DEAD`` is terminal and requires an operator: the plan requires dead
    letters to be replayable, not silently dropped, and it forbids the queue
    from growing without bound when a remote rejects a payload.
    """

    PENDING = "pending"
    INFLIGHT = "inflight"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"


class SubmissionDisposition(StrEnum):
    """What an inbound form submission resolved to.

    ``DUPLICATE`` is a success, not a failure: the plan requires submission-id
    de-duplication, and a replayed webhook must not create a second record or
    an error the sender would retry forever.
    """

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class TenantBinding:
    """Maps one inbound request to the tenant that is allowed to answer it.

    The plan requires tenant mismatch to be a refusal, so this is resolved
    before any payload is parsed. An anonymous caller that names no tenant
    cannot be silently upgraded to a default one.
    """

    tenant_key: str
    external_account_id: str
    source_domain: str
    approved: bool = False
    approved_at: datetime | None = None
    approval_reference: str | None = None


@dataclass(frozen=True)
class OutboundRecord:
    """One row of the transactional outbox.

    ``idempotency_key`` is the deduplication anchor across retries, and
    ``object_version`` is what makes out-of-order delivery detectable: a
    remote write carrying an older version must not overwrite a newer one.
    """

    idempotency_key: str
    capability: str
    tenant_key: str
    payload: dict[str, object]
    object_version: int
    status: OutboundStatus = OutboundStatus.PENDING
    attempts: int = 0
    last_error: str | None = None
    created_at: datetime | None = None
    dead_letter_reason: str | None = None


@dataclass(frozen=True)
class FieldWhitelist:
    """The approved outbound field set for one Bitable table.

    Two approvals are kept apart on purpose. ``outbound_fields`` is the
    structural mapping; ``personal_data_fields`` is the subset that carries
    personal information, which the plan gates behind a *separate* approval.
    A field present in the first but not the second is refused rather than
    sent, so widening the mapping cannot quietly widen the personal-data
    surface.
    """

    table_key: str
    outbound_fields: frozenset[str]
    personal_data_fields: frozenset[str] = frozenset()
    approved_at: datetime | None = None
    approval_reference: str | None = None

    def rejects_personal_data(self) -> bool:
        return not (self.personal_data_fields <= self.outbound_fields)


@dataclass(frozen=True)
class InboundEnvelope:
    """A decoded inbound request, before any business logic runs.

    Holds only what the transport can know for certain. Signature material and
    decryption keys stay in the receiving service and are never placed on this
    object, per the plan's rule that inbound and outbound keys do not share.
    """

    submission_id: str
    tenant_key: str
    source: str
    received_at: datetime
    fields: dict[str, object] = field(default_factory=dict)
    idempotency_key: str = ""


# --------------------------------------------------------------------------------------
# Capability contracts
# --------------------------------------------------------------------------------------


@runtime_checkable
class BitableTransport(Protocol):
    """Remote Bitable (智能表格) transport. Unconfirmed surface."""

    def push(self, record: OutboundRecord) -> str: ...
    def fetch(self, table_key: str, since: datetime | None) -> list[dict[str, object]]: ...


@runtime_checkable
class FormTransport(Protocol):
    """Remote form-definition transport. Unconfirmed surface."""

    def describe(self, form_key: str) -> dict[str, object]: ...


@runtime_checkable
class CallbackVerifier(Protocol):
    """Signature/decryption verification for inbound callbacks.

    The plan requires the official parameters and samples to be confirmed
    before this is bound, and requires negative cases — bad signature, replay,
    duplicate, malformed body, tenant mismatch — to be demonstrable. A
    placeholder that returned ``True`` would make all of those pass vacuously.
    """

    def verify(self, headers: dict[str, str], body: bytes) -> InboundEnvelope: ...


@runtime_checkable
class DocumentSearchTransport(Protocol):
    """Enterprise document search. Unconfirmed surface and unconfirmed ACL model."""

    def search(
        self, query: str, tenant_key: str, document_ids: list[str]
    ) -> list[dict[str, object]]: ...


# --------------------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconciliationFinding:
    """One divergence found by the periodic reconciliation pass.

    The plan requires a scheduled reconciliation, not only retries: a record
    can diverge without any call failing, for example when an operator edits a
    Bitable row directly. Findings are data, not exceptions, so a partial
    mismatch is reportable rather than fatal.
    """

    table_key: str
    local_object_id: str
    remote_record_id: str | None
    divergence: str
    local_version: int
    observed_remote_version: int | None = None
