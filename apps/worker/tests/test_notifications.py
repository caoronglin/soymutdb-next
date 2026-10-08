"""Notification tests (D2): NotifyStore, create task, trigger helpers, plyer.

No docker / no DB / no broker: the notification write path runs against a
fake sync session and the trigger points are asserted with monkeypatched
helpers.  ``utils/notify.py`` is tested with and without plyer available.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any

import pytest

from soymutdb_worker.repositories import NotifyStore
from soymutdb_worker.tasks import notifications as notifications_module
from soymutdb_worker.tasks.notifications import (
    CREATE_NOTIFICATION_TASK,
    create_notification,
    notify_completed,
    notify_failed,
)
from soymutdb_worker.utils import notify as notify_utils


class _Result:
    def __init__(self, rows: list, rowcount: int | None = None):
        self._rows = rows
        self.rowcount = rowcount

    def first(self):
        return self._rows[0] if self._rows else None


def _extract(value):
    """Unwrap BindParameter / enum members to plain values."""
    while hasattr(value, "value") and not isinstance(value, str):
        value = value.value
    return value


class FakeSession:
    """Fake sync session for notifications + job-owner lookups."""

    def __init__(
        self,
        user_id: str | None = "user-1",
        existing_link: str | None = None,
        status: str | None = "pending",
        rowcount: int = 1,
    ):
        self.user_id = user_id
        self.existing_link = existing_link
        self.status = status
        self.rowcount = rowcount
        self.inserts: list[dict] = []

    def execute(self, stmt, params=None):
        table = getattr(stmt, "table", None)
        table_name = getattr(table, "name", None)
        text_sql = str(stmt)
        if table_name == "notifications" and hasattr(stmt, "_values"):
            values = {
                getattr(key, "name", key): _extract(value)
                for key, value in dict(getattr(stmt, "_values", {}) or {}).items()
            }
            self.inserts.append(values)
            return _Result([], rowcount=self.rowcount)
        if "FROM notifications" in text_sql:
            # SELECT id FROM notifications WHERE user_id=... AND link=...
            if self.existing_link:
                return _Result([("existing-id",)])
            return _Result([])
        if table_name in ("blast_jobs", "analysis_jobs", "gwas_jobs") and hasattr(stmt, "_values"):
            # status UPDATE — track transitions like the real stores.
            values = {
                getattr(key, "name", key): _extract(value)
                for key, value in dict(getattr(stmt, "_values", {}) or {}).items()
            }
            if "status" in values:
                self.status = values["status"]
            return _Result([], rowcount=self.rowcount)
        if "FROM blast_jobs" in text_sql or "FROM gwas_jobs" in text_sql:
            if "user_id" in text_sql:
                return _Result([(self.user_id,)]) if self.user_id else _Result([])
            return _Result([(self.status,)]) if self.status else _Result([])
        if "FROM analysis_jobs" in text_sql:
            if "user_id" in text_sql:
                return _Result([(self.user_id,)]) if self.user_id else _Result([])
            return _Result([(self.status,)]) if self.status else _Result([])
        return _Result([])


@contextmanager
def _fake_db(session: FakeSession):
    yield session


class FakeTask:
    def update_state(self, **kwargs):
        pass


def _call_task(task: Any, *args, **kwargs):
    """Invoke the raw task function (bypassing Celery's bound-task wrapper)."""
    return task.run.__func__(*args, **kwargs)


# ---------------------------------------------------------------------------
# NotifyStore
# ---------------------------------------------------------------------------


class TestNotifyStore:
    def test_create_inserts_row(self) -> None:
        session = FakeSession()
        inserted = NotifyStore(session).create(
            user_id="user-1",
            type="blast_completed",
            title="BLAST job completed",
            body="BLAST job abc12345 finished.",
            link="/blast/jobs/abc12345",
        )
        assert inserted is True
        assert len(session.inserts) == 1
        row = session.inserts[0]
        assert row["user_id"] == "user-1"
        assert row["type"] == "blast_completed"
        assert row["link"] == "/blast/jobs/abc12345"

    def test_create_is_idempotent_on_user_plus_link(self) -> None:
        """Same job link twice -> second call is skipped (one row only)."""
        session = FakeSession(existing_link="/blast/jobs/abc12345")
        store = NotifyStore(session)
        assert (
            store.create(
                user_id="user-1",
                type="blast_completed",
                title="t",
                body="b",
                link="/blast/jobs/abc12345",
            )
            is False
        )
        assert session.inserts == []

    def test_create_without_link_always_inserts(self) -> None:
        session = FakeSession()
        store = NotifyStore(session)
        assert store.create(user_id="user-1", type="seed_request", title="t", body="b") is True
        assert store.create(user_id="user-1", type="seed_request", title="t", body="b") is True
        assert len(session.inserts) == 2

    @pytest.mark.parametrize("kind", ["blast", "fastp", "scanpy", "gwas"])
    def test_get_job_user_id_resolves_owner(self, kind: str) -> None:
        session = FakeSession(user_id="user-42")
        assert NotifyStore(session).get_job_user_id("job-1", kind) == "user-42"

    def test_get_job_user_id_returns_none_when_missing(self) -> None:
        session = FakeSession(user_id=None)
        assert NotifyStore(session).get_job_user_id("job-1", "blast") is None

    def test_get_job_user_id_rejects_unknown_kind(self) -> None:
        with pytest.raises(ValueError, match="Unknown notification job kind"):
            NotifyStore(FakeSession()).get_job_user_id("job-1", "nope")


# ---------------------------------------------------------------------------
# create_notification task
# ---------------------------------------------------------------------------


class TestCreateNotificationTask:
    def test_task_name_and_queue_contract(self) -> None:
        assert CREATE_NOTIFICATION_TASK == "soymutdb_worker.tasks.notifications.create_notification"
        assert create_notification.name == CREATE_NOTIFICATION_TASK

    def test_task_writes_via_store(self, monkeypatch) -> None:
        session = FakeSession()
        calls: list[tuple] = []
        created = []

        class _SpyStore(NotifyStore):
            def create(self, **kwargs) -> bool:
                calls.append(kwargs)
                created.append(kwargs["type"])
                return True

        monkeypatch.setattr(notifications_module, "get_db", lambda: _fake_db(session))
        monkeypatch.setattr(notifications_module, "NotifyStore", _SpyStore)

        result = _call_task(
            create_notification,
            FakeTask(),
            user_id="user-1",
            type="gwas_failed",
            title="GWAS job failed",
            body="GWAS job abc failed.",
            link="/gwas/jobs/abc",
        )
        assert result is True
        assert created == ["gwas_failed"]
        assert calls[0]["user_id"] == "user-1"
        assert calls[0]["link"] == "/gwas/jobs/abc"


# ---------------------------------------------------------------------------
# Trigger helpers (notify_completed / notify_failed)
# ---------------------------------------------------------------------------


class TestTriggerHelpers:
    def test_notify_completed_inserts_row_and_desktop_notifies(self, monkeypatch) -> None:
        session = FakeSession(user_id="user-9")
        desktop_calls: list[tuple] = []
        monkeypatch.setattr(notifications_module, "get_db", lambda: _fake_db(session))
        monkeypatch.setattr(
            notifications_module,
            "desktop_notify",
            lambda *a, **k: desktop_calls.append((a, k)) or True,
        )

        notify_completed("job-abc", kind="blast")

        assert len(session.inserts) == 1
        row = session.inserts[0]
        assert row["user_id"] == "user-9"
        assert row["type"] == "blast_completed"
        assert row["link"] == "/blast/jobs/job-abc"
        assert desktop_calls == [
            (("[SoyMutDB] BLAST job completed", "BLAST job job-abc… finished successfully."), {})
        ]

    def test_notify_failed_includes_error_excerpt(self, monkeypatch) -> None:
        session = FakeSession(user_id="user-9")
        monkeypatch.setattr(notifications_module, "get_db", lambda: _fake_db(session))
        monkeypatch.setattr(notifications_module, "desktop_notify", lambda *a, **k: True)

        notify_failed("job-abc", kind="gwas", error="EMMAX crashed with code 1")

        assert len(session.inserts) == 1
        row = session.inserts[0]
        assert row["type"] == "gwas_failed"
        assert row["link"] == "/gwas/jobs/job-abc"
        assert "EMMAX crashed" in row["body"]

    def test_analysis_kinds_share_analysis_type(self, monkeypatch) -> None:
        session = FakeSession(user_id="user-9")
        monkeypatch.setattr(notifications_module, "get_db", lambda: _fake_db(session))
        monkeypatch.setattr(notifications_module, "desktop_notify", lambda *a, **k: True)

        notify_completed("job-1", kind="fastp")
        notify_completed("job-2", kind="scanpy")

        assert [r["type"] for r in session.inserts] == [
            "analysis_completed",
            "analysis_completed",
        ]
        assert [r["link"] for r in session.inserts] == [
            "/analyses/job-1",
            "/analyses/job-2",
        ]

    def test_anonymous_job_is_skipped(self, monkeypatch) -> None:
        session = FakeSession(user_id=None)
        monkeypatch.setattr(notifications_module, "get_db", lambda: _fake_db(session))
        monkeypatch.setattr(notifications_module, "desktop_notify", lambda *a, **k: True)

        notify_completed("job-abc", kind="blast")

        assert session.inserts == []

    def test_dispatch_failure_is_swallowed(self, monkeypatch) -> None:
        def boom(*a, **k):
            raise RuntimeError("db gone")

        monkeypatch.setattr(notifications_module, "get_db", boom)
        # Must not raise: notifications are best-effort.
        notify_completed("job-abc", kind="blast")
        notify_failed("job-abc", kind="blast", error="x")


# ---------------------------------------------------------------------------
# Trigger points: job tasks call the helpers after mark_*
# ---------------------------------------------------------------------------


class TestTriggerPoints:
    def _monkeypatch_blast_execution(self, monkeypatch) -> None:
        import soymutdb_worker.tasks.blast as blast_module

        monkeypatch.setattr(blast_module, "get_blast_db_path", lambda db, **kw: "/tmp/db")
        monkeypatch.setattr(blast_module, "run_blast_command", lambda **kw: None)
        monkeypatch.setattr(
            blast_module,
            "parse_diamond_tabular",
            lambda path: {"hits": [], "total_hits": 0, "query_len": 0},
        )
        monkeypatch.setattr(blast_module, "_result_file_metadata", lambda p: ("abc123", 12))
        monkeypatch.setattr(blast_module, "upload_file", lambda *a, **k: None)
        monkeypatch.setattr(
            blast_module, "generate_presigned_url", lambda *a, **k: "https://s3.example/x"
        )

    def test_run_blast_calls_notify_completed_after_success(self, monkeypatch) -> None:
        import soymutdb_worker.tasks.blast as blast_module
        from soymutdb_worker.shared import BLAST_RUN_TASK, JobPayload

        calls: list[tuple] = []
        monkeypatch.setattr(
            blast_module, "notify_completed", lambda *a, **k: calls.append((a, k)) or None
        )
        self._monkeypatch_blast_execution(monkeypatch)
        session = FakeSession(user_id=None)  # job row present; owner irrelevant here
        monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))

        now = __import__("datetime").datetime.now(__import__("datetime").UTC)
        job_id = str(uuid.uuid4())
        payload = JobPayload(
            job_id=job_id,
            task_name=BLAST_RUN_TASK,
            payload={
                "job_id": job_id,
                "program": "blastp",
                "database": "williams82_prot",
                "sequence": "MKTIIALSYIFCLVFADYKDDDDKTRWQYNE",
                "evalue": 0.001,
                "max_target_seqs": 10,
            },
            idempotency_key=f"blast:{job_id}",
            created_at=now,
            updated_at=now,
        ).model_dump(mode="json")

        result = _call_task(blast_module.run_blast, FakeTask(), payload=payload)

        assert result["total_hits"] == 0
        assert calls == [((job_id,), {"kind": "blast"})]

    def test_run_blast_calls_notify_failed_after_error(self, monkeypatch) -> None:
        import soymutdb_worker.tasks.blast as blast_module
        from soymutdb_worker.shared import BLAST_RUN_TASK, JobPayload

        calls: list[tuple] = []
        monkeypatch.setattr(
            blast_module, "notify_failed", lambda *a, **k: calls.append((a, k)) or None
        )
        self._monkeypatch_blast_execution(monkeypatch)

        def boom(*args, **kwargs):
            raise RuntimeError("blast binary exploded")

        monkeypatch.setattr(blast_module, "run_blast_command", boom)
        session = FakeSession(user_id=None)
        monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))

        now = __import__("datetime").datetime.now(__import__("datetime").UTC)
        job_id = str(uuid.uuid4())
        payload = JobPayload(
            job_id=job_id,
            task_name=BLAST_RUN_TASK,
            payload={
                "job_id": job_id,
                "program": "blastp",
                "database": "williams82_prot",
                "sequence": "MKTIIALSYIFCLVFADYKDDDDKTRWQYNE",
                "evalue": 0.001,
                "max_target_seqs": 10,
            },
            idempotency_key=f"blast:{job_id}",
            created_at=now,
            updated_at=now,
        ).model_dump(mode="json")

        with pytest.raises(RuntimeError, match="blast binary exploded"):
            _call_task(blast_module.run_blast, FakeTask(), payload=payload)

        assert len(calls) == 1
        assert calls[0][0][0] == job_id
        assert calls[0][1]["kind"] == "blast"
        assert "blast binary exploded" in calls[0][1]["error"]


# ---------------------------------------------------------------------------
# utils/notify.py — plyer desktop channel
# ---------------------------------------------------------------------------


class TestDesktopNotify:
    def test_disabled_flag_is_noop(self, monkeypatch) -> None:
        monkeypatch.setenv("SOYMUTDB_DESKTOP_NOTIFY", "false")
        assert notify_utils.desktop_notify("t", "b") is False

    def test_enabled_but_plyer_missing_skips_gracefully(self, monkeypatch) -> None:
        monkeypatch.setenv("SOYMUTDB_DESKTOP_NOTIFY", "true")
        # Simulate the optional dependency being absent.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "plyer":
                raise ImportError("No module named 'plyer'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        # Must not raise; returns False and logs a warning.
        assert notify_utils.desktop_notify("t", "b") is False

    def test_enabled_with_plyer_shows_notification(self, monkeypatch) -> None:
        monkeypatch.setenv("SOYMUTDB_DESKTOP_NOTIFY", "true")
        shown: dict = {}

        class _FakeNotification:
            @staticmethod
            def notify(**kwargs):
                shown.update(kwargs)

        import sys
        import types

        plyer_mod = types.ModuleType("plyer")
        plyer_mod.notification = _FakeNotification
        monkeypatch.setitem(sys.modules, "plyer", plyer_mod)

        assert (
            notify_utils.desktop_notify("Title", "Message", app_name="SoyMutDB", timeout=5) is True
        )
        assert shown["title"] == "Title"
        assert shown["message"] == "Message"
        assert shown["app_name"] == "SoyMutDB"
        assert shown["timeout"] == 5

    def test_plyer_notify_failure_is_swallowed(self, monkeypatch) -> None:
        monkeypatch.setenv("SOYMUTDB_DESKTOP_NOTIFY", "true")

        class _Boom:
            @staticmethod
            def notify(**kwargs):
                raise OSError("no display")

        import sys
        import types

        plyer_mod = types.ModuleType("plyer")
        plyer_mod.notification = _Boom
        monkeypatch.setitem(sys.modules, "plyer", plyer_mod)

        assert notify_utils.desktop_notify("t", "b") is False
