"""Anonymous BLAST uses a purpose-specific capability, not account auth.

HTTP tests run the real route/service/outbox path with a recording session;
Redis tests exercise the shared atomic limiter contract independently.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError as PydanticValidationError

from app.api.v1 import blast as routes
from app.core.blast_capability import (
    PUBLIC_JOB_MARKER,
    PURPOSE,
    issue_blast_capability,
    verify_blast_capability,
)
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import AuthenticationError, AuthorizationError, ServiceUnavailableError
from app.core.ratelimit import PublicBlastRateLimiter
from app.models.blast import BlastDatabase, BlastJob
from app.models.genomic import Assembly
from app.services.blast_service import BlastService
from app.services.release_context import ReleaseContext, get_release_context

PAYLOAD = {"database_id": 1, "query_sequence": ">query\nMKVLAAGIVGLNLGGK"}
BASE = "/api/v1/blast/public/jobs"


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class Session:
    def __init__(self):
        self.catalog = BlastDatabase(
            id=1,
            name="protein",
            db_type="prot",
            assembly_id=1,
            file_path="/private/indices/protein",
            is_active=True,
        )
        self.catalog.assembly = Assembly(
            id=1,
            name="Wm82.a4.v1",
            species="Glycine max",
            version="v4",
            release_id=7,
        )
        self.jobs = {}
        self.added = []
        self.statements = []
        self.commits = 0

    async def execute(self, stmt):
        self.statements.append(stmt)
        sql = str(stmt)
        if "FROM blast_jobs" in sql:
            job_id = stmt.whereclause.right.value
            return Result([self.jobs[job_id]] if job_id in self.jobs else [])
        if "FROM blast_databases" in sql:
            return Result([self.catalog] if self.catalog else [])
        if "min(blast_hits.evalue)" in sql:
            return Result([(None, None)])
        return Result()

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, BlastJob):
            obj.database = self.catalog
            self.jobs[obj.id] = obj

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass


@pytest.fixture
async def api(monkeypatch):
    session = Session()
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_release_context] = lambda: ReleaseContext(
        release_id=7, assembly_id=1, assembly="Wm82.a4.v1"
    )
    quota = AsyncMock()
    monkeypatch.setattr(routes, "public_blast_rate_limiter", quota)
    monkeypatch.setattr(get_settings(), "blast_public_enabled", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, session, quota


def headers(token):
    return {"X-Blast-Token": token}


def assert_private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "X-Blast-Token"


async def submit(api):
    client, session, quota = api
    response = await client.post(BASE, json=PAYLOAD)
    assert response.status_code == 201, response.text
    assert_private(response)
    body = response.json()
    return body, session.jobs[uuid.UUID(body["job"]["job_id"])]


async def test_submit_reuses_release_scoped_transactional_outbox_without_path_leaks(api):
    body, job = await submit(api)
    _, session, quota = api
    assert job.user_id is None
    assert job.parameters[PUBLIC_JOB_MARKER] is True
    assert PUBLIC_JOB_MARKER not in body["job"]["parameters"]
    assert session.commits == 1
    event = next(obj for obj in session.added if type(obj).__name__ == "OutboxEvent")
    payload = event.payload["payload"]
    assert payload["database"] == "protein"
    assert payload["assembly_id"] == 1
    assert payload["release_key"] == "7"
    assert PUBLIC_JOB_MARKER not in payload["parameters"]
    assert "assemblies.release_id" in str(session.statements[0])
    assert 7 in session.statements[0].compile().params.values()
    assert "/private/" not in str(body)
    assert job.expires_at <= datetime.now(UTC) + timedelta(hours=24)
    claims = jwt.decode(
        body["access_token"], get_settings().jwt_secret, algorithms=[get_settings().jwt_algorithm]
    )
    assert claims["sub"] == str(job.id)
    assert claims["type"] == claims["purpose"] == PURPOSE
    assert len(claims["jti"]) >= 32
    assert claims["exp"] - claims["iat"] <= 86400
    assert (
        datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00")).timestamp()
        == claims["exp"]
    )
    quota.enforce.assert_awaited_once_with(client_ip="127.0.0.1")


async def test_header_capability_can_poll_and_read_results_only(api):
    body, job = await submit(api)
    client, _, _ = api
    for suffix in ("", "/results"):
        response = await client.get(
            f"{BASE}/{job.id}{suffix}", headers=headers(body["access_token"])
        )
        assert response.status_code == 200, response.text
        assert_private(response)
    # A query parameter, or even a bearer header, cannot stand in for the capability header.
    for kwargs in (
        {"params": {"access_token": body["access_token"]}},
        {"headers": {"Authorization": f"Bearer {body['access_token']}"}},
    ):
        response = await client.get(f"{BASE}/{job.id}", **kwargs)
        assert response.status_code == 401
        assert_private(response)
    assert (await client.get(BASE)).status_code == 405


@pytest.mark.parametrize("kind", ["access", "refresh", "wrong-job", "expired", "tampered"])
async def test_public_rejects_other_purposes_jobs_expiry_and_bad_signatures(api, kind):
    body, job = await submit(api)
    client, _, _ = api
    now = datetime.now(UTC)
    claims = {
        "sub": str(job.id),
        "type": PURPOSE,
        "purpose": PURPOSE,
        "jti": "a" * 40,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    if kind in ("access", "refresh"):
        claims["type"] = kind
    elif kind == "wrong-job":
        claims["sub"] = str(uuid.uuid4())
    elif kind == "expired":
        claims.update(iat=now - timedelta(hours=2), exp=now - timedelta(hours=1))
    token = jwt.encode(claims, get_settings().jwt_secret, algorithm=get_settings().jwt_algorithm)
    if kind == "tampered":
        token += "bad"
    for suffix in ("", "/results"):
        response = await client.get(f"{BASE}/{job.id}{suffix}", headers=headers(token))
        assert response.status_code == 401
        assert_private(response)
        assert token not in response.text


@pytest.mark.parametrize("owner,marker", [(True, True), (True, False), (False, False)])
async def test_capability_rejects_account_owned_and_orphaned_account_jobs(api, owner, marker):
    body, job = await submit(api)
    client, _, _ = api
    job.user_id = uuid.uuid4() if owner else None
    job.parameters = {PUBLIC_JOB_MARKER: marker}
    for suffix in ("", "/results"):
        response = await client.get(
            f"{BASE}/{job.id}{suffix}", headers=headers(body["access_token"])
        )
        assert response.status_code == 403
        assert_private(response)


@pytest.mark.parametrize("roles", [None, [], ["researcher"]])
def test_private_authorization_never_accepts_none_equals_none(roles):
    with pytest.raises(AuthorizationError):
        BlastService._authorize_job(None, None, roles)
    BlastService._authorize_job(None, None, ["administrator"])


async def test_no_public_diagnostics_or_stored_result_path(api):
    body, job = await submit(api)
    client, _, _ = api
    job.status = "failed"
    job.error_message = "/private/indices/protein failed running /bin/diamond"
    job.result_path = "/private/local/result"
    for suffix in ("", "/results"):
        response = await client.get(
            f"{BASE}/{job.id}{suffix}", headers=headers(body["access_token"])
        )
        assert response.status_code == 200
        assert "/private" not in response.text
        assert "/bin/" not in response.text
        assert response.json()["error_message"] == "BLAST search failed"


async def test_expired_completed_jobs_never_generate_downloads(api, monkeypatch):
    body, job = await submit(api)
    client, _, _ = api
    job.status = "completed"
    job.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    job.result_path = "blast-results/output.json"
    presign = AsyncMock()
    monkeypatch.setattr("app.services.blast_service.generate_presigned_url", presign)
    response = await client.get(f"{BASE}/{job.id}/results", headers=headers(body["access_token"]))
    assert response.json()["status"] == "expired"
    assert response.json()["download_url"] is None
    presign.assert_not_called()


async def test_download_ttl_does_not_outlive_capability(api, monkeypatch):
    from unittest.mock import Mock

    body, job = await submit(api)
    client, _, _ = api
    job.status = "completed"
    job.result_path = "blast-results/output.json"
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(job.id),
            "type": PURPOSE,
            "purpose": PURPOSE,
            "jti": "a" * 40,
            "iat": now,
            "exp": now + timedelta(seconds=30),
        },
        get_settings().jwt_secret,
        algorithm=get_settings().jwt_algorithm,
    )
    presign = Mock(return_value="https://objects.example/signed")
    monkeypatch.setattr("app.services.blast_service.generate_presigned_url", presign)
    response = await client.get(f"{BASE}/{job.id}/results", headers=headers(token))
    assert response.status_code == 200, response.text
    assert response.json()["download_url"] == "https://objects.example/signed"
    assert 0 < presign.call_args.kwargs["expires_in"] <= 30


async def test_public_shorter_query_limit_and_disabled_mode(api, monkeypatch):
    client, session, quota = api
    monkeypatch.setattr(get_settings(), "blast_public_max_length", 20)
    response = await client.post(BASE, json={**PAYLOAD, "query_sequence": "M" * 21})
    assert response.status_code == 422
    assert_private(response)
    assert not session.added
    quota.enforce.assert_not_awaited()
    monkeypatch.setattr(get_settings(), "blast_public_enabled", False)
    assert (await client.post(BASE, json=PAYLOAD)).status_code == 404


async def test_unpublished_database_creates_neither_job_nor_outbox(api):
    client, session, _ = api
    session.catalog = None
    response = await client.post(BASE, json=PAYLOAD)
    assert response.status_code == 404
    assert_private(response)
    assert not session.added
    assert not session.commits


async def test_quota_failure_precedes_job_and_outbox(api):
    from app.core.exceptions import RateLimitExceededError

    client, session, quota = api
    quota.enforce.side_effect = RateLimitExceededError("Too many public searches", retry_after=100)
    response = await client.post(BASE, json=PAYLOAD)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "100"
    assert_private(response)
    assert not session.added


async def test_peer_header_only_trusted_from_configured_proxy(api, monkeypatch):
    client, _, quota = api
    await client.post(BASE, json=PAYLOAD, headers={"X-Forwarded-For": "192.0.2.1"})
    quota.enforce.assert_awaited_with(client_ip="127.0.0.1")
    monkeypatch.setattr(get_settings(), "analytics_trusted_proxy_ips", ("127.0.0.1",))
    await client.post(BASE, json=PAYLOAD, headers={"X-Forwarded-For": "192.0.2.1"})
    quota.enforce.assert_awaited_with(client_ip="192.0.2.1")


async def test_dedicated_redis_budget_is_shared_and_resets_by_window():
    from app.core.exceptions import RateLimitExceededError

    counts = {}
    clock = [3600.0]

    async def evaluate(_script, _numkeys, key, ttl):
        counts[key] = counts.get(key, 0) + 1
        return [counts[key], ttl]

    redis = SimpleNamespace(eval=evaluate)
    config = SimpleNamespace(
        app_env="prod", blast_public_rate_limit_max=5, blast_public_rate_limit_window=3600
    )
    workers = [
        PublicBlastRateLimiter(
            redis_getter=lambda: redis, settings_getter=lambda: config, clock=lambda: clock[0]
        )
        for _ in range(2)
    ]
    for index in range(5):
        await workers[index % 2].enforce(client_ip="192.0.2.1")
    with pytest.raises(RateLimitExceededError):
        await workers[1].enforce(client_ip="192.0.2.1")
    assert all(key.startswith("soymutdb:blast-public-submit:") for key in counts)
    await workers[0].enforce(client_ip="192.0.2.2")
    clock[0] += 3600
    await workers[0].enforce(client_ip="192.0.2.1")


@pytest.mark.parametrize("env", ["prod", "staging", "dev"])
async def test_quota_redis_failure_closed_except_dev(env):
    from app.core.exceptions import RateLimitExceededError

    async def unavailable(*args):
        raise ConnectionError("down")

    config = SimpleNamespace(
        app_env=env, blast_public_rate_limit_max=1, blast_public_rate_limit_window=3600
    )
    limiter = PublicBlastRateLimiter(
        redis_getter=lambda: SimpleNamespace(eval=unavailable), settings_getter=lambda: config
    )
    if env == "dev":
        await limiter.enforce(client_ip="192.0.2.1")
        with pytest.raises(RateLimitExceededError):
            await limiter.enforce(client_ip="192.0.2.1")
    else:
        with pytest.raises(ServiceUnavailableError):
            await limiter.enforce(client_ip="192.0.2.1")


def test_random_jti_and_ttl_config():
    job_id = uuid.uuid4()
    first, _ = issue_blast_capability(job_id)
    second, _ = issue_blast_capability(job_id)
    assert first != second
    verify_blast_capability(first, job_id)
    with pytest.raises(AuthenticationError):
        verify_blast_capability(first, uuid.uuid4())
    for ttl in (0, 86401):
        with pytest.raises(PydanticValidationError):
            Settings(blast_public_token_ttl_seconds=ttl)
