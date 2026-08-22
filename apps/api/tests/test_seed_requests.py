"""Seed request contact API tests (D1) – no docker / no testcontainers.

Covers with a fake database session:
- service layer: create (row + outbox event in one transaction, task name /
  idempotency key assertions), list (pagination shape + status filter SQL),
  status transitions (pending → approved/rejected → fulfilled, illegal
  transitions rejected, unknown id 404)
- HTTP layer: public create (201 / validation 422 for bad email and
  >200 gene IDs), admin RBAC (401 unauthenticated / 403 non-manager /
  200 seed manager), endpoint wiring
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import (
    SoyMutDBError,
    http_exception_handler,
    soy_mut_db_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.security import RoleName, create_access_token
from app.core.task_contract import SEED_REQUEST_EMAIL_TASK
from app.models.auth import Role, User
from app.models.outbox import OutboxEvent, OutboxEventStatus
from app.models.seed_request import SeedRequestContact, SeedRequestStatus
from app.schemas.seed_request import (
    MAX_GENE_IDS,
    SeedRequestCreate,
    SeedRequestUpdate,
)
from app.services.seed_request_service import SeedRequestService


# ---------------------------------------------------------------------------
# Fake database session (unit-level, no docker)
# ---------------------------------------------------------------------------


class _Scalars:
    def __init__(self, items: list):
        self._items = items

    def all(self) -> list:
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class _Result:
    def __init__(self, rows: list):
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0] if self._rows else None


class FakeDbSession:
    """AsyncSession stand-in: returns fake seed request rows for queries."""

    def __init__(
        self,
        requests: list[SeedRequestContact] | None = None,
        user: User | None = None,
        total: int | None = None,
    ):
        self.requests = list(requests or [])
        self.user = user
        #: ``None`` means "derive from requests at query time" (tests may
        #: mutate ``requests`` after construction).
        self.total = total
        self.added: list[Any] = []
        self.commits = 0
        self.flushes = 0
        self.last_stmt = None
        self.statements: list[Any] = []

    async def execute(self, stmt, params=None):
        self.last_stmt = stmt
        self.statements.append(stmt)
        text = str(stmt)
        if "seed_request_contacts" in text:
            if "count(*)" in text.lower():
                total = self.total if self.total is not None else len(self.requests)
                return _Result([total])
            return _Result(list(self.requests))
        if "FROM users" in text:
            return _Result([self.user] if self.user else [])
        return _Result([])

    def add(self, obj) -> None:
        # Emulate the DB: server-side timestamps.
        if isinstance(obj, SeedRequestContact):
            now = datetime.now(UTC)
            obj.created_at = obj.created_at or now
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj) -> None:
        pass

    async def rollback(self) -> None:
        pass


def _make_user(role: RoleName = RoleName.RESEARCHER) -> User:
    return User(
        id=uuid.uuid4(),
        username="tester",
        email="tester@soymutdb.local",
        password_hash="x",
        is_active=True,
        is_deleted=False,
        role_rel=Role(id=1, name=role.value),
    )


def _make_request(
    *,
    request_id: str | None = None,
    name: str = "Jane Doe",
    email: str = "jane@example.org",
    status: str = "pending",
    processed_at=None,
    processed_by=None,
) -> SeedRequestContact:
    now = datetime.now(UTC)
    return SeedRequestContact(
        id=uuid.UUID(request_id) if request_id else uuid.uuid4(),
        name=name,
        email=email,
        institution="University of Soy",
        country="China",
        gene_ids=["Glyma.01G000100", "Glyma.01G000200"],
        notes=None,
        status=status,
        created_at=now,
        processed_at=processed_at,
        processed_by=processed_by,
    )


def _create_payload(**overrides: Any) -> dict:
    payload = {
        "name": "Jane Doe",
        "email": "jane@example.org",
        "institution": "University of Soy",
        "country": "China",
        "gene_ids": ["Glyma.01G000100", "Glyma.01G000200"],
        "notes": "For my lab's drought project",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Service layer — create + outbox
# ---------------------------------------------------------------------------


class TestCreateRequest:
    async def test_create_writes_row_and_outbox_event_in_one_transaction(self):
        session = FakeDbSession()
        service = SeedRequestService()

        response = await service.create_request(
            session, SeedRequestCreate(**_create_payload())
        )

        # One transaction: request + outbox event committed together.
        assert session.commits == 1
        assert session.flushes >= 1

        request = next(
            obj for obj in session.added if isinstance(obj, SeedRequestContact)
        )
        event = next(obj for obj in session.added if isinstance(obj, OutboxEvent))

        assert request.status == SeedRequestStatus.PENDING
        assert request.gene_ids == ["Glyma.01G000100", "Glyma.01G000200"]

        # Outbox event carries the full versioned JobPayload for the email task.
        assert event.aggregate_type == "seed_request"
        assert event.aggregate_id == str(request.id)
        assert event.event_type == "seed_request.created"
        assert event.status == OutboxEventStatus.PENDING
        assert event.attempt_count == 0
        payload = event.payload
        assert payload["task_name"] == SEED_REQUEST_EMAIL_TASK
        assert payload["payload_version"] == 1
        assert payload["job_id"] == str(request.id)
        assert payload["idempotency_key"] == f"seed-request-email:{request.id}"
        inner = payload["payload"]
        assert inner["request_id"] == str(request.id)
        assert inner["name"] == "Jane Doe"
        assert inner["email"] == "jane@example.org"
        assert inner["gene_ids"] == ["Glyma.01G000100", "Glyma.01G000200"]
        assert inner["status"] == "pending"

        assert response.id == str(request.id)
        assert response.status.value == "pending"

    async def test_create_dedupes_and_trims_gene_ids(self):
        session = FakeDbSession()
        response = await SeedRequestService().create_request(
            session,
            SeedRequestCreate(
                **_create_payload(
                    gene_ids=["Glyma.01G000100", " Glyma.01G000100 ", "Glyma.02G000100"]
                )
            ),
        )
        assert response.gene_ids == [
            "Glyma.01G000100",
            "Glyma.02G000100",
        ]

    async def test_create_rejects_too_many_gene_ids(self):
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            SeedRequestCreate(
                **_create_payload(gene_ids=[f"Glyma.{i:02d}G000100" for i in range(MAX_GENE_IDS + 1)])
            )

    async def test_create_rejects_empty_gene_ids(self):
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            SeedRequestCreate(**_create_payload(gene_ids=[]))

    async def test_create_rejects_bad_email(self):
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError):
            SeedRequestCreate(**_create_payload(email="not-an-email"))


# ---------------------------------------------------------------------------
# Service layer — list
# ---------------------------------------------------------------------------


class TestListRequests:
    async def test_list_returns_paginated_shape(self):
        session = FakeDbSession(
            requests=[_make_request(), _make_request()],
            total=7,
        )
        response = await SeedRequestService().list_requests(
            session, page=2, page_size=5
        )
        assert response.total == 7
        assert response.page == 2
        assert response.page_size == 5
        assert len(response.items) == 2

    async def test_list_applies_status_filter_in_sql(self):
        session = FakeDbSession(requests=[_make_request(status="pending")])
        await SeedRequestService().list_requests(
            session, status=SeedRequestStatus.PENDING
        )
        sql = str(session.last_stmt)
        assert "seed_request_contacts" in sql
        assert "seed_request_contacts.status" in sql

    async def test_list_orders_by_created_at_desc(self):
        session = FakeDbSession(requests=[_make_request()])
        await SeedRequestService().list_requests(session)
        sql = str(session.last_stmt)
        assert "ORDER BY" in sql and "created_at" in sql


# ---------------------------------------------------------------------------
# Service layer — status transitions
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    async def test_pending_to_approved_records_processor(self):
        request = _make_request()
        session = FakeDbSession(requests=[request])
        processor = uuid.uuid4()

        response = await SeedRequestService().update_status(
            session, request.id, SeedRequestUpdate(status=SeedRequestStatus.APPROVED), processor
        )

        assert response.status.value == "approved"
        assert response.processed_by == str(processor)
        assert response.processed_at is not None
        assert session.commits == 1

    async def test_approved_to_fulfilled_ok(self):
        request = _make_request(status="approved", processed_at=datetime.now(UTC))
        session = FakeDbSession(requests=[request])
        response = await SeedRequestService().update_status(
            session, request.id, SeedRequestUpdate(status=SeedRequestStatus.FULFILLED), uuid.uuid4()
        )
        assert response.status.value == "fulfilled"

    async def test_illegal_transition_rejected(self):
        from app.core.exceptions import ValidationError

        request = _make_request(status="pending")
        session = FakeDbSession(requests=[request])
        with pytest.raises(ValidationError, match="Illegal seed request status transition"):
            await SeedRequestService().update_status(
                session, request.id, SeedRequestUpdate(status=SeedRequestStatus.FULFILLED), uuid.uuid4()
            )

    async def test_terminal_status_never_transitions(self):
        from app.core.exceptions import ValidationError

        for terminal in ("rejected", "fulfilled"):
            request = _make_request(status=terminal, processed_at=datetime.now(UTC))
            session = FakeDbSession(requests=[request])
            with pytest.raises(ValidationError):
                await SeedRequestService().update_status(
                    session, request.id, SeedRequestUpdate(status=SeedRequestStatus.APPROVED), uuid.uuid4()
                )

    async def test_unknown_id_404(self):
        from app.core.exceptions import NotFoundError

        session = FakeDbSession(requests=[])
        with pytest.raises(NotFoundError):
            await SeedRequestService().update_status(
                session, uuid.uuid4(), SeedRequestUpdate(status=SeedRequestStatus.APPROVED), uuid.uuid4()
            )


# ---------------------------------------------------------------------------
# HTTP layer: public create + admin RBAC
# ---------------------------------------------------------------------------


@pytest.fixture
async def api_app():
    """Minimal app with the full v1 router and a fake DB session."""
    from app.api.v1.router import api_router
    from app.core.database import get_db

    session = FakeDbSession(user=None)

    async def override_get_db():
        yield session

    application = FastAPI(title="Seed Request Test API")
    application.include_router(api_router, prefix="/api/v1")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    application.add_exception_handler(Exception, http_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)
    application.dependency_overrides[get_db] = override_get_db
    application.state.fake_session = session
    return application


@pytest.fixture
async def api_client(api_app):
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_header(user: User) -> dict[str, str]:
    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


class TestPublicCreate:
    async def test_create_201(self, api_client, api_app):
        api_app.state.fake_session.user = None
        r = await api_client.post(
            "/api/v1/seed-requests", json=_create_payload()
        )
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "pending"
        assert body["name"] == "Jane Doe"
        assert body["email"] == "jane@example.org"
        assert body["gene_ids"] == ["Glyma.01G000100", "Glyma.01G000200"]

    async def test_create_rejects_bad_email_422(self, api_client):
        r = await api_client.post(
            "/api/v1/seed-requests", json=_create_payload(email="nope")
        )
        assert r.status_code == 422

    async def test_create_rejects_too_many_gene_ids_422(self, api_client):
        r = await api_client.post(
            "/api/v1/seed-requests",
            json=_create_payload(
                gene_ids=[f"Glyma.{i:02d}G000100" for i in range(MAX_GENE_IDS + 1)]
            ),
        )
        assert r.status_code == 422

    async def test_create_rejects_missing_fields_422(self, api_client):
        r = await api_client.post(
            "/api/v1/seed-requests", json={"name": "Jane"}
        )
        assert r.status_code == 422


class TestAdminRBAC:
    async def test_admin_list_unauthenticated_401(self, api_client):
        r = await api_client.get("/api/v1/admin/seed-requests")
        assert r.status_code == 401

    async def test_admin_list_viewer_403(self, api_client, api_app):
        user = _make_user(RoleName.VIEWER)
        api_app.state.fake_session.user = user
        r = await api_client.get(
            "/api/v1/admin/seed-requests", headers=_auth_header(user)
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "forbidden"

    async def test_admin_list_researcher_403(self, api_client, api_app):
        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        r = await api_client.get(
            "/api/v1/admin/seed-requests", headers=_auth_header(user)
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "forbidden"

    async def test_admin_list_seed_manager_200(self, api_client, api_app):
        user = _make_user(RoleName.SEED_MANAGER)
        api_app.state.fake_session.user = user
        api_app.state.fake_session.requests = [
            _make_request(status="pending"),
            _make_request(status="approved", processed_at=datetime.now(UTC)),
        ]
        r = await api_client.get(
            "/api/v1/admin/seed-requests", headers=_auth_header(user)
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert body["page"] == 1
        assert len(body["items"]) == 2

    async def test_admin_list_pagination_params(self, api_client, api_app):
        user = _make_user(RoleName.SEED_MANAGER)
        api_app.state.fake_session.user = user
        api_app.state.fake_session.requests = [_make_request()]
        r = await api_client.get(
            "/api/v1/admin/seed-requests",
            params={"page": 2, "page_size": 10, "status": "pending"},
            headers=_auth_header(user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["page"] == 2
        assert body["page_size"] == 10

    async def test_admin_patch_unauthenticated_401(self, api_client):
        r = await api_client.patch(
            f"/api/v1/admin/seed-requests/{uuid.uuid4()}",
            json={"status": "approved"},
        )
        assert r.status_code == 401

    async def test_admin_patch_researcher_403(self, api_client, api_app):
        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        request = _make_request()
        api_app.state.fake_session.requests = [request]
        r = await api_client.patch(
            f"/api/v1/admin/seed-requests/{request.id}",
            json={"status": "approved"},
            headers=_auth_header(user),
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "forbidden"

    async def test_admin_patch_seed_manager_200(self, api_client, api_app):
        user = _make_user(RoleName.SEED_MANAGER)
        api_app.state.fake_session.user = user
        request = _make_request()
        api_app.state.fake_session.requests = [request]
        r = await api_client.patch(
            f"/api/v1/admin/seed-requests/{request.id}",
            json={"status": "approved"},
            headers=_auth_header(user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "approved"
        assert body["processed_by"] == str(user.id)

    async def test_admin_patch_illegal_transition_422(self, api_client, api_app):
        user = _make_user(RoleName.SEED_MANAGER)
        api_app.state.fake_session.user = user
        request = _make_request(status="pending")
        api_app.state.fake_session.requests = [request]
        r = await api_client.patch(
            f"/api/v1/admin/seed-requests/{request.id}",
            json={"status": "fulfilled"},
            headers=_auth_header(user),
        )
        # app.core.exceptions.ValidationError maps to 422 (UNPROCESSABLE).
        assert r.status_code == 422
        assert "Illegal seed request status transition" in r.json()["error"]["message"]
