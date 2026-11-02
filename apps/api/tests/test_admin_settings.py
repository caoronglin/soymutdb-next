"""Tests for admin settings API endpoints (``/api/v1/admin/settings/*``).

Covers: GET and PUT for settings sections, with RBAC enforcement.
Uses mocked DB session and authentication — no PostgreSQL required.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.exceptions import (
    SoyMutDBError,
    soy_mut_db_exception_handler,
    validation_exception_handler,
)

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _make_mock_session():
    """Return a mock DB session with ``AsyncMock`` query methods."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()

    default_result = MagicMock()
    default_result.scalars.return_value.all.return_value = []
    default_result.scalar_one_or_none.return_value = None
    default_result.scalar.return_value = 0
    session.execute.return_value = default_result
    session.scalar.return_value = 0
    return session


def _admin_user():
    """Return a mock User object with administrator privileges."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_superuser = True
    user.is_active = True
    user.is_deleted = False
    user.role_rel = MagicMock()
    user.role_rel.name = "administrator"
    return user


def _viewer_user():
    """Return a mock User object with viewer role (non-admin)."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_superuser = False
    user.is_active = True
    user.is_deleted = False
    user.role_rel = MagicMock()
    user.role_rel.name = "viewer"
    return user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session():
    """Return a clean mock DB session for admin settings endpoints."""
    return _make_mock_session()


@pytest.fixture
def admin_user():
    """Return a mock admin user."""
    return _admin_user()


@pytest.fixture
def viewer_user():
    """Return a mock viewer user (non-admin)."""
    return _viewer_user()


@pytest.fixture
async def client(mock_session, admin_user):
    """Create a test client with mocked DB session and admin auth.

    By default the current user is an administrator.  Override the
    ``get_current_user`` dependency to test non-admin scenarios.
    """
    from app.api.v1.admin_settings import router
    from app.api.v1.deps import get_current_user

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    # Register exception handlers so AuthorizationError returns 403 JSON
    app.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    async def override_get_db():
        yield mock_session

    async def override_get_current_user():
        return admin_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/admin/settings/{section}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSettings:
    """Tests for ``GET /api/v1/admin/settings/{section}``."""

    async def test_get_settings_returns_dict(self, client, mock_session):
        """Settings are returned as a key-value dict."""
        setting = MagicMock()
        setting.key = "blast.default_db"
        setting.value = "williams82_cds"

        result = MagicMock()
        result.scalars.return_value.all.return_value = [setting]
        mock_session.execute.return_value = result

        response = await client.get("/api/v1/admin/settings/blast")
        assert response.status_code == 200
        data = response.json()
        assert data == {"default_db": "williams82_cds"}

    async def test_get_settings_unknown_section_is_rejected(self, client, mock_session):
        """An unregistered section cannot expose arbitrary historical rows."""
        response = await client.get("/api/v1/admin/settings/empty_section")
        assert response.status_code == 404
        mock_session.execute.assert_not_awaited()

    async def test_get_settings_omits_unknown_and_secret_historical_rows(
        self, client, mock_session
    ):
        known = MagicMock(key="email.smtpHost", value="smtp.example.org")
        unknown = MagicMock(key="email.customPython", value="import os")
        secret = MagicMock(key="email.smtpPassword", value="legacy-plain-secret")
        result = MagicMock()
        result.scalars.return_value.all.return_value = [known, unknown, secret]
        mock_session.execute.return_value = result

        response = await client.get("/api/v1/admin/settings/email")

        assert response.status_code == 200
        assert response.json() == {"smtpHost": "smtp.example.org"}

    async def test_get_settings_multiple_keys(self, client, mock_session):
        """Multiple keys under the same section are all returned."""
        s1 = MagicMock()
        s1.key = "blast.max_sequences"
        s1.value = "100"
        s2 = MagicMock()
        s2.key = "blast.default_db"
        s2.value = "williams82_cds"

        result = MagicMock()
        result.scalars.return_value.all.return_value = [s1, s2]
        mock_session.execute.return_value = result

        response = await client.get("/api/v1/admin/settings/blast")
        assert response.status_code == 200
        data = response.json()
        assert data["max_sequences"] == "100"
        assert data["default_db"] == "williams82_cds"

    async def test_get_settings_requires_admin(self, client, mock_session, viewer_user):
        """Non-admin user receives 403."""
        from app.api.v1.deps import get_current_user

        async def override_get_current_user():
            return viewer_user

        client._transport.app.dependency_overrides[get_current_user] = override_get_current_user

        response = await client.get("/api/v1/admin/settings/blast")
        assert response.status_code == 403
        data = response.json()
        assert "error" in data


# ---------------------------------------------------------------------------
# Tests: PUT /api/v1/admin/settings/{section}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUpdateSettings:
    """Tests for ``PUT /api/v1/admin/settings/{section}``."""

    async def test_update_settings_new_key(self, client, mock_session):
        """New key-value pairs are created."""
        # First execute call: no existing row found -> None
        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None

        no_rows = MagicMock()
        no_rows.scalars.return_value.all.return_value = []

        mock_session.execute.side_effect = [not_found, no_rows]

        with patch("app.services.settings_service.log_action", new_callable=AsyncMock) as mock_log:
            response = await client.put(
                "/api/v1/admin/settings/blast",
                json={"default_db": "williams82_cds"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["default_db"] == "williams82_cds"

        # Verify SystemSetting was added to the session
        assert mock_session.add.called
        added_setting = next(
            call.args[0]
            for call in mock_session.add.call_args_list
            if getattr(call.args[0], "key", None) == "blast.default_db"
        )
        assert added_setting.key == "blast.default_db"
        assert added_setting.value == "williams82_cds"

        # Verify audit log was recorded
        mock_log.assert_awaited_once()
        assert mock_log.call_args[1]["action"] == "settings_update:blast"

    async def test_update_settings_existing_key(self, client, mock_session):
        """Existing key-value pairs are updated."""
        # The endpoint batch-fetches existing rows via `.scalars().all()`.
        existing_row = MagicMock()
        existing_row.key = "blast.default_db"
        existing_row.value = "williams82_cds"
        existing = MagicMock()
        existing.scalars.return_value.all.return_value = [existing_row]

        no_revision = MagicMock()
        no_revision.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_revision, existing]

        with patch("app.services.settings_service.log_action", new_callable=AsyncMock):
            response = await client.put(
                "/api/v1/admin/settings/blast",
                json={"default_db": "williams82_cds_v2"},
            )

        assert response.status_code == 200
        # The existing row's value should have been updated
        assert existing_row.value == "williams82_cds_v2"
        assert existing_row.updated_by is not None

    async def test_update_settings_multiple_keys(self, client, mock_session):
        """Multiple keys are upserted in a single request."""
        # One batch-fetch for existing rows under the section (none exist).
        not_found = MagicMock()
        not_found.scalars.return_value.all.return_value = []

        no_revision = MagicMock()
        no_revision.scalar_one_or_none.return_value = None

        mock_session.execute.side_effect = [
            no_revision,
            not_found,
        ]

        with patch("app.services.settings_service.log_action", new_callable=AsyncMock):
            response = await client.put(
                "/api/v1/admin/settings/blast",
                json={"max_sequences": "200", "default_db": "williams82_cds"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["max_sequences"] == "200"
        assert data["default_db"] == "williams82_cds"

    async def test_update_settings_requires_admin(self, client, mock_session, viewer_user):
        """Non-admin user receives 403 on PUT."""
        from app.api.v1.deps import get_current_user

        async def override_get_current_user():
            return viewer_user

        client._transport.app.dependency_overrides[get_current_user] = override_get_current_user

        response = await client.put(
            "/api/v1/admin/settings/blast",
            json={"default_db": "williams82_cds"},
        )
        assert response.status_code == 403

    async def test_update_settings_boolean_value(self, client, mock_session):
        """Boolean values are stored as lowercase strings."""
        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None

        no_rows = MagicMock()
        no_rows.scalars.return_value.all.return_value = []

        mock_session.execute.side_effect = [not_found, no_rows]

        with patch("app.services.settings_service.log_action", new_callable=AsyncMock):
            response = await client.put(
                "/api/v1/admin/settings/features",
                json={"registration": True},
            )

        assert response.status_code == 200
        assert mock_session.add.called
        added = next(
            call.args[0]
            for call in mock_session.add.call_args_list
            if getattr(call.args[0], "key", None) == "features.registration"
        )
        assert added.value == "true"

    async def test_update_settings_numeric_value(self, client, mock_session):
        """Numeric values are JSON-encoded for storage."""
        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None

        no_rows = MagicMock()
        no_rows.scalars.return_value.all.return_value = []

        mock_session.execute.side_effect = [not_found, no_rows]

        with patch("app.services.settings_service.log_action", new_callable=AsyncMock):
            response = await client.put(
                "/api/v1/admin/settings/blast",
                json={"max_sequences": 200},
            )

        assert response.status_code == 200
        assert mock_session.add.called
        added = next(
            call.args[0]
            for call in mock_session.add.call_args_list
            if getattr(call.args[0], "key", None) == "blast.max_sequences"
        )
        assert added.value == "200"

    async def test_update_settings_rejects_unknown_key_before_database_write(
        self, client, mock_session
    ):
        response = await client.put(
            "/api/v1/admin/settings/general",
            json={"unregistered": "value"},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
        mock_session.execute.assert_not_awaited()
        mock_session.add.assert_not_called()
        mock_session.commit.assert_not_awaited()

    async def test_update_settings_rejects_plaintext_secret_before_database_write(
        self, client, mock_session
    ):
        response = await client.put(
            "/api/v1/admin/settings/email",
            json={"smtpPassword": "do-not-store-me"},
        )

        assert response.status_code == 422
        assert "deployment secret" in response.json()["error"]["message"]
        mock_session.execute.assert_not_awaited()
        mock_session.add.assert_not_called()

    async def test_update_settings_rejects_retired_cdn_section(self, client, mock_session):
        response = await client.put(
            "/api/v1/admin/settings/cdn",
            json={"url": "https://cdn.example.com"},
        )

        assert response.status_code == 422
        assert "Unknown setting" in response.json()["error"]["message"]
        mock_session.execute.assert_not_awaited()
        mock_session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: typed settings contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_schema_exposes_typed_non_secret_contract(client, mock_session):
    response = await client.get("/api/v1/admin/settings/schema")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["sections"]["general"]["fields"]["siteName"]["kind"] == "string"
    assert body["sections"]["data"]["fields"]["maxExportRecords"] == {
        "kind": "integer",
        "default": 10_000,
        "permission": "administrator",
        "scope": "global",
        "hot_reload": True,
        "redaction": "none",
        "requires_approval": False,
        "allowed_values": [],
        "allowed_url_hosts": [],
        "minimum": 1,
        "maximum": 10_000_000,
        "max_length": 10_000,
    }
    assert "smtpPassword" not in body["sections"]["email"]["fields"]
    assert "cdn" not in body["sections"]
    assert body["sections"]["geo"]["fields"]["defaultCrawlerPolicy"] == {
        "kind": "enum",
        "default": "deny",
        "permission": "administrator",
        "scope": "global",
        "hot_reload": False,
        "redaction": "none",
        "requires_approval": True,
        "allowed_values": ["deny", "retrieval_and_training", "retrieval_only"],
        "allowed_url_hosts": [],
        "minimum": None,
        "maximum": None,
        "max_length": 10_000,
    }
    schema_text = str(body)
    assert "smtpPassword" not in schema_text
    assert "deployment secret" not in schema_text
    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_settings_document_returns_typed_values_and_current_version(client, mock_session):
    revision = MagicMock(version=4)
    revision_result = MagicMock()
    revision_result.scalar_one_or_none.return_value = revision
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = [
        MagicMock(key="email.smtpPort", value="587"),
        MagicMock(key="email.enableNotifications", value="false"),
        MagicMock(key="email.smtpPassword", value="must-not-leak"),
        MagicMock(key="email.unknown", value="must-not-leak"),
    ]
    mock_session.execute.side_effect = [revision_result, rows_result]

    response = await client.get("/api/v1/admin/settings/email/document")

    assert response.status_code == 200
    assert response.json() == {
        "section": "email",
        "version": 4,
        "values": {"smtpPort": 587, "enableNotifications": False},
    }
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_settings_openapi_exposes_typed_document_and_deprecates_legacy_read(
    client,
):
    schema = client._transport.app.openapi()
    paths = schema["paths"]

    document_response = paths["/api/v1/admin/settings/{section}/document"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    assert document_response == {"$ref": "#/components/schemas/SettingsDocumentResponse"}
    assert paths["/api/v1/admin/settings/{section}"]["get"]["deprecated"] is True
    assert paths["/api/v1/admin/settings/{section}"]["put"]["deprecated"] is True
    for operation in (
        paths["/api/v1/admin/settings/{section}"]["patch"],
        paths["/api/v1/admin/settings/{section}/rollback"]["post"],
    ):
        assert "409" in operation["responses"]
        assert operation["responses"]["409"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }


@pytest.mark.asyncio
async def test_settings_validate_normalizes_values_without_database_access(client, mock_session):
    response = await client.post(
        "/api/v1/admin/settings/validate",
        json={
            "section": "data",
            "values": {"maxExportRecords": "200"},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "section": "data",
        "valid": True,
        "values": {"maxExportRecords": 200},
    }
    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_settings_validate_returns_the_sanitized_storage_value(client, mock_session):
    response = await client.post(
        "/api/v1/admin/settings/validate",
        json={
            "section": "about",
            "values": {"content_en": "<p>safe</p><script>must-not-survive()</script>"},
        },
    )

    assert response.status_code == 200
    content = response.json()["values"]["content_en"]
    assert "<p>safe</p>" in content
    assert "script" not in content
    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("section", "values", "message"),
    [
        ("general", {"unregistered": "value"}, "Unknown setting"),
        ("email", {"smtpPassword": "do-not-store-me"}, "deployment secret"),
    ],
)
async def test_settings_validate_is_fail_closed(client, mock_session, section, values, message):
    response = await client.post(
        "/api/v1/admin/settings/validate",
        json={"section": section, "values": values},
    )

    assert response.status_code == 422
    assert message in response.json()["error"]["message"]
    assert "do-not-store-me" not in response.text
    mock_session.execute.assert_not_awaited()
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_settings_patch_rejects_unsafe_values_before_version_query(client, mock_session):
    response = await client.patch(
        "/api/v1/admin/settings/data",
        json={
            "expected_version": 0,
            "values": {"maxExportRecords": 0},
        },
    )

    assert response.status_code == 422
    assert "must be >= 1" in response.json()["error"]["message"]
    mock_session.execute.assert_not_awaited()
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_settings_patch_rejects_invalid_live_snapshot_before_mutation(
    mock_session,
):
    from app.core.exceptions import ValidationError
    from app.services.settings_service import patch_settings

    no_revision = MagicMock()
    no_revision.scalar_one_or_none.return_value = None
    invalid_row = MagicMock(key="data.maxExportRecords", value="not-an-integer")
    live_result = MagicMock()
    live_result.scalars.return_value.all.return_value = [invalid_row]
    mock_session.execute.side_effect = [no_revision, live_result]

    with pytest.raises(ValidationError, match="data.maxExportRecords"):
        await patch_settings(
            mock_session,
            section="data",
            expected_version=0,
            values={"maxExportRecords": 200},
            actor_id=uuid.uuid4(),
            ip_address=None,
        )

    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_settings_patch_creates_first_version_and_audit(client, mock_session):
    no_revision = MagicMock()
    no_revision.scalar_one_or_none.return_value = None
    no_rows = MagicMock()
    no_rows.scalars.return_value.all.return_value = []
    mock_session.execute.side_effect = [no_revision, no_rows]

    response = await client.patch(
        "/api/v1/admin/settings/data",
        json={
            "expected_version": 0,
            "values": {"maxExportRecords": 200},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "section": "data",
        "version": 1,
        "values": {"maxExportRecords": 200},
    }
    added = [call.args[0] for call in mock_session.add.call_args_list]
    setting_rows = [item for item in added if hasattr(item, "key")]
    assert {row.key: row.value for row in setting_rows} == {
        "data.maxExportRecords": "200",
    }
    revision = next(item for item in added if hasattr(item, "snapshot"))
    assert revision.version == 1
    assert revision.snapshot == {
        "maxExportRecords": "200",
    }
    audit = next(item for item in added if getattr(item, "action", None) == "settings_patch")
    assert audit.action == "settings_patch"
    assert mock_session.commit.await_count == 1


@pytest.mark.asyncio
async def test_settings_patch_rejects_stale_expected_version_with_stable_code(client, mock_session):
    current_revision = MagicMock(version=3)
    revision_result = MagicMock()
    revision_result.scalar_one_or_none.return_value = current_revision
    no_rows = MagicMock()
    no_rows.scalars.return_value.all.return_value = []
    mock_session.execute.side_effect = [revision_result, no_rows]

    response = await client.patch(
        "/api/v1/admin/settings/data",
        json={"expected_version": 2, "values": {"maxExportRecords": 200}},
    )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "settings_version_conflict",
        "message": "Settings version conflict",
        "details": {
            "section": "data",
            "expected_version": 2,
            "current_version": 3,
        },
    }
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_settings_patch_race_becomes_stable_version_conflict(mock_session):
    from sqlalchemy.exc import IntegrityError

    from app.core.exceptions import SettingsVersionConflictError
    from app.services.settings_service import patch_settings

    no_revision = MagicMock()
    no_revision.scalar_one_or_none.return_value = None
    no_rows = MagicMock()
    no_rows.scalars.return_value.all.return_value = []
    winner = MagicMock(version=1)
    winner_result = MagicMock()
    winner_result.scalar_one_or_none.return_value = winner
    mock_session.execute.side_effect = [no_revision, no_rows, winner_result]
    mock_session.commit.side_effect = IntegrityError(
        "duplicate revision", {}, Exception("unique violation")
    )

    with pytest.raises(SettingsVersionConflictError) as raised:
        await patch_settings(
            mock_session,
            section="data",
            expected_version=0,
            values={"maxExportRecords": 200},
            actor_id=uuid.uuid4(),
            ip_address=None,
        )

    assert raised.value.error_code == "settings_version_conflict"
    assert raised.value.details["current_version"] == 1
    mock_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_settings_history_returns_typed_audit_metadata_without_secrets(client, mock_session):
    actor_id = uuid.uuid4()
    revision = MagicMock(
        version=2,
        action="patch",
        snapshot={
            "smtpPort": "587",
            "enableNotifications": "true",
            "smtpPassword": "must-not-leak",
        },
        changes={"smtpPort": "587"},
        created_by=actor_id,
        created_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        rollback_from_version=None,
        reason=None,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [revision]
    mock_session.execute.return_value = result

    response = await client.get("/api/v1/admin/settings/email/history")

    assert response.status_code == 200
    assert response.json() == {
        "section": "email",
        "current_version": 2,
        "items": [
            {
                "version": 2,
                "action": "patch",
                "values": {"smtpPort": 587, "enableNotifications": True},
                "changes": {"smtpPort": 587},
                "actor_id": str(actor_id),
                "created_at": "2026-08-20T12:00:00Z",
                "rollback_from_version": None,
                "reason": None,
            }
        ],
    }
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_settings_rollback_restores_snapshot_as_new_audited_version(client, mock_session):
    current = MagicMock(
        version=3,
        snapshot={"smtpPort": "2525", "enableNotifications": "true"},
    )
    target = MagicMock(version=1, snapshot={"smtpPort": "587"})
    current_result = MagicMock()
    current_result.scalar_one_or_none.return_value = current
    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = target
    smtp_port = MagicMock(key="email.smtpPort", value="2525")
    notifications = MagicMock(key="email.enableNotifications", value="true")
    live_result = MagicMock()
    live_result.scalars.return_value.all.return_value = [smtp_port, notifications]
    delete_result = MagicMock()
    mock_session.execute.side_effect = [
        current_result,
        target_result,
        live_result,
        delete_result,
    ]

    response = await client.post(
        "/api/v1/admin/settings/email/rollback",
        json={
            "expected_version": 3,
            "target_version": 1,
            "reason": "restore known SMTP configuration",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "section": "email",
        "version": 4,
        "values": {"smtpPort": 587},
    }
    assert smtp_port.value == "587"
    assert "DELETE FROM system_settings" in str(mock_session.execute.await_args_list[3].args[0])
    added = [call.args[0] for call in mock_session.add.call_args_list]
    revision = next(item for item in added if getattr(item, "action", None) == "rollback")
    assert revision.version == 4
    assert revision.rollback_from_version == 1
    assert revision.reason == "restore known SMTP configuration"
    assert revision.changes == {
        "smtpPort": "587",
        "enableNotifications": None,
    }
    audit = next(item for item in added if getattr(item, "action", None) == "settings_rollback")
    assert audit.new_value["rollback_from_version"] == 1
    assert mock_session.commit.await_count == 1


@pytest.mark.asyncio
async def test_settings_rollback_revalidates_historical_snapshot(client, mock_session):
    current = MagicMock(version=2)
    target = MagicMock(
        version=1,
        snapshot={"maxExportRecords": "not-an-integer"},
    )
    current_result = MagicMock()
    current_result.scalar_one_or_none.return_value = current
    target_result = MagicMock()
    target_result.scalar_one_or_none.return_value = target
    live_result = MagicMock()
    live_result.scalars.return_value.all.return_value = []
    mock_session.execute.side_effect = [current_result, target_result, live_result]

    response = await client.post(
        "/api/v1/admin/settings/data/rollback",
        json={"expected_version": 2, "target_version": 1, "reason": "unsafe"},
    )

    assert response.status_code == 422
    assert "must be an integer" in response.json()["error"]["message"]
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_put_is_restricted_versioned_compatibility_layer(client, mock_session):
    no_revision = MagicMock()
    no_revision.scalar_one_or_none.return_value = None
    no_revision.scalars.return_value.all.return_value = []
    no_rows = MagicMock()
    no_rows.scalars.return_value.all.return_value = []
    stored = MagicMock(key="data.maxExportRecords", value="200")
    final_result = MagicMock()
    final_result.scalars.return_value.all.return_value = [stored]
    mock_session.execute.side_effect = [no_revision, no_rows, final_result]

    response = await client.put("/api/v1/admin/settings/data", json={"maxExportRecords": 200})

    assert response.status_code == 200
    added = [call.args[0] for call in mock_session.add.call_args_list]
    assert any(getattr(item, "action", None) == "put_compat" for item in added)
    revision = next(item for item in added if getattr(item, "action", None) == "put_compat")
    assert revision.version == 1
    assert revision.snapshot == {"maxExportRecords": "200"}
    audit = next(item for item in added if getattr(item, "action", None) == "settings_update:data")
    assert audit.new_value["version"] == 1
    assert response.json() == {"maxExportRecords": "200"}


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/site/about (public, editable About-us content, D4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPublicAbout:
    """``GET /site/about`` serves the ``about.*`` system settings publicly."""

    def _make_client(self, mock_session):
        from app.api.v1.site import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        async def override_get_db():
            yield mock_session

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    async def test_about_returns_all_fields_when_set(self, mock_session):
        rows = []
        for key, value in {
            "about.title_en": "About SoyMutDB",
            "about.title_zh": "关于我们",
            "about.summary_en": "Short intro",
            "about.content_en": "# Full markdown",
        }.items():
            row = MagicMock()
            row.key = key
            row.value = value
            rows.append(row)
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        mock_session.execute.return_value = result

        async with self._make_client(mock_session) as client:
            response = await client.get("/api/v1/site/about")
        assert response.status_code == 200
        body = response.json()
        assert body["title_en"] == "About SoyMutDB"
        assert body["title_zh"] == "关于我们"
        assert body["summary_en"] == "Short intro"
        assert body["content_en"] == "# Full markdown"
        # unset keys degrade to null
        assert body["summary_zh"] is None
        assert body["content_zh"] is None

    async def test_about_empty_db_returns_nulls(self, mock_session):
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = result

        async with self._make_client(mock_session) as client:
            response = await client.get("/api/v1/site/about")
        assert response.status_code == 200
        body = response.json()
        assert all(body[k] is None for k in body)
