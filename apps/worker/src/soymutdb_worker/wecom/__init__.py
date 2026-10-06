"""WeCom (企业微信) integration contracts and local policy — W5.

See ``README.md`` in this package for what is implemented, what is deliberately
unbound, and the confirmed official API contract.
"""

from .cli import CliResult, WecomCli
from .contracts import (
    BitableTransport,
    CallbackVerifier,
    DocumentSearchTransport,
    FieldWhitelist,
    FormTransport,
    InboundEnvelope,
    IntegrationUnverified,
    OutboundRecord,
    OutboundStatus,
    ReconciliationFinding,
    SubmissionDisposition,
    TenantBinding,
    Unverified,
)
from .outbox import DeliveryOutcome, OutboxProcessor, OutboxStore, reconcile
from .policy import (
    OutboundFieldDecision,
    PolicyRefusal,
    backoff_delay,
    check_source_domain,
    decide_outbound_fields,
    project_outbound_payload,
    redact,
    redact_mapping,
    resolve_tenant,
    should_retry,
    summarise_refusals,
)

__all__ = [
    "BitableTransport",
    "CallbackVerifier",
    "CliResult",
    "DeliveryOutcome",
    "DocumentSearchTransport",
    "FieldWhitelist",
    "FormTransport",
    "InboundEnvelope",
    "IntegrationUnverified",
    "OutboundFieldDecision",
    "OutboundRecord",
    "OutboundStatus",
    "OutboxProcessor",
    "OutboxStore",
    "PolicyRefusal",
    "ReconciliationFinding",
    "SubmissionDisposition",
    "TenantBinding",
    "Unverified",
    "WecomCli",
    "backoff_delay",
    "check_source_domain",
    "decide_outbound_fields",
    "project_outbound_payload",
    "reconcile",
    "redact",
    "redact_mapping",
    "resolve_tenant",
    "should_retry",
    "summarise_refusals",
]
