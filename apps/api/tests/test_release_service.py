from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.models.auth import AuditLog
from app.models.content import ReleaseStatus
from app.models.data_publishing import ImportStatus
from app.services.release_service import (
    ReleaseNotReady,
    mark_release_ready,
    publish_release,
    rollback_release,
    validate_release,
)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar_one(self):
        if not self.rows:
            raise LookupError("no row")
        return self.rows[0]

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class _FakeDb:
    def __init__(self, releases, datasets, links, pointer):
        self.releases = releases
        self.datasets = datasets
        self.links = links
        self.pointer = pointer
        self.audit: list[AuditLog] = []
        self.outbox = []

    @asynccontextmanager
    async def begin(self):
        yield

    async def execute(self, stmt):
        text = str(stmt)
        if "active_release" in text:
            return _Result([self.pointer])
        if "release_data_sets" in text:
            return _Result(
                [self.datasets[data_id] for rel_id, data_id in self.links if rel_id == 2]
            )
        if "FROM releases" in text:
            if "active_at <" in text:
                return _Result([self.releases[0]])
            if "releases.id" in text:
                return _Result([self.releases[1]])
            return _Result(
                sorted(
                    [r for r in self.releases if r.status == ReleaseStatus.PUBLISHED.value],
                    key=lambda r: r.active_at or 0,
                    reverse=True,
                )
            )
        return _Result([])

    def add(self, value):
        if isinstance(value, AuditLog):
            self.audit.append(value)
        else:
            self.outbox.append(value)

    async def flush(self):
        return None


def _release(release_id, status, active_at=None):
    return SimpleNamespace(
        id=release_id,
        status=status,
        manifest={"version": f"r{release_id}", "provenance": [{"sha256": "a" * 64}]},
        active_at=active_at,
        published_at=None,
        published_by=None,
        rolled_back_at=None,
        reason=None,
    )


@pytest.fixture
def fake_ready_db():
    first = _release(1, ReleaseStatus.PUBLISHED.value, 1)
    second = _release(2, ReleaseStatus.READY.value)
    dataset = SimpleNamespace(id=10, status=ImportStatus.READY.value)
    return _FakeDb([first, second], {10: dataset}, [(2, 10)], SimpleNamespace(id=1, release_id=1))


@pytest.fixture
def fake_not_ready_db():
    release = _release(2, ReleaseStatus.VALIDATED.value)
    dataset = SimpleNamespace(id=10, status=ImportStatus.QUEUED.value, source_objects=[])
    return _FakeDb(
        [_release(1, ReleaseStatus.PUBLISHED.value, 1), release],
        {10: dataset},
        [(2, 10)],
        SimpleNamespace(id=1, release_id=1),
    )


@pytest.mark.asyncio
async def test_validate_release_rejects_dataset_not_ready(fake_not_ready_db):
    with pytest.raises(ReleaseNotReady, match="all data sets must be ready"):
        await validate_release(fake_not_ready_db, release_id=2, actor_id="actor")


@pytest.mark.asyncio
async def test_ready_requires_jbrowse_blast_download_api_smoke(db_session):
    with pytest.raises(ReleaseNotReady, match="api"):
        await mark_release_ready(
            db_session,
            release_id=1,
            actor_id="actor",
            manifest={"version": "r1", "provenance": []},
            readiness={"jbrowse": True, "blast": True, "downloads": True, "api": False},
        )


@pytest.mark.asyncio
async def test_publish_changes_pointer_and_audit_atomically(fake_ready_db):
    published = await publish_release(
        fake_ready_db, release_id=2, actor_id="actor", reason="approved"
    )

    assert fake_ready_db.pointer.release_id == 2
    assert published.status == ReleaseStatus.PUBLISHED.value
    assert [entry.action for entry in fake_ready_db.audit] == ["release_published"]
    assert fake_ready_db.audit[0].old_value == {"active_release_id": 1}
    assert fake_ready_db.audit[0].new_value["active_release_id"] == 2


@pytest.mark.asyncio
async def test_rollback_requires_reason_and_restores_previous_pointer(fake_ready_db):
    await publish_release(fake_ready_db, release_id=2, actor_id="actor", reason="approved")
    restored, rolled = await rollback_release(
        fake_ready_db, release_id=2, actor_id="actor", reason="bad checksum"
    )

    assert restored.id == 1
    assert rolled.status == ReleaseStatus.ROLLED_BACK.value
    assert fake_ready_db.pointer.release_id == 1
    assert [entry.action for entry in fake_ready_db.audit] == [
        "release_published",
        "release_rolled_back",
    ]
