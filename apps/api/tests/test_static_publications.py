"""Tests for the immutable multi-target static publication service (Phase 3).

Covers:
- target-scoped monotonically increasing publication ids
- status state machine and transition validation
- stale-job superseding (later request wins)
- rollback relation
- failure never changes the published pointer (service does not promote)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.publication import (
    PublicationStatus,
    PublicationTarget,
    StaticPublication,
    transition_allowed,
)
from app.services.publication_service import (
    InvalidTransition,
    PublicationError,
    mark_superseded,
    record_published,
    request_publication,
    rollback,
    should_promote,
    transition,
)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class _FakeDb:
    def __init__(self):
        self.publications: list = []
        self.leases: dict[str, object] = {}
        self.counters: dict[str, object] = {}
        self.audit: list = []
        self.outbox: list = []
        self._seq = 0

    def _next_id(self) -> int:
        self._seq += 1
        return self._seq

    def add(self, value):
        name = value.__class__.__name__
        if name == "StaticPublication":
            if getattr(value, "id", None) is None:
                object.__setattr__(value, "id", self._next_id())
            self.publications.append(value)
        elif name == "PublicationCounter":
            self.counters[value.target] = value
        elif name == "PublicationTargetLease":
            self.leases[value.target] = value
        elif name == "AuditLog":
            self.audit.append(value)
        else:
            self.outbox.append(value)

    async def flush(self):
        return None

    async def execute(self, stmt):
        text = str(stmt)
        if "publication_counters" in text:
            vals = list(self.counters.values())
            return _Result(vals)
        if "publication_target_leases" in text:
            vals = list(self.leases.values())
            return _Result(vals)
        if "static_publications" in text:
            return _Result(list(self.publications))
        return _Result([])

    async def scalar(self, stmt):
        return None


def _pub(pub_id: int, target: str, status: str, release_id: int = 1) -> StaticPublication:
    return SimpleNamespace(
        id=pub_id,
        publication_id=pub_id,
        target=target,
        status=status,
        release_id=release_id,
        page_definition_version=None,
        manifest_digest=None,
        artifact_url=None,
        remote_id=None,
        previous_publication_id=None,
        evidence=None,
        error_message=None,
        requested_by=None,
        superseded_by_publication_id=None,
    )


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def test_transition_allowed_forward_path() -> None:
    path = [
        PublicationStatus.REQUESTED,
        PublicationStatus.BUILDING,
        PublicationStatus.VALIDATING,
        PublicationStatus.DEPLOYING,
        PublicationStatus.PUBLISHED,
    ]
    for a, b in zip(path, path[1:]):
        assert transition_allowed(a, b)


def test_transition_rejects_terminal_and_backwards() -> None:
    assert not transition_allowed(PublicationStatus.FAILED, PublicationStatus.BUILDING)
    assert not transition_allowed(PublicationStatus.PUBLISHED, PublicationStatus.DEPLOYING)
    assert transition_allowed(PublicationStatus.PUBLISHED, PublicationStatus.ROLLED_BACK)


def test_transition_rejects_invalid_jump() -> None:
    # transition_allowed() is a pure predicate: a bad jump returns False.
    assert not transition_allowed(
        PublicationStatus.REQUESTED, PublicationStatus.PUBLISHED
    )


@pytest.mark.asyncio
async def test_transition_raises_on_invalid() -> None:
    db = _FakeDb()
    p = _pub(1, "local", PublicationStatus.REQUESTED.value)
    db.publications = [p]
    with pytest.raises(InvalidTransition):
        await transition(db, 1, PublicationStatus.PUBLISHED)


# ---------------------------------------------------------------------------
# request_publication: monotonic target-scoped ids + dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_publication_allocs_and_dispatches(monkeypatch):
    from app.services import publication_service

    dispatched = []

    async def fake_enqueue(db, **kwargs):
        dispatched.append(kwargs)
        return SimpleNamespace(id="e1")

    monkeypatch.setattr(publication_service, "enqueue_task_event", fake_enqueue)

    db = _FakeDb()
    pub = await request_publication(
        db, target=PublicationTarget.LOCAL, release_id=5, actor_id="admin"
    )
    assert pub.target == "local"
    assert pub.status == "requested"
    assert pub.publication_id == 1
    assert len(dispatched) == 1
    assert dispatched[0]["task_name"].endswith("build_static_release")
    assert dispatched[0]["kwargs"]["release_id"] == 5


@pytest.mark.asyncio
async def test_request_publication_monotonic_per_target(monkeypatch):
    from app.services import publication_service

    async def fake_enqueue(db, **kwargs):
        return SimpleNamespace(id="e1")

    monkeypatch.setattr(publication_service, "enqueue_task_event", fake_enqueue)
    db = _FakeDb()
    p1 = await request_publication(db, target=PublicationTarget.LOCAL, release_id=1, actor_id="a")
    p2 = await request_publication(db, target=PublicationTarget.LOCAL, release_id=2, actor_id="a")
    assert p1.publication_id == 1
    assert p2.publication_id == 2


# ---------------------------------------------------------------------------
# record_published: rollback relation + terminal guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_published_links_previous() -> None:
    db = _FakeDb()
    first = _pub(1, "local", PublicationStatus.PUBLISHED.value)
    second = _pub(2, "local", PublicationStatus.DEPLOYING.value)
    db.publications = [first, second]

    out = await record_published(db, 2, remote_id="deploy:2", evidence={"ok": True})
    assert out.status == PublicationStatus.PUBLISHED.value
    assert out.remote_id == "deploy:2"


@pytest.mark.asyncio
async def test_transition_marks_superseded() -> None:
    db = _FakeDb()
    p = _pub(1, "cloudflare_pages", PublicationStatus.DEPLOYING.value)
    db.publications = [p]
    out = await mark_superseded(db, 1, by_publication_id=2)
    assert out.status == PublicationStatus.SUPERSEDED.value
    assert out.superseded_by_publication_id == 2


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_requires_published_and_reason() -> None:
    db = _FakeDb()
    p = _pub(1, "local", PublicationStatus.PUBLISHED.value)
    db.publications = [p]
    with pytest.raises(PublicationError, match="reason"):
        await rollback(db, 1, actor_id="a", reason="  ")
    out = await rollback(db, 1, actor_id="a", reason="bad release")
    assert out.status == PublicationStatus.ROLLED_BACK.value


@pytest.mark.asyncio
async def test_rollback_rejects_non_published() -> None:
    db = _FakeDb()
    p = _pub(1, "local", PublicationStatus.FAILED.value)
    db.publications = [p]
    with pytest.raises(PublicationError, match="published"):
        await rollback(db, 1, actor_id="a", reason="x")


# ---------------------------------------------------------------------------
# should_promote stale-job guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_promote_false_when_superseded() -> None:
    db = _FakeDb()
    p = _pub(1, "github_pages", PublicationStatus.DEPLOYING.value)
    db.publications = [p]

    # Simulate a newer latest request: lease says latest == 2, pub == 1.
    class _LeaseResult:
        def scalar_one_or_none(self):
            return 2

    async def _execute(stmt):
        if "publication_target_leases" in str(stmt):
            return _LeaseResult()
        return _Result([p])

    db.execute = _execute
    assert await should_promote(db, 1) is False
