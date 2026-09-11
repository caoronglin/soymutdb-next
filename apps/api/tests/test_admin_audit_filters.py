"""Regression tests for administrator audit-log filters."""

from sqlalchemy import and_
from sqlalchemy.dialects.postgresql import dialect

from app.api.v1.admin import _build_conditions


def test_audit_search_includes_actor_and_ip_columns() -> None:
    conditions = _build_conditions(
        search="alice",
        action=None,
        user_id=None,
        ip_address=None,
        start_date=None,
        end_date=None,
    )

    sql = str(and_(*conditions).compile(dialect=dialect()))

    assert "audit_logs.ip_address" in sql
    assert "users.username" in sql
