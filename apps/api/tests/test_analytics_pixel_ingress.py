"""HTTP ingress and store-boundary contracts for the analytics pixel.

These tests mount the real ``analytics`` router on a minimal in-process FastAPI
app. Nothing here needs a database, Redis, Docker or testcontainers: the
background-task arguments are captured by a spy service, and the session the
real service opens is replaced by a recorder that replays canned result rows.

That is a deliberate scope limit, not a full integration proof:

* the store spies assert the *bound parameters* the service would send, not what
  a real PostgreSQL server stores — ``test_analytics_native_postgres.py`` is
  where the statements run against a real database;
* the *read* fakes return fixed rows, so the summary tests cover the
  sanitisation of labels the service receives, not query planning.

Authorization is checked through the real dependency overrides of the router, so
the administrator guard exercised here is the same guard production uses.

Sentinels
---------
Every raw value a caller could smuggle in — an internal numeric id, a public id,
a v4/v5 gene symbol, a percentage, a full URL, a search term, a referrer URL, a
widget label, a user-agent string and a forwarded address — is unique enough to
be searched for in the captured task arguments, the recorded insert row and the
response body. A sentinel appearing anywhere it should not is a failure.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.api.v1 import analytics as analytics_module
from app.api.v1.deps import get_current_user
from app.core.exceptions import (
    AuthenticationError,
    SoyMutDBError,
    soy_mut_db_exception_handler,
    validation_exception_handler,
)
from app.services.analytics_privacy import (
    OTHER_PAGE_TEMPLATE,
    PAGE_TEMPLATE_OR_OTHER,
    REFERRER_CATEGORIES,
    REFERRER_DIRECT,
    REFERRER_OTHER,
    REFERRER_SEARCH,
    classify_referrer,
    normalize_analytics_page,
)
from app.services.analytics_repository import (
    EVENT_COLUMNS,
    EVENTS_TABLE,
    WEB_VITAL_COLUMNS,
    WEB_VITALS_TABLE,
)
from app.services.analytics_service import TRACKING_PIXEL, AnalyticsService

# --------------------------------------------------------------------------- #
# Sentinels
# --------------------------------------------------------------------------- #

INTERNAL_ID = "918273645"
PUBLIC_ID = "MUT-000918273645"
GENE_V4 = "Glyma01G000100"
GENE_V5 = "Glyma.01G000100"
PERCENTAGE = "37.5percent"
SEARCH_TERM = "sentinelqueryterm"
WIDGET_LABEL = "sentinelwidgetlabel"
HOST_SENTINEL = "sentinel-host.example"
CREDENTIAL_SENTINEL = "sentinel-password-42"
EMAIL_SENTINEL = "sentinel.user@example.invalid"
USER_AGENT_SENTINEL = "SentinelBrowser/9.9 (sentinel-agent-marker)"
IP_SENTINEL = "203.0.113.77"

ALL_SENTINELS = (
    INTERNAL_ID,
    PUBLIC_ID,
    GENE_V4,
    GENE_V5,
    PERCENTAGE,
    SEARCH_TERM,
    WIDGET_LABEL,
    HOST_SENTINEL,
    CREDENTIAL_SENTINEL,
    EMAIL_SENTINEL,
    USER_AGENT_SENTINEL,
    IP_SENTINEL,
)

SESSION_COOKIE = analytics_module.SESSION_COOKIE_NAME

RAW_URL = (
    f"https://user:{CREDENTIAL_SENTINEL}@{HOST_SENTINEL}:8443"
    f"/mutants/{INTERNAL_ID}?q={SEARCH_TERM}&pct={PERCENTAGE}#frag"
)
RAW_REferrer = f"https://{EMAIL_SENTINEL}:{CREDENTIAL_SENTINEL}@{HOST_SENTINEL}/s?q={SEARCH_TERM}"


def assert_no_sentinels(blob: Any) -> None:
    """Fail if any raw sentinel survives in *blob* (dict/list/str)."""
    text = json.dumps(blob, default=str) if not isinstance(blob, str) else blob
    for sentinel in ALL_SENTINELS:
        assert sentinel not in text, f"raw value leaked: {sentinel!r} in {text!r}"


# --------------------------------------------------------------------------- #
# Spies
# --------------------------------------------------------------------------- #


class BackgroundSpy:
    """Stands in for ``AnalyticsService`` and records queued task arguments."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.vitals: list[dict[str, Any]] = []

    async def record_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)

    async def record_web_vital(self, **kwargs: Any) -> None:
        self.vitals.append(kwargs)

    @property
    def queued(self) -> list[dict[str, Any]]:
        return [*self.events, *self.vitals]


class QueryResult:
    """Minimal stand-in for a SQLAlchemy result."""

    def __init__(self, rows: list[tuple[Any, Any]]) -> None:
        self._rows = rows

    def scalar(self) -> Any:
        return self._rows[0][0] if self._rows else None

    def all(self) -> list[tuple[Any, Any]]:
        return list(self._rows)


#: The two clauses the fake applies, so a truncated query is visible to a test.
_ORDER_BY_COUNT_DESC = re.compile(r"ORDER BY\s+cnt\s+DESC", re.IGNORECASE)
_LIMIT_CLAUSE = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)


class SessionSpy:
    """Stands in for the async session a real service opens.

    It records every statement with the parameters bound to it and replays
    canned rows keyed by a distinctive fragment of the statement text.
    """

    def __init__(self, responses: dict[str, list[tuple[Any, Any]]] | None = None) -> None:
        self.responses = responses or {}
        self.statements: list[dict[str, Any]] = []
        self.commits = 0
        self.fail = False

    async def __aenter__(self) -> SessionSpy:
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False

    async def execute(self, statement: Any, parameters: Any = None) -> QueryResult:
        sql = str(statement)
        self.statements.append({"sql": sql, "parameters": dict(parameters or {})})
        if self.fail:
            raise RuntimeError("analytics store unavailable")
        for fragment, rows in self.responses.items():
            if fragment in sql:
                return QueryResult(self._apply_server_window(sql, rows))
        return QueryResult([])

    async def commit(self) -> None:
        self.commits += 1

    @staticmethod
    def _apply_server_window(sql: str, rows: list[tuple[Any, Any]]) -> list[tuple[Any, Any]]:
        """Apply the query's own ``ORDER BY cnt DESC`` / ``LIMIT`` to canned rows.

        A fake that ignored ``LIMIT`` could not tell a query that returns every
        stored label from one that truncates before the service normalises it,
        so a regression for that truncation would pass for the wrong reason.
        This applies exactly those two clauses and nothing else: it is a test
        double for them, not a database emulation, and it makes no claim about
        any other SQL behaviour.
        """
        if _ORDER_BY_COUNT_DESC.search(sql):
            rows = sorted(rows, key=lambda row: row[1], reverse=True)
        limit = _LIMIT_CLAUSE.search(sql)
        if limit:
            rows = rows[: int(limit.group(1))]
        return rows

    @property
    def sql_text(self) -> str:
        return " ".join(statement["sql"] for statement in self.statements)

    def insert_params(self, table: str) -> list[dict[str, Any]]:
        """Return the bound parameters of every insert into *table*."""
        return [
            statement["parameters"]
            for statement in self.statements
            if statement["sql"].startswith(f"INSERT INTO {table}")
        ]


def _service_with(spy: SessionSpy) -> AnalyticsService:
    """Return a real service whose sessions are the recorder."""
    return AnalyticsService(session_factory=lambda: spy)


# --------------------------------------------------------------------------- #
# App fixtures
# --------------------------------------------------------------------------- #


def _build_app(service: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(analytics_module.router)
    app.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.state.analytics_service = service
    return app


@pytest.fixture
def spy() -> BackgroundSpy:
    return BackgroundSpy()


@pytest.fixture
def client(monkeypatch, spy: BackgroundSpy) -> TestClient:
    monkeypatch.setattr(analytics_module, "analytics", spy)
    return TestClient(_build_app(spy))


@pytest.fixture
def spy_session() -> SessionSpy:
    return SessionSpy()


@pytest.fixture
def session(spy_session: SessionSpy) -> SessionSpy:
    return spy_session


@pytest.fixture
def store_client(monkeypatch, spy_session: SessionSpy) -> TestClient:
    """Client whose real ``AnalyticsService`` writes into the session spy.

    The router resolves the module-level ``analytics`` service at call time, so
    the service under test is installed there; only the session it opens is
    replaced.
    """
    monkeypatch.setattr(analytics_module, "analytics", _service_with(spy_session))
    return TestClient(_build_app(analytics_module.analytics))


def _admin_user() -> SimpleNamespace:
    return SimpleNamespace(role_rel=None, is_superuser=True)


def _researcher_user() -> SimpleNamespace:
    return SimpleNamespace(role_rel=SimpleNamespace(name="researcher"), is_superuser=False)


def _deny_anonymous() -> None:
    raise AuthenticationError("Missing or invalid Authorization header")


def _summary_app(
    monkeypatch: pytest.MonkeyPatch,
    session: SessionSpy,
    user: Any = _deny_anonymous,
) -> FastAPI:
    """Build the summary app with a recorded session and a stubbed login.

    *user* may be a user object or a dependency callable; a callable that raises
    stands in for "no valid credentials".
    """
    monkeypatch.setattr(analytics_module, "analytics", _service_with(session))
    app = _build_app(analytics_module.analytics)
    app.dependency_overrides[get_current_user] = user if callable(user) else (lambda: user)
    return app


# --------------------------------------------------------------------------- #
# GET pixel: privacy at the ingress
# --------------------------------------------------------------------------- #


def test_get_pixel_stores_templates_never_raw_values(
    client: TestClient, spy: BackgroundSpy
) -> None:
    response = client.get(
        "/track.gif",
        params={
            "event": "search",
            "page": f"/mutants/{INTERNAL_ID}",
            "path": RAW_URL,
            "q": SEARCH_TERM,
            "widget": WIDGET_LABEL,
            "ref": "https://www.google.com/search?q=" + SEARCH_TERM,
            "source": RAW_URL,
            "duration": "1500",
        },
        headers={
            "User-Agent": USER_AGENT_SENTINEL,
            "X-Forwarded-For": IP_SENTINEL,
            "Referer": RAW_REferrer,
        },
    )

    assert response.status_code == 200
    assert response.content == TRACKING_PIXEL
    assert len(spy.events) == 1
    event = spy.events[0]
    assert_no_sentinels(event)

    # Only canonical templates reach the store.
    assert event["page"] == "/mutants/:publicId"
    assert event["path"] in PAGE_TEMPLATE_OR_OTHER
    # Free text and raw identifiers are dropped, not stored.
    assert event["search_query"] == ""
    assert event["widget_name"] == ""
    assert event["user_agent"] == ""
    assert event["ip_hash"] == ""
    # Referrer/source are finite categories only.
    assert event["referrer"] in REFERRER_CATEGORIES
    assert event["source"] in REFERRER_CATEGORIES | {""}
    assert event["referrer"] == REFERRER_SEARCH
    assert event["source"] == classify_referrer(RAW_URL)
    assert event["source"] == REFERRER_OTHER
    assert event["event_type"] == "search"
    assert event["duration_ms"] == 1500
    assert_no_sentinels(response.text)
    assert_no_sentinels(str(dict(response.headers)))


def test_get_pixel_response_is_a_private_no_store_gif(client: TestClient) -> None:
    response = client.get("/track.gif", params={"page": "/genes/" + GENE_V5})

    assert response.headers["content-type"] == "image/gif"
    cache_control = response.headers["cache-control"]
    assert "no-store" in cache_control
    assert "private" in cache_control
    assert response.content == TRACKING_PIXEL
    assert_no_sentinels(response.text)


def test_page_template_round_trips_through_the_ingress(
    client: TestClient, spy: BackgroundSpy
) -> None:
    """A canonical template is its own fixed point, so storage stays stable."""
    for template in ("/mutants/:publicId", "/genes/:geneId", "/search", OTHER_PAGE_TEMPLATE):
        client.get("/track.gif", params={"page": template})

    assert [e["page"] for e in spy.events] == [
        "/mutants/:publicId",
        "/genes/:geneId",
        "/search",
        OTHER_PAGE_TEMPLATE,
    ]
    for event in spy.events:
        assert event["page"] == normalize_analytics_page(event["page"])


def test_assembly_specific_paths_never_cross_namespaces(
    client: TestClient, spy: BackgroundSpy
) -> None:
    client.get("/track.gif", params={"path": f"/genes/{GENE_V4}"})
    client.get("/track.gif", params={"path": f"/genes/{GENE_V5}"})

    assert [e["path"] for e in spy.events] == ["/genes/:geneId", "/genes/:geneId"]
    assert_no_sentinels(spy.queued)


def test_performance_event_requires_a_complete_metric_triplet(
    client: TestClient, spy: BackgroundSpy
) -> None:
    client.get(
        "/track.gif",
        params={
            "event": "performance",
            "name": "LCP",
            "value": "1234.5",
            "rating": "good",
            "path": f"/mutants/{INTERNAL_ID}",
        },
    )
    assert len(spy.vitals) == 1
    assert spy.vitals[0]["name"] == "LCP"
    assert spy.vitals[0]["value"] == 1234.5
    assert spy.vitals[0]["rating"] == "good"
    assert spy.vitals[0]["path"] == "/mutants/:publicId"
    assert spy.vitals[0]["user_agent"] == ""
    assert spy.vitals[0]["ip_hash"] == ""
    assert_no_sentinels(spy.queued)

    # A rating missing its metric is dropped, never stored half-formed.
    spy.vitals.clear()
    client.get("/track.gif", params={"event": "performance", "name": "LCP", "value": "12"})
    assert spy.vitals == []


# --------------------------------------------------------------------------- #
# DNT: nothing is created before the guard
# --------------------------------------------------------------------------- #


def test_dnt_returns_a_private_pixel_without_a_cookie_or_a_write(
    client: TestClient, spy: BackgroundSpy
) -> None:
    response = client.get(
        "/track.gif",
        params={"page": f"/mutants/{INTERNAL_ID}", "q": SEARCH_TERM},
        headers={"DNT": "1", "User-Agent": USER_AGENT_SENTINEL},
    )

    assert response.status_code == 200
    assert response.content == TRACKING_PIXEL
    assert "no-store" in response.headers["cache-control"]
    assert "private" in response.headers["cache-control"]
    # No cookie is minted and nothing is queued.
    assert SESSION_COOKIE not in response.cookies
    assert "set-cookie" not in {k.lower() for k in response.headers}
    assert spy.queued == []


def test_dnt_leaves_an_existing_cookie_untouched(
    client: TestClient, spy: BackgroundSpy
) -> None:
    existing = str(uuid.uuid4())
    client.cookies.set(SESSION_COOKIE, existing)

    response = client.get("/track.gif", params={"page": "/search"}, headers={"DNT": "1"})

    assert spy.queued == []
    # Present in the request, unchanged, and not re-issued or cleared.
    assert client.cookies.get(SESSION_COOKIE) == existing
    assert "set-cookie" not in {k.lower() for k in response.headers}


def test_existing_uuid_cookie_is_reused_and_not_reissued(
    client: TestClient, spy: BackgroundSpy
) -> None:
    existing = str(uuid.uuid4())
    response = client.get(
        "/track.gif", params={"page": "/search"}, cookies={SESSION_COOKIE: existing}
    )

    assert spy.events[0]["session_id"] == existing
    assert "set-cookie" not in {k.lower() for k in response.headers}


def test_garbage_cookie_is_replaced_with_a_new_uuid(
    client: TestClient, spy: BackgroundSpy
) -> None:
    response = client.get(
        "/track.gif", params={"page": "/search"}, cookies={SESSION_COOKIE: "not-a-uuid"}
    )

    minted = spy.events[0]["session_id"]
    assert uuid.UUID(minted)
    assert response.cookies[SESSION_COOKIE] == minted


def test_malformed_input_is_dropped_without_echo_or_cookie(
    client: TestClient, spy: BackgroundSpy
) -> None:
    response = client.get(
        "/track.gif",
        params={"page": f"/mutants/{INTERNAL_ID}#frag", "event": "telemetry", "q": SEARCH_TERM},
    )

    assert response.status_code == 200
    assert response.content == TRACKING_PIXEL
    assert spy.queued == []
    # An invalid event is not an error page: nothing about it is reflected.
    assert_no_sentinels(response.text)
    assert_no_sentinels(str(dict(response.headers)))
    assert SESSION_COOKIE not in response.cookies


@pytest.mark.parametrize(
    "params",
    [
        {"event": "telemetry"},
        {"duration": "-5"},
        {"duration": "not-a-number"},
        {"duration": str(86_400_001)},
        {"event": "performance", "name": "LCP", "value": "10", "rating": "excellent"},
        {"value": "-1", "name": "LCP", "rating": "good", "event": "performance"},
        {"value": "nan", "name": "LCP", "rating": "good", "event": "performance"},
        {"value": "inf", "name": "LCP", "rating": "good", "event": "performance"},
        {"value": "-inf", "name": "LCP", "rating": "good", "event": "performance"},
        {"value": "NaN", "name": "LCP", "rating": "good", "event": "performance"},
        {"value": "true", "name": "LCP", "rating": "good", "event": "performance"},
        {"name": "TBT", "value": "10", "rating": "good", "event": "performance"},
        {"page": "x" * 4000},
        {"page": ["/search", f"/mutants/{INTERNAL_ID}"]},
        {"q": SEARCH_TERM, "widget": WIDGET_LABEL, "duration": "1e9"},
    ],
)
def test_invalid_query_values_never_reach_storage(
    client: TestClient, spy: BackgroundSpy, params: dict[str, Any]
) -> None:
    response = client.get("/track.gif", params=params)

    assert response.status_code == 200
    assert spy.queued == []
    assert_no_sentinels(response.text)


# --------------------------------------------------------------------------- #
# POST beacon
# --------------------------------------------------------------------------- #


def test_beacon_stores_a_template_not_the_full_url(client: TestClient, spy: BackgroundSpy) -> None:
    response = client.post(
        "/track.gif",
        json={
            "event": "performance",
            "name": "CLS",
            "value": 0.05,
            "rating": "good",
            "url": RAW_URL,
            "id": INTERNAL_ID,
            "ts": 1750000000000,
        },
        headers={"User-Agent": USER_AGENT_SENTINEL},
    )

    assert response.status_code == 200
    assert response.content == TRACKING_PIXEL
    assert len(spy.vitals) == 1
    vital = spy.vitals[0]
    assert vital["path"] == "/mutants/:publicId"
    assert vital["user_agent"] == ""
    assert vital["ip_hash"] == ""
    assert_no_sentinels(vital)
    assert_no_sentinels(response.text)


def test_beacon_respects_dnt_before_touching_cookies(
    client: TestClient, spy: BackgroundSpy
) -> None:
    response = client.post(
        "/track.gif",
        json={"name": "LCP", "value": 1.0, "rating": "good", "url": RAW_URL},
        headers={"DNT": "1"},
    )

    assert response.status_code == 200
    assert spy.queued == []
    assert SESSION_COOKIE not in response.cookies


@pytest.mark.parametrize(
    "body",
    [
        b"not json at all",
        b"[]",
        b'"just a string"',
        b"{",
        json.dumps({"name": "TBT", "value": 1.0, "rating": "good"}).encode(),
        json.dumps({"name": "LCP", "value": -1, "rating": "good"}).encode(),
        json.dumps({"name": "LCP", "value": 86_400_001, "rating": "good"}).encode(),
        json.dumps({"name": "LCP", "value": "fast", "rating": "good"}).encode(),
        # A JSON boolean is not a measurement; ``true`` must not become 1.0 ms.
        json.dumps({"name": "LCP", "value": True, "rating": "good"}).encode(),
        json.dumps({"name": "LCP", "value": False, "rating": "good"}).encode(),
        # ``NaN``/``Infinity`` are JSON numbers Python accepts and no measurement.
        b'{"name": "LCP", "value": NaN, "rating": "good"}',
        b'{"name": "LCP", "value": Infinity, "rating": "good"}',
        b'{"name": "LCP", "value": -Infinity, "rating": "good"}',
        json.dumps({"name": "LCP", "value": "1e999", "rating": "good"}).encode(),
        json.dumps({"name": "LCP", "rating": "excellent"}).encode(),
        json.dumps({"event": "pageview", "name": "LCP", "value": 1.0, "rating": "good"}).encode(),
        b"x" * 9000,
    ],
)
def test_malformed_beacon_is_dropped_without_echo(
    client: TestClient, spy: BackgroundSpy, body: bytes
) -> None:
    response = client.post(
        "/track.gif",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.content == TRACKING_PIXEL
    assert spy.queued == []
    assert_no_sentinels(response.text)
    assert_no_sentinels(str(dict(response.headers)))


def test_beacon_echoes_no_rejected_value_in_a_validation_error(
    client: TestClient, spy: BackgroundSpy
) -> None:
    """A framework 422 would repeat the offending value; the pixel never does."""
    secret = f"{SEARCH_TERM}-{CREDENTIAL_SENTINEL}"
    response = client.post(
        "/track.gif",
        content=json.dumps({"name": secret, "value": "nan", "rating": secret}).encode(),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert secret not in response.text
    assert spy.queued == []


def test_beacon_boolean_is_rejected_before_model_validation(
    client: TestClient, spy: BackgroundSpy
) -> None:
    """``"value": true`` is a JSON boolean, not a 1.0 ms measurement.

    The ingress guards the value itself instead of relying on the field
    constraint, because pydantic's lax mode coerces a boolean into ``1.0``:
    without the guard this request would be queued and stored.
    """
    response = client.post(
        "/track.gif",
        json={"name": "LCP", "value": True, "rating": "good", "url": RAW_URL},
    )

    assert response.status_code == 200
    assert response.content == TRACKING_PIXEL
    assert spy.queued == []
    assert SESSION_COOKIE not in response.cookies


# --------------------------------------------------------------------------- #
# Store boundary: the service normalises even when called directly
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_record_event_sanitises_direct_store_calls(spy_session: SessionSpy) -> None:
    service = _service_with(spy_session)
    session_id = uuid.uuid4().hex

    await service.record_event(
        session_id=session_id,
        event_type="pageview",
        page=f"/mutants/{INTERNAL_ID}",
        path=RAW_URL,
        widget_name=WIDGET_LABEL,
        search_query=SEARCH_TERM,
        source=RAW_REferrer,
        referrer="https://www.bing.com/search?q=" + SEARCH_TERM,
        user_agent=USER_AGENT_SENTINEL,
        ip_hash="deadbeef" * 8,
        duration_ms=42,
    )

    row = spy_session.insert_params(EVENTS_TABLE)[0]
    assert_no_sentinels(row)
    assert row["page"] == "/mutants/:publicId"
    assert row["path"] in PAGE_TEMPLATE_OR_OTHER
    # The native table has no column for free text, a browser string or an
    # address, so those values are never bound — not written empty, absent.
    assert tuple(row) == EVENT_COLUMNS
    assert row["referrer"] == REFERRER_SEARCH
    assert row["source"] == classify_referrer(RAW_REferrer)
    assert row["duration_ms"] == 42
    assert uuid.UUID(str(row["session_id"])) == uuid.UUID(session_id)
    assert spy_session.commits == 1


@pytest.mark.asyncio
async def test_record_web_vital_sanitises_direct_store_calls(spy_session: SessionSpy) -> None:
    service = _service_with(spy_session)

    await service.record_web_vital(
        session_id=uuid.uuid4().hex,
        name="INP",
        value=120.0,
        rating="good",
        path=RAW_URL,
        user_agent=USER_AGENT_SENTINEL,
        ip_hash="deadbeef" * 8,
    )

    row = spy_session.insert_params(WEB_VITALS_TABLE)[0]
    assert_no_sentinels(row)
    assert row["path"] == "/mutants/:publicId"
    assert tuple(row) == WEB_VITAL_COLUMNS


@pytest.mark.asyncio
async def test_bad_metrics_are_never_stored_quietly(spy_session: SessionSpy) -> None:
    service = _service_with(spy_session)
    session_id = uuid.uuid4().hex

    await service.record_event(
        session_id=session_id, event_type="pageview", duration_ms=99_999_999
    )
    await service.record_web_vital(
        session_id=session_id, name="LCP", value=float("nan"), rating="good"
    )
    await service.record_web_vital(
        session_id=session_id, name="LCP", value=10.0, rating="excellent"
    )
    await service.record_event(session_id="not-a-uuid", event_type="pageview")

    rows = spy_session.insert_params(EVENTS_TABLE)
    assert len(rows) == 1
    row = rows[0]
    assert row["duration_ms"] == 86_400_000
    assert row["event_type"] == "pageview"


def test_end_to_end_ingress_to_insert_has_no_raw_values(
    store_client: TestClient, spy_session: SessionSpy
) -> None:
    """The real router and the real service, with only the session replaced."""
    spy = store_client.app.state.analytics_service
    store_client.get(
        "/track.gif",
        params={
            "event": "widget",
            "page": f"/mutants/{INTERNAL_ID}",
            "path": f"/mutants/{INTERNAL_ID}?q={SEARCH_TERM}",
            "widget": WIDGET_LABEL,
            "q": SEARCH_TERM,
            "duration": "3000",
        },
        headers={"User-Agent": USER_AGENT_SENTINEL, "X-Forwarded-For": IP_SENTINEL},
    )
    store_client.post(
        "/track.gif",
        json={"name": "TTFB", "value": 220.5, "rating": "good", "url": RAW_URL},
    )

    assert isinstance(spy, AnalyticsService)
    rows = spy_session.insert_params(EVENTS_TABLE)
    assert len(rows) == 1
    for row in rows:
        assert_no_sentinels(row)
    assert rows[0]["page"] == "/mutants/:publicId"
    assert tuple(rows[0]) == EVENT_COLUMNS
    assert spy_session.insert_params(WEB_VITALS_TABLE)[0]["path"] == "/mutants/:publicId"


@pytest.mark.asyncio
async def test_store_boundary_is_idempotent(spy_session: SessionSpy) -> None:
    """Normalising an already-normalised value must not move it.

    This is the regression for the double-classification trap: the ingress hands
    the store a ``direct`` category, and a store that re-classified its own
    output would report it as ``other``.
    """
    service = _service_with(spy_session)

    await service.record_event(
        session_id=uuid.uuid4().hex,
        event_type="pageview",
        page="/mutants/:publicId",
        path="/other",
        referrer=REFERRER_DIRECT,
        source=REFERRER_SEARCH,
    )
    row = spy_session.insert_params(EVENTS_TABLE)[0]
    assert row["page"] == "/mutants/:publicId"
    assert row["path"] == OTHER_PAGE_TEMPLATE
    assert row["referrer"] == REFERRER_DIRECT
    assert row["source"] == REFERRER_SEARCH

    # A second writer boundary pass cannot change any of them.
    await service.record_event(
        session_id=uuid.uuid4().hex,
        event_type="pageview",
        page=normalize_analytics_page(row["page"]),
        path=normalize_analytics_page(row["path"]),
        referrer=row["referrer"],
        source=row["source"],
    )
    again = spy_session.insert_params(EVENTS_TABLE)[1]
    assert again["page"] == row["page"]
    assert again["referrer"] == row["referrer"]


def test_request_site_never_changes_what_is_stored(
    store_client: TestClient, spy_session: SessionSpy
) -> None:
    """Host/UA/IP are not a permission and not a storage dimension.

    The client's ``site`` is never trusted as anything: two requests differing
    only in host and client headers produce byte-identical rows apart from the
    per-session cookie, and no site-like column is added.
    """
    for host in ("portal.example", "admin.internal.example"):
        store_client.get(
            "/track.gif",
            params={"page": "/search"},
            headers={
                "Host": host,
                "User-Agent": USER_AGENT_SENTINEL,
                "X-Forwarded-For": IP_SENTINEL,
            },
        )

    rows = spy_session.insert_params(EVENTS_TABLE)
    assert len(rows) == 2
    assert rows[0]["page"] == rows[1]["page"] == "/search"
    assert_no_sentinels(rows)
    # The bound column set is fixed, and it holds no host, agent or address
    # dimension: there is nowhere for one of those to be recorded.
    for row in rows:
        assert tuple(row) == EVENT_COLUMNS


def test_beacon_reuses_an_existing_session_cookie(client: TestClient, spy: BackgroundSpy) -> None:
    existing = str(uuid.uuid4())
    response = client.post(
        "/track.gif",
        json={"name": "FCP", "value": 900.0, "rating": "good", "url": "/news/slug"},
        cookies={SESSION_COOKIE: existing},
    )

    assert spy.vitals[0]["session_id"] == existing
    assert spy.vitals[0]["path"] == "/news/:slug"
    assert "set-cookie" not in {k.lower() for k in response.headers}


# --------------------------------------------------------------------------- #
# Admin summary
# --------------------------------------------------------------------------- #

HISTORICAL_ROWS = {
    "GROUP BY event_type": [("pageview", 40), ("search", 9), ("legacy-thing", 3)],
    "GROUP BY page": [
        (f"/mutants/{INTERNAL_ID}", 12),
        (f"/mutants/{PUBLIC_ID}", 5),
        ("/search", 30),
        (f"https://{HOST_SENTINEL}/mutants/{INTERNAL_ID}", 2),
        ("/admin/secrets", 4),
    ],
    "GROUP BY referrer": [
        (f"https://{EMAIL_SENTINEL}@{HOST_SENTINEL}/", 8),
        ("direct", 20),
        ("https://www.google.com/search?q=" + SEARCH_TERM, 6),
    ],
    "AT TIME ZONE": [("2026-10-01", 12), ("2026-10-02", 9), ("not-a-date", 4)],
    "SELECT COUNT(*) FROM": [],
    "COUNT(DISTINCT session_id)": [],
}


def test_summary_requires_an_administrator_and_queries_nothing_otherwise(
    monkeypatch: pytest.MonkeyPatch, session: SessionSpy
) -> None:
    anonymous = TestClient(_summary_app(monkeypatch, session))
    assert anonymous.get("/admin/analytics/summary").status_code == 401
    assert session.statements == []

    non_admin = TestClient(_summary_app(monkeypatch, session, user=_researcher_user()))
    response = non_admin.get("/admin/analytics/summary")
    assert response.status_code == 403
    assert session.statements == []


def test_summary_is_private_and_never_shared_cached(
    monkeypatch: pytest.MonkeyPatch, session: SessionSpy
) -> None:
    app = _summary_app(monkeypatch, session, user=_admin_user())
    response = TestClient(app).get("/admin/analytics/summary")

    assert response.status_code == 200
    cache_control = response.headers["cache-control"]
    assert "private" in cache_control
    assert "no-store" in cache_control


def test_summary_sanitises_historical_labels_and_merges_counts(
    monkeypatch: pytest.MonkeyPatch, session: SessionSpy
) -> None:
    session.responses = HISTORICAL_ROWS
    app = _summary_app(monkeypatch, session, user=_admin_user())

    body = TestClient(app).get("/admin/analytics/summary").json()
    assert_no_sentinels(body)

    pages = {item["label"]: item["count"] for item in body["top_pages"]}
    # Raw ids and full URLs collapse into one template and their counts merge.
    assert pages["/mutants/:publicId"] == 12 + 5 + 2
    assert pages["/search"] == 30
    # An internal-only route is not guessed at; it collapses to /other.
    assert pages[OTHER_PAGE_TEMPLATE] == 4
    assert all(label in PAGE_TEMPLATE_OR_OTHER for label in pages)

    referrers = {item["label"]: item["count"] for item in body["top_referrers"]}
    assert set(referrers) <= REFERRER_CATEGORIES
    # A stored category is a fixed point of the read normaliser.
    assert referrers[REFERRER_DIRECT] == 20
    assert referrers[REFERRER_SEARCH] == 6
    # A raw historical URL collapses into a category instead of being echoed.
    assert referrers[REFERRER_OTHER] == 8

    types = {item["label"]: item["count"] for item in body["events_by_type"]}
    assert set(types) <= {"pageview", "click", "search", "widget", "other"}
    assert types["other"] == 3

    # The daily series keeps its dates; nothing is merged into it.
    assert [item["label"] for item in body["events_by_day"]] == ["2026-10-01", "2026-10-02"]


def test_summary_never_returns_free_text_search_terms(
    monkeypatch: pytest.MonkeyPatch, session: SessionSpy
) -> None:
    session.responses = HISTORICAL_ROWS
    app = _summary_app(monkeypatch, session, user=_admin_user())

    body = TestClient(app).get("/admin/analytics/summary").json()

    assert body["top_searches"] == []
    assert body["top_searches_available"] is False
    assert "search_query" not in session.sql_text
    assert SEARCH_TERM not in json.dumps(body)


def test_summary_distinguishes_an_empty_window_from_an_unavailable_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy = SessionSpy(responses={"SELECT COUNT(*) FROM": [(0,)]})
    healthy.responses["COUNT(DISTINCT session_id)"] = [(0,)]
    body = TestClient(_summary_app(monkeypatch, healthy, user=_admin_user())).get(
        "/admin/analytics/summary"
    ).json()

    assert body["total_events"] == 0
    assert body["total_events_available"] is True
    assert body["top_pages"] == []

    broken = SessionSpy()
    broken.fail = True
    degraded = TestClient(_summary_app(monkeypatch, broken, user=_admin_user())).get(
        "/admin/analytics/summary"
    ).json()

    assert degraded["total_events"] == 0
    assert degraded["total_events_available"] is False
    assert degraded["top_pages_available"] is False
    assert degraded["events_by_day_available"] is False
    # An older typed client keeps its shape either way: the seven data sections
    # and the seven availability flags are always present.
    sections = (
        "total_events",
        "unique_sessions",
        "events_by_type",
        "top_pages",
        "top_referrers",
        "top_searches",
        "events_by_day",
    )
    for key in sections:
        assert key in body and key in degraded
        assert f"{key}_available" in body and f"{key}_available" in degraded
    assert body["top_searches_available"] is False
    assert degraded["top_searches_available"] is False


# --------------------------------------------------------------------------- #
# Admin summary: truncation must not happen before normalisation
# --------------------------------------------------------------------------- #


def _raw_mutant_page_rows(count: int) -> list[tuple[str, int]]:
    """Distinct raw mutant URLs, as written before templates existed."""
    return [(f"/mutants/{900_000 + index}", 1) for index in range(count)]


def _raw_referrer_rows(count: int) -> list[tuple[str, int]]:
    """Distinct raw referrer URLs, none of which is a known category."""
    return [(f"https://blog-{index}.example/post", 1) for index in range(count)]


def test_summary_merges_every_stored_label_before_truncating(
    monkeypatch: pytest.MonkeyPatch, session: SessionSpy
) -> None:
    """A count must be the total, not the top raw rows that survive a LIMIT.

    120 distinct mutant URLs collapse into one template. Truncating the
    *stored* labels first would drop whole groups that were about to be merged
    into it, so ``/mutants/:publicId`` would report a lower bound instead of
    the real total. The fake applies the query's own ``LIMIT``, so a query that
    still has one fails this test rather than passing by accident.
    """
    session.responses = {
        "GROUP BY page": [*_raw_mutant_page_rows(120), ("/search", 500)],
        "GROUP BY referrer": _raw_referrer_rows(60),
    }
    app = _summary_app(monkeypatch, session, user=_admin_user())

    body = TestClient(app).get("/admin/analytics/summary").json()

    pages = {item["label"]: item["count"] for item in body["top_pages"]}
    assert pages["/mutants/:publicId"] == 120
    assert pages["/search"] == 500
    referrers = {item["label"]: item["count"] for item in body["top_referrers"]}
    assert referrers[REFERRER_OTHER] == 60
    # No breakdown query may cut the stored labels before they are normalised.
    assert _LIMIT_CLAUSE.search(session.sql_text) is None


def test_summary_caps_the_breakdown_only_after_merging(
    monkeypatch: pytest.MonkeyPatch, session: SessionSpy
) -> None:
    """The cap drops whole templates; it never shaves a merged count."""
    # 25 distinct real templates. `/analyses*` used to fill three slots; those
    # routes no longer exist, so the same three slots now hold other pages that
    # are still in the canonical set — the test is about the cap dropping whole
    # templates, not about any particular page.
    templates = [
        "/", "/about", "/analytics", "/assemblies", "/blast",
        "/browser", "/compare", "/downloads",
        "/genes", "/guide", "/help", "/login", "/mutants", "/news",
        "/publications", "/search", "/search/blast", "/search/gbrowse",
        "/search/genes", "/search/location", "/search/primer",
        "/seed-request", "/sra", "/tools", "/variants",
    ]
    # 25 distinct templates, one of them reached through two raw spellings.
    session.responses = {
        "GROUP BY page": [
            *[(template, 100) for template in templates],
            (f"https://{HOST_SENTINEL}/", 3),
        ]
    }
    app = _summary_app(monkeypatch, session, user=_admin_user())

    body = TestClient(app).get("/admin/analytics/summary").json()

    pages = {item["label"]: item["count"] for item in body["top_pages"]}
    assert len(pages) == 20
    # The merged template keeps its full count even though five were dropped.
    assert pages["/"] == 103
    assert sum(item["count"] for item in body["top_pages"]) == 103 + 19 * 100
    assert all(label in PAGE_TEMPLATE_OR_OTHER for label in pages)


# --------------------------------------------------------------------------- #
# Admin summary: the window is a bound cutoff, not statement text
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_summary_window_is_a_bound_utc_cutoff(spy_session: SessionSpy) -> None:
    """The day count arrives as a parameter, and every query shares it.

    An ``INTERVAL n DAY`` in statement text would make the window part of the
    query; a bound ``:cutoff`` keeps it a value and keeps all six statements of
    the summary on one window.
    """
    service = _service_with(spy_session)
    before = datetime.now(UTC)

    await service.get_summary(days=7)
    after = datetime.now(UTC)

    cutoffs = [
        statement["parameters"]["cutoff"]
        for statement in spy_session.statements
        if "cutoff" in statement["parameters"]
    ]
    assert len(cutoffs) == 6
    assert len(set(cutoffs)) == 1
    assert before - timedelta(days=7) <= cutoffs[0] <= after - timedelta(days=7)
    assert "INTERVAL" not in spy_session.sql_text.upper()


@pytest.mark.asyncio
async def test_summary_window_stays_inside_the_published_bounds(
    spy_session: SessionSpy,
) -> None:
    """A direct caller cannot ask for an unbounded scan or an empty window."""
    service = _service_with(spy_session)

    for requested, expected_days in ((0, 1), (-5, 1), (10_000, 365), ("nonsense", 1)):
        spy_session.statements.clear()
        now = datetime.now(UTC)
        await service.get_summary(days=requested)  # type: ignore[arg-type]
        after = datetime.now(UTC)
        cutoff = next(
            statement["parameters"]["cutoff"] for statement in spy_session.statements
            if "cutoff" in statement["parameters"]
        )
        window = timedelta(days=expected_days)
        assert now - window <= cutoff <= after - window
