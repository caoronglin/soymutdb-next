"""Safe, read-only import inspection/preview contracts."""

from __future__ import annotations

import base64
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import (
    SoyMutDBError,
    soy_mut_db_exception_handler,
    validation_exception_handler,
)
from app.models.auth import User


def _admin() -> User:
    return SimpleNamespace(
        id=uuid.uuid4(),
        is_superuser=True,
        role_rel=SimpleNamespace(name="administrator"),
    )


def _viewer() -> User:
    return SimpleNamespace(
        id=uuid.uuid4(),
        is_superuser=False,
        role_rel=SimpleNamespace(name="viewer"),
    )


@pytest.fixture
async def inspection_client():
    from app.api.v1.admin_modules import router
    from app.api.v1.deps import get_current_user

    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    application.state.current_user = _admin()

    async def current_user():
        return application.state.current_user

    application.dependency_overrides[get_current_user] = current_user
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        yield client, application


def _body(data: bytes, *, filename: str = "genes.tsv") -> dict[str, str]:
    return {
        "filename": filename,
        "content_base64": base64.b64encode(data).decode("ascii"),
    }


async def test_admin_can_inspect_valid_module_without_persisting(
    inspection_client,
) -> None:
    client, _ = inspection_client
    data = (
        b"gene_id\tchromosome\tstart\tend\tmutation_feature\n"
        b"G1\tChr01\t1\t9\tSNP\n"
        b"G2\tChr02\t10\t20\tDEL\n"
    )

    response = await client.post("/api/v1/admin/modules/genes/inspect", json=_body(data))

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 1
    assert body["module_key"] == "genes"
    assert body["format"] == "tsv"
    assert body["encoding"] == "utf-8"
    assert body["delimiter"] == "\t"
    assert body["headers"] == [
        "gene_id",
        "chromosome",
        "start",
        "end",
        "mutation_feature",
    ]
    assert body["row_count"] == 2
    assert body["rows"][0]["start"] == 1
    assert body["truncated"] is False
    assert body["validation"] == {"ok": True, "error_count": 0, "errors": []}
    assert len(body["checksum_sha256"]) == 64


async def test_validate_alias_returns_bounded_diagnostics(inspection_client) -> None:
    client, _ = inspection_client
    data = (
        b"gene_id\tchromosome\tstart\tend\n"
        b"G1\tChr01\t1\t9\n"
        b"G1\tChr01\t10\t20\n"
    )

    response = await client.post("/api/v1/admin/modules/genes/validate", json=_body(data))

    assert response.status_code == 200
    assert response.json()["validation"]["ok"] is False
    assert response.json()["validation"]["errors"][0]["code"] == "duplicate_key"


async def test_inspection_preview_is_capped_and_formula_cells_are_escaped(
    inspection_client,
) -> None:
    client, _ = inspection_client
    rows = [b"gene_id\tchromosome\tstart\tend\tmutation_feature"]
    rows.extend(
        f"G{i}\tChr01\t1\t9\t=HYPERLINK(\"https://evil.example\")".encode()
        for i in range(101)
    )

    response = await client.post(
        "/api/v1/admin/modules/genes/inspect", json=_body(b"\n".join(rows) + b"\n")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["row_count"] == 101
    assert len(body["rows"]) == 100
    assert body["truncated"] is True
    assert body["rows"][0]["mutation_feature"].startswith("'=")


async def test_inspection_requires_admin(inspection_client) -> None:
    client, application = inspection_client
    application.state.current_user = _viewer()

    response = await client.post(
        "/api/v1/admin/modules/genes/inspect",
        json=_body(b"gene_id\tchromosome\tstart\tend\n"),
    )

    assert response.status_code == 403


async def test_inspection_rejects_unknown_schema_and_invalid_base64(
    inspection_client,
) -> None:
    client, _ = inspection_client

    unknown = await client.post(
        "/api/v1/admin/modules/not_registered/inspect",
        json=_body(b"a\n"),
    )
    invalid = await client.post(
        "/api/v1/admin/modules/genes/inspect",
        json={"filename": "genes.tsv", "content_base64": "not base64%%%"},
    )

    assert unknown.status_code == 404
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    ("schema", "values"),
    [
        (
            "MultipartStartRequest",
            {
                "filename": "plugin.py",
                "type": "module_tsv",
                "part_count": 1,
                "content_type": "text/x-python",
            },
        ),
        (
            "ImportCreateRequest",
            {
                "filename": "plugin.sh",
                "type": "module_tsv",
                "file_path": "s3://bucket/plugin.sh",
                "idempotency_key": "no-code",
            },
        ),
    ],
)
def test_admin_import_contract_rejects_code_files(schema: str, values: dict[str, object]) -> None:
    from app.schemas import data_publishing

    with pytest.raises(PydanticValidationError, match="code files"):
        getattr(data_publishing, schema)(**values)
