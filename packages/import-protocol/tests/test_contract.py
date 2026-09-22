"""Contract tests for the shared import protocol (ADR-0005).

These pin the invariants both the API control plane and the Celery worker rely
on. If either side changes a semantic input, a transition, or the publish
visibility rule, this fails — before a retry can silently double-count facts or
leak a partial write.
"""

from __future__ import annotations

import pytest

from soymutdb_import_protocol import (
    ALLOWED_MANIFEST_TRANSITIONS,
    FINGERPRINT_INPUT_FIELDS,
    ImportManifestStatus,
    can_transition,
    compute_import_fingerprint,
    is_portal_visible_status,
)
from soymutdb_import_protocol.fingerprint import compute_import_fingerprint as fn

BASE = {
    "source_sha256": "a" * 64,
    "release_id": 1,
    "assembly_id": 2,
    "importer_version": "imp-1",
    "schema_version": "sch-1",
    "normalization_version": "norm-1",
    "config_hash": "cfg-1",
}


def test_fingerprint_is_stable_and_64_hex() -> None:
    fp = compute_import_fingerprint(**BASE)
    assert fp == fn(**BASE)
    assert fp == compute_import_fingerprint(**BASE)
    assert len(fp) == 64
    int(fp, 16)


@pytest.mark.parametrize("field", FINGERPRINT_INPUT_FIELDS)
def test_every_semantic_input_changes_the_fingerprint(field: str) -> None:
    base = compute_import_fingerprint(**BASE)
    changed = dict(BASE)
    changed[field] = changed[field] + "x" if isinstance(changed[field], str) else changed[field] + 1
    assert compute_import_fingerprint(**changed) != base


def test_field_order_is_the_documented_contract() -> None:
    # FINGERPRINT_INPUT_FIELDS documents the ordered semantic inputs; any
    # reordering is a protocol change and must fail here, not in production.
    assert FINGERPRINT_INPUT_FIELDS == (
        "source_sha256",
        "release_id",
        "assembly_id",
        "importer_version",
        "schema_version",
        "normalization_version",
        "config_hash",
    )


def test_happy_path_transitions_are_permitted() -> None:
    assert can_transition("created", ImportManifestStatus.PARSING)
    assert can_transition("parsing", ImportManifestStatus.WRITING)
    assert can_transition("writing", ImportManifestStatus.VERIFYING)
    assert can_transition("verifying", ImportManifestStatus.PUBLISHED)


def test_any_non_published_may_fail() -> None:
    for state in ("created", "parsing", "writing", "verifying"):
        assert can_transition(state, ImportManifestStatus.FAILED)


def test_retry_resumes_only_from_created_or_failed() -> None:
    assert can_transition("failed", ImportManifestStatus.CREATED)
    assert not can_transition("published", ImportManifestStatus.CREATED)


def test_illegal_skips_are_rejected() -> None:
    assert not can_transition("created", ImportManifestStatus.PUBLISHED)
    assert not can_transition("parsing", ImportManifestStatus.PUBLISHED)
    # PUBLISHED is terminal.
    assert ALLOWED_MANIFEST_TRANSITIONS[ImportManifestStatus.PUBLISHED] == frozenset()


def test_unknown_current_state_is_rejected() -> None:
    assert not can_transition("bogus", ImportManifestStatus.PARSING)


def test_only_published_is_portal_visible() -> None:
    assert is_portal_visible_status("published")
    for state in ("created", "parsing", "writing", "verifying", "failed"):
        assert not is_portal_visible_status(state)
    assert not is_portal_visible_status("bogus")
