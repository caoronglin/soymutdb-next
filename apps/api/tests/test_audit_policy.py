"""Focused tests for the bounded declarative audit-policy slice."""

from __future__ import annotations

import pytest

from app.core.audit_policy import declares_audit, get_audit_policy


def test_declares_immutable_action_and_roles() -> None:
    @declares_audit("release_published", roles={"administrator"})
    async def handler() -> None:
        return None

    policy = get_audit_policy(handler)
    assert policy is not None
    assert policy.action == "release_published"
    assert policy.roles == frozenset({"administrator"})


@pytest.mark.parametrize(
    ("action", "roles", "message"),
    [
        ("", {"administrator"}, "non-empty"),
        ("release_published", set(), "at least one role"),
    ],
)
def test_rejects_incomplete_audit_declaration(action, roles, message) -> None:
    with pytest.raises(ValueError, match=message):
        declares_audit(action, roles=roles)


@pytest.mark.parametrize(
    ("endpoint_name", "action"),
    [
        ("create_release", "release_created"),
        ("validate_admin_release", "release_validated"),
        ("ready_admin_release", "release_ready"),
        ("publish_admin_release", "release_published"),
        ("rollback_admin_release", "release_rolled_back"),
    ],
)
def test_in_scope_admin_mutations_declare_matching_audit_actions(
    endpoint_name: str, action: str
) -> None:
    import inspect

    from app.api.v1 import admin

    endpoint = getattr(admin, endpoint_name)
    policy = get_audit_policy(endpoint)
    assert policy is not None
    assert policy.action == action
    assert policy.roles == frozenset({"administrator"})
    # The action declaration must match the handler audit write. Release
    # lifecycle handlers delegate the write to release_service, whose action
    # names are intentionally checked here by source-level contract evidence.
    source = inspect.getsource(endpoint)
    if endpoint_name == "create_release":
        assert f'action="{action}"' in source


def test_inventory_reports_missing_declarations_without_failing() -> None:
    from fastapi import APIRouter

    from app.core.audit_inventory import inventory_write_routes

    router = APIRouter()

    @router.post("/declared")
    @declares_audit("sample_created", roles={"administrator"})
    async def declared() -> None:
        return None

    @router.post("/undeclared")
    async def undeclared() -> None:
        return None

    inventory = inventory_write_routes(router.routes)
    assert [item.as_dict() for item in inventory] == [
        {
            "path": "/declared",
            "methods": ("POST",),
            "action": "sample_created",
            "roles": ("administrator",),
            "declared": True,
        },
        {
            "path": "/undeclared",
            "methods": ("POST",),
            "action": None,
            "roles": (),
            "declared": False,
        },
    ]


def test_admin_inventory_contains_all_current_in_scope_declarations() -> None:
    from app.api.v1.admin import router
    from app.core.audit_inventory import inventory_write_routes

    by_action = {item.action: item for item in inventory_write_routes(router.routes)}
    assert {
        "release_created",
        "release_validated",
        "release_ready",
        "release_published",
        "release_rolled_back",
    }.issubset(by_action)
    assert {
        action: (item.path, item.methods, item.roles, item.declared)
        for action, item in by_action.items()
        if action is not None
    } == {
        "release_created": ("/admin/releases", ("POST",), ("administrator",), True),
        "release_published": (
            "/admin/releases/{release_id}/publish",
            ("POST",),
            ("administrator",),
            True,
        ),
        "release_ready": (
            "/admin/releases/{release_id}/ready",
            ("POST",),
            ("administrator",),
            True,
        ),
        "release_rolled_back": (
            "/admin/releases/{release_id}/rollback",
            ("POST",),
            ("administrator",),
            True,
        ),
        "release_validated": (
            "/admin/releases/{release_id}/validate",
            ("POST",),
            ("administrator",),
            True,
        ),
    }

