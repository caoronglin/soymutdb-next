"""The exported OpenAPI document must declare what each error handler sends.

Complements ``scripts/test_openapi_422_unified_envelope.py``: that guard reads
the *committed* snapshot and generated client, so it can run without a Python
3.15 venv. This one reads the schema built from the live ``app.main:app``, so
a change to the builder is caught before anyone regenerates the artifacts.

The offline guard pins the 422/500/4xx/5xx envelope shapes by counting the
generated client's response bodies; this one asserts the same contract at the
source of the export. Together a co-revert of builder + snapshot + client
cannot pass silently.
"""
from __future__ import annotations

import pytest

from app.main import app

METHODS = {"get", "put", "post", "patch", "delete"}
ENVELOPE = {"$ref": "#/components/schemas/ErrorResponse"}
VALIDATION = {"$ref": "#/components/schemas/ValidationErrorResponse"}


@pytest.fixture(scope="module")
def schema() -> dict:
    return app.openapi()


def _operations(schema: dict):
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method in METHODS and isinstance(operation, dict):
                yield method.upper(), path, operation


def _ref(response: dict):
    return response.get("content", {}).get("application/json", {}).get("schema")


def test_every_operation_declares_a_unified_500(schema: dict) -> None:
    for method, path, operation in _operations(schema):
        responses = operation.get("responses", {})
        assert "500" in responses, f"{method} {path} missing 500"
        assert _ref(responses["500"]) == ENVELOPE, (
            f"{method} {path} declares 500 as {_ref(responses['500'])!r}; "
            "unhandled_exception_handler always sends ErrorResponse"
        )


def test_every_operation_declares_a_unified_422(schema: dict) -> None:
    for method, path, operation in _operations(schema):
        responses = operation.get("responses", {})
        assert "422" in responses, f"{method} {path} missing 422"
        assert _ref(responses["422"]) == VALIDATION, (
            f"{method} {path} declares 422 as {_ref(responses['422'])!r}; "
            "validation_exception_handler always sends ValidationErrorResponse"
        )


def test_every_other_error_status_uses_the_unified_envelope(schema: dict) -> None:
    """409/429 (and any future 4xx/5xx) all go through ErrorResponse."""
    seen = 0
    for method, path, operation in _operations(schema):
        for code, response in operation.get("responses", {}).items():
            if code in ("422", "500") or not (
                code.startswith("4") or code.startswith("5")
            ):
                continue
            seen += 1
            assert _ref(response) == ENVELOPE, (
                f"{method} {path} declares {code} as {_ref(response)!r}; "
                "every non-422 error handler sends ErrorResponse"
            )
    # A floor, so a builder that stops emitting 409/429 entirely cannot pass
    # vacuously with zero error responses to check.
    assert seen >= 4, f"only {seen} non-422/500 error responses declared"


def test_both_error_schemas_are_defined(schema: dict) -> None:
    schemas = schema["components"]["schemas"]
    assert "ErrorResponse" in schemas
    assert "ValidationErrorResponse" in schemas
