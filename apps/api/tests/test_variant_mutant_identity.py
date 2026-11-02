"""PostgreSQL/HTTP regression: public mutant filters never bind hash surrogates."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import insert, select

from app.api.v1 import variants as routes
from app.api.v1.deps import get_current_user
from app.models.auth import Role, User
from app.models.content import Release, ReleaseStatus
from app.models.genomic import Assembly
from app.models.variant import MutantLine
from app.models.variant_facts import variant_facts
from app.services.release_context import ReleaseContext, get_release_context


@pytest.mark.parametrize("mapper", ["_row_to_response", "_row_to_detail"])
def test_unannotated_native_facts_have_null_optional_enums(mapper):
    from app.services.variant_service import VariantService

    result = getattr(VariantService, mapper)({
        "variant_id": 1, "assembly_key": "v4", "chromosome": "Chr01", "position": 1,
        "ref_allele": "A", "alt_allele": "T", "variant_type": "SNP",
        "consequence": "", "impact": "",
    })
    assert result.consequence is None
    assert result.impact is None


PUBLIC_ID = "SM7QF3Z9P2A"
PRIVATE_ID = "SM8RF3Z9P2B"
LINE_NAME = "PRIVATE_LAB_DESIGNATION_42"


@pytest.fixture
async def seeded_context(app, db_session):
    for identity, assembly in ((8101, "v4"), (8102, "v5")):
        db_session.add(Release(
            id=identity, version=f"identity-{identity}", name=assembly,
            status=ReleaseStatus.PUBLISHED, assembly_id=identity, assembly=assembly,
        ))
        db_session.add(Assembly(
            id=identity, name=assembly, version=assembly, species="Glycine max",
            release_id=identity,
        ))
    db_session.add_all([
        MutantLine(id=42, name=LINE_NAME, public_id=PUBLIC_ID, release_id=8101),
        MutantLine(
            id=43, name="PRIVATE_HIDDEN_LINE", public_id=PRIVATE_ID,
            release_id=8101, is_public=False,
        ),
    ])
    await db_session.flush()
    await db_session.execute(insert(variant_facts), [
        {
            "release_id": identity, "assembly_id": identity, "assembly_key": assembly,
            "variant_id": identity, "chromosome": "Chr01", "position": 12345,
            "ref_allele": "A", "alt_allele": "T", "variant_type": "SNP",
            "mutant_line_name": LINE_NAME,
            # Deliberately unrelated to mutant_lines.id (legacy hashes are not FKs).
            "mutant_line_surrogate_id": 709926958,
        }
        for identity, assembly in ((8101, "v4"), (8102, "v5"))
    ])
    await db_session.flush()
    context = ReleaseContext(release_id=8101, assembly_id=8101, assembly="v4")

    async def resolve():
        return context

    app.dependency_overrides[get_release_context] = resolve
    yield context
    app.dependency_overrides.pop(get_release_context, None)


@pytest.mark.asyncio
async def test_public_filter_matches_name_not_unrelated_hash(client, seeded_context):
    response = await client.get("/api/v1/variants", params={
        "mutant_line_public_id": PUBLIC_ID, "assembly": "v4",
    })
    assert response.status_code == 200
    assert [item["variant_id"] for item in response.json()["items"]] == ["8101"]
    for private_value in (LINE_NAME, "709926958", "mutant_line_surrogate_id", "internal_id"):
        assert private_value not in response.text
    other_assembly = await client.get("/api/v1/variants", params={
        "mutant_line_public_id": PUBLIC_ID, "assembly": "v5",
    })
    assert other_assembly.status_code == 200
    assert other_assembly.json()["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value,expected", [("42", 422), ("709926958", 422), (PRIVATE_ID, 404)])
async def test_private_or_internal_locators_do_not_resolve(client, seeded_context, value, expected):
    response = await client.get("/api/v1/variants", params={"mutant_line_public_id": value})
    assert response.status_code == expected
    assert LINE_NAME not in response.text
    assert "PRIVATE_HIDDEN_LINE" not in response.text


@pytest.mark.asyncio
async def test_public_id_cannot_resolve_in_another_release(app, client, seeded_context):
    async def other_release():
        return ReleaseContext(release_id=8102, assembly_id=8102, assembly="v5")

    app.dependency_overrides[get_release_context] = other_release
    response = await client.get("/api/v1/variants", params={"mutant_line_public_id": PUBLIC_ID})
    assert response.status_code == 404
    assert LINE_NAME not in response.text


@pytest.fixture
async def export_caller(app, monkeypatch, db_session):
    """A real researcher account: the export record is owned by a user row."""
    role = (
        await db_session.execute(select(Role).where(Role.name == "researcher"))
    ).scalar_one()
    user = User(
        username="export-caller",
        email="export-caller@soymutdb.local",
        password_hash="x",
        is_active=True,
        is_deleted=False,
        role_rel=role,
    )
    db_session.add(user)
    await db_session.flush()

    async def researcher():
        return SimpleNamespace(
            id=user.id,
            role_rel=SimpleNamespace(name="researcher"),
            is_superuser=False,
        )

    app.dependency_overrides[get_current_user] = researcher
    enqueue = AsyncMock()
    monkeypatch.setattr(routes, "enqueue_task_event", enqueue)
    yield enqueue
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field", ["mutant_line_id", "mutant_line_name", "mutant_line_surrogate_id"],
)
async def test_export_rejects_private_filters_before_enqueue(
    client, seeded_context, export_caller, field,
):
    response = await client.post("/api/v1/variants/export", json={"filters": {field: "42"}})
    assert response.status_code == 422
    export_caller.assert_not_called()


@pytest.mark.asyncio
async def test_export_resolves_public_filter_in_api(client, seeded_context, export_caller):
    response = await client.post("/api/v1/variants/export", json={
        "filters": {"mutant_line_public_id": PUBLIC_ID, "assembly": "v4"},
    })
    assert response.status_code == 202
    filters = export_caller.call_args.kwargs["kwargs"]["filters"]
    assert filters["mutant_line_name"] == LINE_NAME
    assert filters["release_key"] == "8101"
    assert "mutant_line_id" not in filters
    assert "mutant_line_public_id" not in filters
    assert LINE_NAME not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("value,expected", [("42", 422), (PRIVATE_ID, 404)])
async def test_export_rejects_unresolvable_public_ids(
    client, seeded_context, export_caller, value, expected,
):
    response = await client.post("/api/v1/variants/export", json={
        "filters": {"mutant_line_public_id": value},
    })
    assert response.status_code == expected
    export_caller.assert_not_called()
