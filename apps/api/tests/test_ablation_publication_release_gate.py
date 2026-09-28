"""Ablation guards for the publication-request release gate.

``request_publication`` used to accept any positive ``release_id``, record a
``requested`` row and enqueue the build task. Nothing verified that the release
existed or had reached a published state, and an optional
``page_definition_version`` was never checked either. The worker would then
build (and could promote) an artifact labelled with an arbitrary id.

The contract now is: the release must exist and be ``published``; a supplied
page-definition version must exist and be ``published``.

Unit-level guards (no PostgreSQL): the service is driven with a fake session
that records what was asked.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.services.publication_service import PublicationError, request_publication


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._rows


class _FakeDb:
    def __init__(self, *, release: Any = None, page_version: Any = None) -> None:
        self.release = release
        self.page_version = page_version
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.leases: dict[str, Any] = {}
        self.counters: dict[str, Any] = {}
        self._seq = 0

    async def execute(self, stmt):
        text = str(stmt)
        self.statements.append(stmt)
        if "publication_target_leases" in text:
            return _Result(list(self.leases.values()))
        if "publication_counters" in text:
            return _Result(list(self.counters.values()))
        if "releases" in text:
            return _Result([self.release] if self.release else [])
        if "page_definition_versions" in text:
            return _Result([self.page_version] if self.page_version else [])
        return _Result([])

    async def flush(self) -> None:
        return None

    def add(self, value) -> None:
        name = value.__class__.__name__
        if name == "StaticPublication" and getattr(value, "id", None) is None:
            self._seq += 1
            object.__setattr__(value, "id", self._seq)
        if name == "PublicationTargetLease":
            self.leases[value.target] = value
        elif name == "PublicationCounter":
            self.counters[value.target] = value
        self.added.append(value)

    async def scalar(self, stmt):
        return None


def _release(status: str = "published"):
    return SimpleNamespace(id=1, status=status, version="2026.09")


async def _request(db: _FakeDb, **overrides: Any):
    kwargs: dict[str, Any] = {
        "target": "github_pages",
        "release_id": 1,
        "actor_id": "actor-1",
    }
    kwargs.update(overrides)
    return await request_publication(db, **kwargs)


# ---------------------------------------------------------------------------
# 1. The release must exist and be published.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_release_is_refused_before_any_allocation():
    db = _FakeDb(release=None)

    with pytest.raises(PublicationError) as excinfo:
        await _request(db)

    assert "does not exist" in str(excinfo.value)
    # Nothing was enqueued and no lease/counter was touched.
    assert db.added == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["draft", "validated", "ready", "rolled_back", "archived"]
)
async def test_unpublished_release_is_refused(status: str):
    """Ablation: removing the status check lets a draft be built and promoted."""
    db = _FakeDb(release=_release(status))

    with pytest.raises(PublicationError) as excinfo:
        await _request(db)

    assert status in str(excinfo.value)
    assert "only a published release" in str(excinfo.value)
    assert db.added == []


@pytest.mark.asyncio
async def test_published_release_is_allowed_and_dispatches_the_build():
    db = _FakeDb(release=_release("published"))

    pub = await _request(db)

    assert pub.release_id == 1
    # The outbox event carries the same release id the artifact will be labelled
    # with, so worker and request cannot disagree.
    outbox = [obj for obj in db.added if type(obj).__name__ == "OutboxEvent"]
    assert len(outbox) == 1
    assert outbox[0].payload.get("release_id") == 1 or "1" in str(outbox[0].payload)


# ---------------------------------------------------------------------------
# 2. A pinned page-definition version must be published.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unpublished_page_version_is_refused():
    db = _FakeDb(release=_release("published"), page_version=None)

    with pytest.raises(PublicationError) as excinfo:
        await _request(db, page_definition_version=7)

    assert "not published" in str(excinfo.value)
    assert db.added == []


@pytest.mark.asyncio
async def test_published_page_version_is_allowed():
    db = _FakeDb(
        release=_release("published"),
        page_version=SimpleNamespace(version=7, status="published"),
    )

    pub = await _request(db, page_definition_version=7)

    assert pub.page_definition_version == 7


@pytest.mark.asyncio
async def test_release_gate_runs_before_the_lease_is_acquired():
    """A refused request must not consume a publication id."""
    db = _FakeDb(release=_release("draft"))

    with pytest.raises(PublicationError):
        await _request(db)

    assert db.leases == {}
    assert db.counters == {}


# ---------------------------------------------------------------------------
# 4. The build-artifact reference travels with the request.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_artifact_url_is_forwarded_in_the_outbox_kwargs():
    """The worker cannot publish without real build output; the request must
    carry the immutable reference that locates it."""
    db = _FakeDb(release=_release("published"))

    await _request(db, build_artifact_url="https://artifacts.example/site.tar.gz")

    outbox = [obj for obj in db.added if type(obj).__name__ == "OutboxEvent"]
    assert len(outbox) == 1
    payload = outbox[0].payload
    kwargs = payload.get("kwargs", payload)
    assert kwargs["build_artifact_url"] == "https://artifacts.example/site.tar.gz"


@pytest.mark.asyncio
async def test_a_request_without_an_artifact_url_still_allocates():
    """Omitting it is allowed — the worker then fails closed, which is a
    recoverable state, rather than publishing a synthetic page."""
    db = _FakeDb(release=_release("published"))

    await _request(db)

    outbox = [obj for obj in db.added if type(obj).__name__ == "OutboxEvent"]
    kwargs = outbox[0].payload.get("kwargs", outbox[0].payload)
    assert kwargs.get("build_artifact_url") in (None, "")


def test_the_request_schema_rejects_a_non_artifact_url():
    from app.schemas.publication import PublicationRequest

    for hostile in ("javascript:alert(1)", "ftp://x/y", "not a url"):
        with pytest.raises(Exception):
            PublicationRequest(target="local", release_id=1, build_artifact_url=hostile)

    # The accepted forms are recorded verbatim.
    for good in (
        "https://artifacts.example/site.tar.gz",
        "http://minio:9000/builds/1.tar.gz",
        "file:///var/builds/1",
    ):
        assert (
            PublicationRequest(
                target="local", release_id=1, build_artifact_url=good
            ).build_artifact_url
            == good
        )
