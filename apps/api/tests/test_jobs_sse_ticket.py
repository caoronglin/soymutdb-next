"""Single-use SSE ticket tests (D5).

The job event stream cannot use an ``Authorization`` header from the browser,
so ``GET /api/v1/jobs/events`` accepts ``?ticket=``.  The ticket replaces the
access token in that position: nginx logs ``$request`` including the query
string, so a token in the URL is a live credential in an access log.

Covers:
- issue → redeem returns the bound user id; the second redemption of the same
  ticket returns ``None`` (a replay is 401 at the endpoint);
- a malformed ticket never reaches the store;
- an unreachable store fails closed with 503 for both issue and redeem, so no
  ticket is handed out and no stream is authorized without single-use proof;
- ``POST /api/v1/jobs/sse-ticket`` returns ``{ticket, expires_in}`` with a TTL
  of at most 60 seconds and a ``private, no-store`` response.
"""

from __future__ import annotations

import uuid

import pytest
from starlette.responses import Response

from app.core.exceptions import ServiceUnavailableError
from app.services import sse_ticket
from app.services.sse_ticket import SSE_TICKET_TTL_SECONDS, issue_ticket, redeem_ticket


class FakeTicketStore:
    """Minimal async Redis double: ``SET ... EX`` plus atomic ``GETDEL``."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}
        self.calls: list[str] = []

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.calls.append("set")
        self.values[key] = value
        self.ttls[key] = ex
        return True

    async def getdel(self, key: str) -> str | None:
        self.calls.append("getdel")
        return self.values.pop(key, None)


class UnavailableStore:
    async def set(self, *_args, **_kwargs):
        raise ConnectionError("redis is unavailable")

    async def getdel(self, *_args, **_kwargs):
        raise ConnectionError("redis is unavailable")


@pytest.fixture()
def store(monkeypatch) -> FakeTicketStore:
    fake = FakeTicketStore()
    monkeypatch.setattr(sse_ticket, "get_redis", lambda: fake)
    return fake


def test_ticket_ttl_is_within_the_contract_ceiling() -> None:
    """A ticket must not outlive the stream handshake it exists for."""
    assert 0 < SSE_TICKET_TTL_SECONDS <= 60


@pytest.mark.asyncio
async def test_ticket_is_bound_to_the_issuing_user(store: FakeTicketStore) -> None:
    user_id = uuid.uuid4()

    ticket = await issue_ticket(user_id)

    assert ticket in {key.removeprefix("sse:ticket:") for key in store.values}
    assert store.ttls[f"sse:ticket:{ticket}"] == SSE_TICKET_TTL_SECONDS
    assert await redeem_ticket(ticket) == user_id
    assert "getdel" in store.calls, "redemption must be the atomic single-use read"


@pytest.mark.asyncio
async def test_replayed_ticket_is_rejected(store: FakeTicketStore) -> None:
    user_id = uuid.uuid4()
    ticket = await issue_ticket(user_id)

    assert await redeem_ticket(ticket) == user_id
    assert await redeem_ticket(ticket) is None


@pytest.mark.asyncio
async def test_unknown_or_expired_ticket_is_rejected(store: FakeTicketStore) -> None:
    """An entry that expired out of the store reads exactly like a replay."""
    never_issued = "A" * 43

    assert await redeem_ticket(never_issued) is None
    assert store.calls == ["getdel"]


@pytest.mark.asyncio
async def test_malformed_ticket_never_reaches_the_store(monkeypatch) -> None:
    def _no_store():
        raise AssertionError("a malformed ticket must not become a cache lookup")

    monkeypatch.setattr(sse_ticket, "get_redis", _no_store)

    for malformed in ("", "short", "=" * 43, "A" * 44, "A" * 42 + "!"):
        assert await redeem_ticket(malformed) is None


@pytest.mark.asyncio
async def test_unavailable_store_fails_closed_on_issue(monkeypatch) -> None:
    monkeypatch.setattr(sse_ticket, "get_redis", lambda: UnavailableStore())

    with pytest.raises(ServiceUnavailableError):
        await issue_ticket(uuid.uuid4())


@pytest.mark.asyncio
async def test_unavailable_store_fails_closed_on_redeem(monkeypatch) -> None:
    monkeypatch.setattr(sse_ticket, "get_redis", lambda: UnavailableStore())

    with pytest.raises(ServiceUnavailableError):
        await redeem_ticket("A" * 43)


@pytest.mark.asyncio
async def test_ticket_endpoint_returns_a_single_use_credential(
    store: FakeTicketStore,
) -> None:
    """``POST /jobs/sse-ticket`` is the only way to obtain a stream ticket."""
    from app.api.v1.jobs import create_sse_ticket

    user = _FakeUser(uuid.uuid4())
    response = Response()

    payload = await create_sse_ticket(response, user)  # type: ignore[arg-type]

    assert payload.expires_in == SSE_TICKET_TTL_SECONDS
    assert payload.expires_in <= 60
    assert response.headers["Cache-Control"] == "private, no-store"
    assert await redeem_ticket(payload.ticket) == user.id
    assert await redeem_ticket(payload.ticket) is None


class _FakeUser:
    """Only the identity is read by the ticket exchange."""

    def __init__(self, user_id: uuid.UUID) -> None:
        self.id = user_id
