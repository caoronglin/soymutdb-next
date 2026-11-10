"""W5 local policy: field whitelist, tenant binding, redaction, retry.

These are the parts of the WeCom integration that make no outbound call, so
they are testable now while the tenant credentials and the unconfirmed
official contracts (see the package README) are still outstanding. A test here
is a claim about *our* rules only, never about the wire format, which nothing
in this repository currently pins.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from soymutdb_worker.wecom.contracts import (
    FieldWhitelist,
    InboundEnvelope,
    OutboundStatus,
    TenantBinding,
)
from soymutdb_worker.wecom.policy import (
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

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _whitelist(**overrides: object) -> FieldWhitelist:
    base: dict[str, object] = {
        "table_key": "tbl-1",
        "outbound_fields": frozenset({"title", "body", "owner_email"}),
        "personal_data_fields": frozenset({"owner_email"}),
    }
    base.update(overrides)
    return FieldWhitelist(**base)  # type: ignore[arg-type]


def _binding(**overrides: object) -> TenantBinding:
    base: dict[str, object] = {
        "tenant_key": "t-1",
        "external_account_id": "acct-1",
        "source_domain": "example.com",
        "approved": True,
    }
    base.update(overrides)
    return TenantBinding(**base)  # type: ignore[arg-type]


def _envelope(**overrides: object) -> InboundEnvelope:
    base: dict[str, object] = {
        "submission_id": "s-1",
        "tenant_key": "t-1",
        "source": "form",
        "received_at": _NOW,
        "source_domain": "example.com",
    }
    base.update(overrides)
    return InboundEnvelope(**base)  # type: ignore[arg-type]


class TestDecideOutboundFields:
    def test_unmapped_field_is_refused(self) -> None:
        decision = decide_outbound_fields({"title": "hello", "surprise": 1}, _whitelist())

        assert decision.allowed == frozenset({"title"})
        assert decision.refused == frozenset({"surprise"})

    def test_mapped_personal_field_needs_its_own_approval(self) -> None:
        """The two approvals are independent.

        A field that is both mapped and personal must be refused until the
        personal-data approval exists, otherwise adding it to the mapping would
        silently widen what leaves the building.
        """
        decision = decide_outbound_fields({"owner_email": "a@b.c"}, _whitelist())

        assert decision.allowed == frozenset()
        assert decision.refused_personal == frozenset({"owner_email"})

    def test_personal_field_is_allowed_once_approved(self) -> None:
        whitelist = _whitelist(
            approved_at=_NOW, approval_reference="AUD-2026-001",
        )
        decision = decide_outbound_fields({"owner_email": "a@b.c"}, whitelist)

        assert decision.allowed == frozenset({"owner_email"})
        assert decision.refused_personal == frozenset()

    def test_partial_approval_is_not_enough(self) -> None:
        """Both halves of the approval record are required.

        Recording a reference without a timestamp (or the reverse) is a partial
        record, and a partial record is not an approval.
        """
        assert (
            decide_outbound_fields(
                {"owner_email": "a@b.c"}, _whitelist(approval_reference="AUD-1")
            ).allowed
            == frozenset()
        )
        assert (
            decide_outbound_fields(
                {"owner_email": "a@b.c"}, _whitelist(approved_at=_NOW)
            ).allowed
            == frozenset()
        )

    def test_inconsistent_whitelist_refuses_rather_than_filtering(self) -> None:
        """A personal field outside the mapped set is a configuration error.

        Silently dropping it would hide the misconfiguration behind a working
        request, so the whitelist is rejected outright.
        """
        broken = _whitelist(outbound_fields=frozenset({"title"}))

        with pytest.raises(PolicyRefusal):
            decide_outbound_fields({"title": "x"}, broken)

    def test_is_clean_tracks_both_refusal_sets(self) -> None:
        assert decide_outbound_fields({"title": "x"}, _whitelist()).is_clean
        assert not decide_outbound_fields({"nope": 1}, _whitelist()).is_clean
        assert not decide_outbound_fields({"owner_email": "a@b.c"}, _whitelist()).is_clean


class TestProjectOutboundPayload:
    def test_an_approved_payload_is_returned_intact(self) -> None:
        whitelist = _whitelist(
            personal_data_fields=frozenset(),
        )
        payload = {"title": "hello", "body": "world"}

        assert project_outbound_payload(payload, whitelist) == payload

    def test_an_unmapped_field_raises_instead_of_being_dropped(self) -> None:
        """Projection is all-or-nothing, unlike the decision it mirrors.

        Returning a quietly reduced payload would let a caller treat a refusal
        as a success and queue an incomplete record, which is exactly what the
        outbox writer is supposed to prevent.
        """
        with pytest.raises(PolicyRefusal, match="unmapped fields"):
            project_outbound_payload({"title": "hello", "surprise": 1}, _whitelist())

    def test_an_unapproved_personal_field_raises(self) -> None:
        with pytest.raises(PolicyRefusal, match="personal-data fields"):
            project_outbound_payload({"owner_email": "a@b.c"}, _whitelist())


class TestResolveTenant:
    def test_known_approved_tenant_resolves(self) -> None:
        binding = _binding()

        assert resolve_tenant("t-1", {"t-1": binding}) is binding

    def test_absent_tenant_is_a_refusal_not_a_default(self) -> None:
        """Absence must never mean "the default tenant".

        A default would turn "the caller did not say who they are" into "the
        caller is whoever we guessed", which for an approval workflow is the
        difference between an audit trail and a forged one.
        """
        with pytest.raises(PolicyRefusal):
            resolve_tenant(None, {"t-1": _binding()})

    def test_empty_string_tenant_is_also_a_refusal(self) -> None:
        with pytest.raises(PolicyRefusal):
            resolve_tenant("", {"t-1": _binding()})

    def test_unknown_tenant_is_refused(self) -> None:
        with pytest.raises(PolicyRefusal):
            resolve_tenant("t-2", {"t-1": _binding()})

    def test_unapproved_binding_is_refused(self) -> None:
        with pytest.raises(PolicyRefusal):
            resolve_tenant("t-1", {"t-1": _binding(approved=False)})

    def test_binding_keyed_under_a_different_tenant_is_refused(self) -> None:
        """The mapping key and the binding's own key must agree.

        A binding filed under someone else's key is either a config mistake or
        a forged entry; both mean the lookup result cannot be trusted.
        """
        misfiled = _binding(tenant_key="t-9")

        with pytest.raises(PolicyRefusal):
            resolve_tenant("t-1", {"t-1": misfiled})


class TestCheckSourceDomain:
    def test_matching_domain_passes(self) -> None:
        check_source_domain(_envelope(), _binding())

    def test_foreign_domain_is_refused(self) -> None:
        with pytest.raises(PolicyRefusal):
            check_source_domain(_envelope(source_domain="attacker.test"), _binding())

    def test_a_correct_tenant_key_does_not_excuse_a_foreign_origin(self) -> None:
        """Tenant identity alone is not sufficient.

        A leaked credential replayed from another origin would otherwise pass
        every tenant check, which is the case this function exists for.
        """
        with pytest.raises(PolicyRefusal):
            check_source_domain(
                _envelope(tenant_key="t-1", source_domain="evil.test"), _binding()
            )

    def test_suffix_lookalike_is_refused(self) -> None:
        """A string suffix is not a domain match.

        ``evil-example.com`` ends with ``example.com`` as text but is a
        different registrable domain.
        """
        with pytest.raises(PolicyRefusal):
            check_source_domain(_envelope(source_domain="evil-example.com"), _binding())


#: The redactor keys on the credential's *name* (`access_token=`, `secret:`, …),
#: never on the value's shape. Assembling the probe from parts keeps a
#: credential-shaped literal out of the source tree — a scanner cannot tell a
#: redaction-test input from a leaked key, and it should not have to.
REDACTION_PROBE = "-".join(("probe", "value", "not", "a", "secret"))


class TestRedaction:
    @pytest.mark.parametrize(
        ("name", "separator"),
        [
            ("access_token", "="),
            ("secret", ": "),
            ("password", "="),
            ("api_key", "="),
            ("apikey", ": "),
        ],
    )
    def test_credential_shaped_values_are_stripped(self, name: str, separator: str) -> None:
        raw = f"{name}{separator}{REDACTION_PROBE}"
        redacted = redact(raw)

        assert REDACTION_PROBE not in redacted, raw

    def test_ordinary_text_survives_intact(self) -> None:
        message = "processed 42 rows for release v4"

        assert redact(message) == message

    def test_a_short_token_shaped_word_is_not_mangled(self) -> None:
        """The pattern requires a value long enough to be a credential.

        Without that floor, ordinary prose containing a word like ``key=1``
        would be rewritten and the log would stop being readable.
        """
        assert redact("key=1") == "key=1"

    def test_mapping_redacts_by_key_name(self) -> None:
        redacted = redact_mapping({"api_key": REDACTION_PROBE, "release": "v4"})

        # `redact_mapping` returns `dict[str, object]` because it passes
        # non-strings through untouched; assert the exact replacement instead of
        # a substring search so the expected value is stated, not implied.
        assert redacted["api_key"] == "***redacted***"
        assert redacted["release"] == "v4"

    def test_mapping_redacts_inside_free_text_values(self) -> None:
        redacted = redact_mapping({"note": f"access_token={REDACTION_PROBE}"})

        note = redacted["note"]
        assert isinstance(note, str)
        assert REDACTION_PROBE not in note
        assert "***redacted***" in note

    def test_non_string_values_pass_through_untouched(self) -> None:
        assert redact_mapping({"rows": 42, "flag": True}) == {"rows": 42, "flag": True}


class TestBackoffDelay:
    def test_attempt_below_one_is_a_caller_error(self) -> None:
        """Attempt 0 is a bug, not a scheduling hint.

        A zero-second backoff turns a transient outage into a hot loop.
        """
        with pytest.raises(ValueError):
            backoff_delay(0)

    def test_delay_doubles_with_each_attempt(self) -> None:
        assert [backoff_delay(n) for n in (1, 2, 3)] == [1.0, 2.0, 4.0]

    def test_delay_is_capped(self) -> None:
        assert backoff_delay(20) == backoff_delay(50) == 300.0


class TestShouldRetry:
    def test_a_retryable_status_retries_below_the_ceiling(self) -> None:
        assert should_retry(OutboundStatus.FAILED, attempt=2, max_attempts=3)
        assert not should_retry(OutboundStatus.FAILED, attempt=3, max_attempts=3)

    @pytest.mark.parametrize(
        "status", [OutboundStatus.SUCCEEDED, OutboundStatus.DEAD]
    )
    def test_terminal_statuses_are_never_retried(self, status: OutboundStatus) -> None:
        assert not should_retry(status, attempt=1, max_attempts=3)


class TestSummariseRefusals:
    def test_output_is_bounded(self) -> None:
        summary = summarise_refusals([f"f{i}" for i in range(50)])

        assert summary.count(",") <= 7
        assert "42 more" in summary

    def test_newlines_cannot_be_smuggled_into_a_log_line(self) -> None:
        """A refused key is attacker-influenced text.

        Truncation bounds the length but never prevented a key from forging a
        second log entry, so the control characters have to go.
        """
        summary = summarise_refusals(["evil\nINFO: forged entry"])

        assert "\n" not in summary
        assert "\r" not in summary

    def test_ordinary_keys_are_unchanged(self) -> None:
        assert summarise_refusals(["owner_email", "title"]) == "owner_email, title"
