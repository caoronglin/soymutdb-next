"""OpenAPI contract and unified error-envelope tests.

No database / testcontainers required:

- OpenAPI export: expected paths, error schemas, security schemes, and the
  422/500 responses attached to every operation.
- Runtime envelope: 500 responses never leak internals, 422 responses carry
  sanitised field-level errors, every error carries ``request_id``.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.exceptions import AuthorizationError
from app.core.security import RoleName, require_admin_roles
from app.main import app

EXPECTED_PATHS = [
    "/api/v1/stats/homepage",
    "/api/v1/stats/summary/impact",
    "/api/v1/stats/summary/variant-types",
    "/api/v1/stats/chromosome-density",
    "/api/v1/stats/discovery-trend",
    "/api/v1/stats/releases",
    "/api/v1/stats/mutagens",
    "/api/v1/admin/dashboard-stats",
    "/api/v1/admin/dashboard-series",
    "/api/v1/admin/releases",
    "/api/v1/admin/releases/{release_id}",
    "/api/v1/admin/releases/{release_id}/validate",
    "/api/v1/admin/releases/{release_id}/ready",
    "/api/v1/admin/releases/{release_id}/publish",
    "/api/v1/admin/releases/{release_id}/rollback",
    "/api/v1/health/ready",
]

SCHEMA = app.openapi()


class _RequestIdMiddleware(BaseHTTPMiddleware):
    """Mirror of the production middleware so request_id is set in tests."""

    async def dispatch(self, request, call_next):
        import uuid

        request.state.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


@pytest.fixture(scope="module")
def error_app():
    """A minimal FastAPI app with the production exception handlers."""
    from fastapi import FastAPI, HTTPException
    from fastapi.exceptions import RequestValidationError

    from app.core.exceptions import (
        SoyMutDBError,
        http_exception_handler,
        soy_mut_db_exception_handler,
        unhandled_exception_handler,
        validation_exception_handler,
    )

    test_app = FastAPI()
    test_app.add_middleware(_RequestIdMiddleware)
    test_app.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    test_app.add_exception_handler(HTTPException, http_exception_handler)
    test_app.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    test_app.add_exception_handler(Exception, unhandled_exception_handler)

    @test_app.get("/boom")
    async def boom() -> None:
        raise RuntimeError(
            "secret db password: hunter2 -- /var/lib/postgresql/data/pg_hba.conf"
        )

    @test_app.get("/not-found")
    async def not_found() -> None:
        raise HTTPException(status_code=404, detail="No such resource")

    @test_app.get("/bad-request")
    async def bad_request() -> None:
        raise HTTPException(status_code=400, detail="Bad input")

    @test_app.get("/need-int")
    async def need_int(x: int) -> dict[str, int]:
        return {"x": x}

    return test_app


@pytest.fixture
async def error_client(error_app):
    transport = ASGITransport(app=error_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# OpenAPI export contract
# ---------------------------------------------------------------------------


class TestOpenApiContract:
    def test_require_admin_roles_rejects_non_administrator(self):
        assert require_admin_roles([RoleName.ADMINISTRATOR.value]) is None
        with pytest.raises(AuthorizationError):
            require_admin_roles([RoleName.AUDITOR.value])

    def test_dashboard_paths_require_authentication(self):
        for path in ("/api/v1/admin/dashboard-stats", "/api/v1/admin/dashboard-series"):
            assert SCHEMA["paths"][path]["get"].get("security")

    def test_release_actions_document_confirmation_and_reason(self):
        schema = SCHEMA["components"]["schemas"]["ReleaseActionRequest"]["properties"]
        assert schema["confirm"]["const"] is True
        assert schema["reason"]["minLength"] == 1

    def test_analysis_tool_contracts_require_assembly_context(self):
        schemas = SCHEMA["components"]["schemas"]
        for name in ("ExpPatternRequest", "EnrichmentRequest"):
            assert "assembly_id" in schemas[name]["required"]
        for name in (
            "ExpPatternResponse",
            "EnrichmentResponse",
            "EnrichmentGseaResponse",
        ):
            assert {
                "assembly_id",
                "release_id",
                "assembly_name",
                "assembly_version",
            }.issubset(schemas[name]["required"])
        for name in ("EnrichmentResponse", "EnrichmentGseaResponse"):
            assert "annotation_source" in schemas[name]["required"]
        for path in ("/api/v1/tools/exppattern", "/api/v1/tools/enrichment"):
            parameters = SCHEMA["paths"][path]["post"]["parameters"]
            assert any(
                item.get("in") == "header"
                and item.get("name") == "X-SoyMutDB-Release"
                for item in parameters
            )

    def test_expected_paths_present(self):
        paths = set(SCHEMA["paths"])
        for expected in EXPECTED_PATHS:
            assert expected in paths, f"missing path {expected}"

    def test_error_schemas_registered(self):
        schemas = set(SCHEMA["components"]["schemas"])
        for name in ("ErrorDetail", "ErrorResponse", "FieldError", "ValidationErrorResponse"):
            assert name in schemas, f"missing schema {name}"

    def test_error_code_catalog_is_exported(self):
        catalog = SCHEMA["x-error-codes"]
        assert catalog["not_found"] == ""
        assert "plugin_disabled" in catalog
        assert "settings_version_conflict" in catalog
        assert list(catalog) == sorted(catalog)

    def test_error_code_catalog_includes_http_exception_fallback(self):
        # http_exception_handler emits ``http_error`` for generic HTTPException
        # statuses (400/413/500/503/...). It has no SoyMutDBError subclass, so
        # a hierarchy-only catalog silently omits a code clients can receive.
        from app.core.exceptions import HTTP_ERROR_CODE, error_code_catalog

        assert HTTP_ERROR_CODE == "http_error"
        assert HTTP_ERROR_CODE in SCHEMA["x-error-codes"]
        assert SCHEMA["x-error-codes"] == error_code_catalog()

    def test_error_status_contract_matches_runtime(self):
        from app.core.exceptions import error_status_map

        status = SCHEMA["x-error-status"]
        assert status["by_code"] == error_status_map()
        # Derived from the hierarchy: every published code maps to the status
        # its exception emits, except the multi-status fallback.
        assert status["by_code"]["not_found"] == 404
        assert status["by_code"]["service_unavailable"] == 503
        assert status["by_code"]["http_error"] is None
        assert status["http_exception"]["fallback"] == "http_error"
        assert status["http_exception"]["404"] == "not_found"

    def test_safe_methods_are_declared_idempotent(self):
        for path, path_item in SCHEMA["paths"].items():
            for method, operation in path_item.items():
                if method in {"get", "put", "delete"}:
                    assert operation["x-idempotent"] is True, f"{method.upper()} {path}"

    def test_homolog_search_declares_cursor_pagination_fields(self):
        operation = SCHEMA["paths"]["/api/v1/homologs/search"]["get"]
        assert operation["x-pagination"] == {
            "mode": "keyset-optional",
            "cursor_parameter": "cursor",
            "next_cursor_field": "next_cursor",
            "has_more_field": "has_more",
            "cursor_is_exclusive": True,
            "fallback": "offset",
        }
        parameters = {parameter["name"] for parameter in operation["parameters"]}
        assert {"cursor", "page", "page_size"} <= parameters

    def test_login_rate_limit_response_documents_retry_after_only(self):
        responses = SCHEMA["paths"]["/api/v1/auth/login"]["post"]["responses"]
        response = responses["429"]
        assert response["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
        assert response["headers"] == {
            "Retry-After": {
                "description": "Seconds until this login attempt may be retried.",
                "schema": {"type": "integer", "minimum": 1},
            }
        }
        assert "429" not in SCHEMA["paths"]["/api/v1/health/ready"]["get"]["responses"]

    def test_security_schemes_documented(self):
        schemes = SCHEMA["components"]["securitySchemes"]
        assert "HTTPBearer" in schemes
        assert "refreshCookie" in schemes
        assert schemes["refreshCookie"]["in"] == "cookie"

    def test_every_operation_documents_error_responses(self):
        for path, path_item in SCHEMA["paths"].items():
            for method, operation in path_item.items():
                if method not in ("get", "post", "put", "patch", "delete"):
                    continue
                responses = operation.get("responses", {})
                assert "422" in responses, f"{method.upper()} {path} missing 422"
                assert "500" in responses, f"{method.upper()} {path} missing 500"

    def test_stats_paths_are_public(self):
        for path in ("/api/v1/stats/homepage", "/api/v1/stats/summary/impact"):
            operation = SCHEMA["paths"][path]["get"]
            assert "security" not in operation or not operation["security"]

    def test_admin_dashboard_requires_auth(self):
        op = SCHEMA["paths"]["/api/v1/admin/dashboard-stats"]["get"]
        security = op.get("security")
        assert security, "dashboard-stats must require authentication"

    def test_admin_dashboard_stats_uses_camel_case(self):
        props = SCHEMA["components"]["schemas"]["AdminDashboardStats"]["properties"]
        assert set(props) == {
            "totalUsers",
            "activeReleases",
            "totalVariants",
            "queryP95Ms",
            "usersChange",
            "releasesChange",
            "variantsChange",
            "queryP95Change",
        }

    def test_gene_variant_and_track_paths_are_exported(self):
        for path in (
            "/api/v1/genes",
            "/api/v1/genes/{gene_id}",
            "/api/v1/variants",
            "/api/v1/variants/{variant_id}",
            "/api/v1/tracks",
            "/api/v1/tracks/{track_id}",
        ):
            assert path in SCHEMA["paths"], f"missing contract path {path}"

    def test_blast_jobs_list_and_results_paths_are_exported(self):
        assert "get" in SCHEMA["paths"]["/api/v1/blast/jobs"]
        assert "/api/v1/blast/jobs/{job_id}/results" in SCHEMA["paths"]


# ---------------------------------------------------------------------------
# Runtime error envelope
# ---------------------------------------------------------------------------


class TestErrorEnvelope:
    async def test_500_never_leaks_internals(self, error_client):
        response = await error_client.get("/boom")
        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "internal_error"
        assert body["status_code"] == 500
        assert body["request_id"]
        raw = response.text
        assert "hunter2" not in raw
        assert "RuntimeError" not in raw
        assert "pg_hba.conf" not in raw
        assert "Traceback" not in raw

    async def test_422_has_field_level_errors(self, error_client):
        response = await error_client.get("/need-int")
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "validation_error"
        assert body["request_id"]
        errors = body["errors"]
        assert isinstance(errors, list) and errors
        error = errors[0]
        # Only sanitised fields — no pydantic internals (loc tuples, ctx, url).
        assert set(error.keys()) == {"field", "message", "type"}
        assert error["field"] == "query.x"

    async def test_http_exception_uses_envelope(self, error_client):
        response = await error_client.get("/not-found")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "not_found"
        assert body["error"]["message"] == "No such resource"
        assert body["request_id"]

    async def test_http_exception_fallback_code_is_published(self, error_client):
        # A generic 400 has no dedicated domain code; the handler falls back to
        # ``http_error``. That code must be in the published catalog exactly
        # because a client can receive it from this path.
        from app.core.exceptions import HTTP_ERROR_CODE, error_code_catalog

        response = await error_client.get("/bad-request")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == HTTP_ERROR_CODE
        assert HTTP_ERROR_CODE in error_code_catalog()
        assert HTTP_ERROR_CODE in SCHEMA["x-error-codes"]

    async def test_request_id_echoed_in_header(self, error_client):
        response = await error_client.get("/not-found", headers={"X-Request-ID": "req-123"})
        assert response.json()["request_id"] == "req-123"
        assert response.headers["X-Request-ID"] == "req-123"
