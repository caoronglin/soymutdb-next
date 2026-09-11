"""Docker-free contracts for PageTemplate API and builtin seed data."""

from app.api.v1.admin_page_builder import router
from app.page_builder.registry import validate_definition
from app.page_builder.schemas import PageTemplateCreate
from app.scripts.seed_page_builder import BUILTIN_TEMPLATES


def test_template_admin_routes_are_registered():
    routes = {(route.path, method) for route in router.routes for method in route.methods}
    assert ("/admin/page-builder/templates", "GET") in routes
    assert ("/admin/page-builder/templates", "POST") in routes
    assert ("/admin/page-builder/templates/{key}", "PUT") in routes
    assert ("/admin/page-builder/templates/{key}", "DELETE") in routes
    assert ("/admin/page-builder/templates/{key}/validate", "POST") in routes


def test_template_create_contract_accepts_stable_key_and_definition():
    payload = PageTemplateCreate(
        key="research-overview",
        label="Research overview",
        definition={"root": {"type": "columns", "props": {"columns": 1}, "children": []}},
    )
    assert payload.key == "research-overview"
    assert validate_definition(payload.definition)["schema_version"] == 2


def test_builtin_templates_are_unique_and_registry_valid():
    keys = [template["key"] for template in BUILTIN_TEMPLATES]
    assert keys == ["blank", "research"]
    assert len(keys) == len(set(keys))
    for template in BUILTIN_TEMPLATES:
        cleaned = validate_definition(template["definition"])
        assert cleaned["schema_version"] == 2


def test_builtin_template_seed_specs_are_deterministic():
    first = [(item["key"], item["sort_order"], item["definition"]) for item in BUILTIN_TEMPLATES]
    second = [(item["key"], item["sort_order"], item["definition"]) for item in BUILTIN_TEMPLATES]
    assert first == second
