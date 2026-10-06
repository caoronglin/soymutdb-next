"""Local policy enforcement for the WeCom integration — W5.

Everything here is a decision this codebase owns: which fields may leave, when
personal data may leave, which tenant an inbound request belongs to, and what
a credential looks like in a log line. None of it depends on a WeCom endpoint,
so all of it is implemented rather than stubbed — these are exactly the rules
that must hold *before* any transport is bound, and a stubbed rule is worse
than no rule because it reads as coverage.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .contracts import (
    FieldWhitelist,
    InboundEnvelope,
    OutboundStatus,
    TenantBinding,
)


class PolicyRefusal(Exception):
    """A request was refused by a local policy. Nothing was sent."""


# --------------------------------------------------------------------------------------
# Outbound field policy
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OutboundFieldDecision:
    allowed: frozenset[str]
    refused: frozenset[str]
    refused_personal: frozenset[str]

    @property
    def is_clean(self) -> bool:
        """True when nothing was refused, by either rule.

        A personal-data refusal counts. It is a refusal of the same request,
        and reading this as "the payload had no problems" would let a caller
        treat an unapproved personal field as a clean bill of health.
        """
        return not self.refused and not self.refused_personal


def decide_outbound_fields(
    payload: Mapping[str, object], whitelist: FieldWhitelist
) -> OutboundFieldDecision:
    """Reduce a payload to the approved field set, or explain the refusal.

    The plan separates two approvals and this function keeps them separate. A
    field absent from ``outbound_fields`` is structurally unmapped. A field that
    *is* mapped but also carries personal data without the separate personal
    -data approval is refused even so — otherwise adding a field to the
    mapping would silently widen what leaves the building.
    """
    if whitelist.rejects_personal_data():
        raise PolicyRefusal(
            f"field whitelist for {whitelist.table_key!r} is inconsistent: personal "
            f"data fields {sorted(whitelist.personal_data_fields)} are not all "
            f"within the mapped fields {sorted(whitelist.outbound_fields)}"
        )

    personal_approved = (
        whitelist.approval_reference is not None and whitelist.approved_at is not None
    )

    allowed: set[str] = set()
    refused: set[str] = set()
    refused_personal: set[str] = set()

    for key, value in payload.items():
        if key not in whitelist.outbound_fields:
            refused.add(key)
            continue
        if key in whitelist.personal_data_fields and not personal_approved:
            refused_personal.add(key)
            continue
        allowed.add(key)

    return OutboundFieldDecision(
        allowed=frozenset(allowed),
        refused=frozenset(refused),
        refused_personal=frozenset(refused_personal),
    )


def project_outbound_payload(
    payload: Mapping[str, object], whitelist: FieldWhitelist
) -> dict[str, object]:
    """Return only the approved fields, or refuse.

    Used by the outbox writer so that a rejected payload never reaches a queue
    in the first place, rather than being queued and then refused at send time.
    """
    decision = decide_outbound_fields(payload, whitelist)
    if decision.refused_personal:
        raise PolicyRefusal(
            f"refusing to send personal-data fields {sorted(decision.refused_personal)} "
            f"for {whitelist.table_key!r} without a recorded personal-data approval"
        )
    if decision.refused:
        raise PolicyRefusal(
            f"refusing to send unmapped fields {sorted(decision.refused)} for "
            f"{whitelist.table_key!r}"
        )
    return {key: payload[key] for key in decision.allowed}


# --------------------------------------------------------------------------------------
# Inbound tenant policy
# --------------------------------------------------------------------------------------


def resolve_tenant(
    claimed_tenant: str | None, bindings: Mapping[str, TenantBinding]
) -> TenantBinding:
    """Resolve an inbound request to exactly one approved tenant.

    Absence is a refusal, not a default. The plan requires a tenant mismatch to
    be rejected, and a default tenant would turn "caller did not say who they
    are" into "caller is whoever we guessed" — which for an approval workflow
    is the difference between an audit trail and a forged one.
    """
    if not claimed_tenant:
        raise PolicyRefusal("inbound request named no tenant; refusing to guess one")
    binding = bindings.get(claimed_tenant)
    if binding is None:
        raise PolicyRefusal(f"inbound request named unknown tenant {claimed_tenant!r}")
    if binding.tenant_key != claimed_tenant:
        raise PolicyRefusal(
            f"tenant binding mismatch: claimed {claimed_tenant!r}, bound to "
            f"{binding.tenant_key!r}"
        )
    if not binding.approved:
        raise PolicyRefusal(
            f"tenant {claimed_tenant!r} is not approved for inbound access "
            f"(reference: {binding.approval_reference or 'none'})"
        )
    return binding


def check_source_domain(envelope: InboundEnvelope, binding: TenantBinding) -> None:
    """Refuse an inbound request whose origin domain is not the bound one.

    Tenant identity alone is not sufficient: a leaked credential replayed from
    another origin would otherwise pass.
    """
    if envelope.source_domain != binding.source_domain:
        raise PolicyRefusal(
            f"source domain mismatch for tenant {binding.tenant_key!r}: "
            f"{envelope.source_domain!r} != {binding.source_domain!r}"
        )


# --------------------------------------------------------------------------------------
# Credential handling
# --------------------------------------------------------------------------------------

# Matches anything that looks like a bearer/bot/secret value in free text.
_SECRET_PATTERN = re.compile(
    r"(?i)\b(?:qyapiaccess_token|access_token|secret|corpsecret|api[-_]?key|password)"
    r"\b\s*[:=]?\s*[\"']?([A-Za-z0-9_\-]{8,})[\"']?"
)
_REDACTED = "***redacted***"


def redact(text: str) -> str:
    """Strip credential-shaped values out of anything headed for a log or an error.

    Applied at the boundary rather than at each call site, because a secret that
    reaches a log has already leaked and the call site is always the one that
    forgets.
    """
    return _SECRET_PATTERN.sub(
        lambda m: f"{m.group(0).split(':')[0].split('=')[0]}=[{_REDACTED}]", text
    )


def redact_mapping(values: Mapping[str, object]) -> dict[str, object]:
    """Redact a mapping by key, for structured error payloads."""
    sensitive = ("token", "secret", "password", "key", "cookie", "authorization")
    out: dict[str, object] = {}
    for name, value in values.items():
        if any(marker in name.lower() for marker in sensitive):
            out[name] = _REDACTED
        elif isinstance(value, str):
            out[name] = redact(value)
        else:
            out[name] = value
    return out


# --------------------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------------------


def backoff_delay(attempt: int, *, base: float = 1.0, ceiling: float = 300.0) -> float:
    """Exponential backoff with a ceiling, for retry scheduling.

    The plan requires rate-limit backoff but the limits themselves are
    unconfirmed, so this stays a pure function of the attempt count: the shape
    of the policy is ours, only the constants are pending.
    """
    if attempt < 1:
        raise ValueError(f"attempt must be >= 1, got {attempt}")
    return min(base * (2 ** (attempt - 1)), ceiling)


def should_retry(status: OutboundStatus, attempt: int, *, max_attempts: int) -> bool:
    """Retry policy for the outbox.

    Dead-lettering is a decision, not an exhaustion side effect, so the caller
    has to ask. That keeps the threshold in one auditable place instead of
    scattered across the retry loop.
    """
    if status in (OutboundStatus.SUCCEEDED, OutboundStatus.DEAD):
        return False
    return attempt < max_attempts


# Field names reach this function from a decoded payload, so a newline in a key
# would let the key forge an extra line in whatever log consumes the message.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def summarise_refusals(keys: Iterable[str], *, limit: int = 8) -> str:
    """A bounded, log-safe key list for an error message.

    Untrusted field names come from a payload, so they are handled two ways. The
    list is truncated, because an error string echoing an unbounded
    attacker-controlled list is a denial-of-service on the log pipeline. And
    control characters are stripped, because a key containing a newline could
    otherwise forge a second log entry — truncation alone never prevented that.
    """
    ordered = sorted(_CONTROL_CHARS.sub(" ", key) for key in keys)
    if len(ordered) <= limit:
        return ", ".join(ordered)
    return f"{', '.join(ordered[:limit])} (+{len(ordered) - limit} more)"
