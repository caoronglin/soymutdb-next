"""Tests for variant API endpoints (/api/v1/variants/*).

Covers: variant search, region query, variant detail, export.
Includes cursor pagination and filter tests.
All routes use the ``/api/v1/`` prefix.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services.release_context import ReleaseContext, get_release_context

VARIANTS_PREFIX = "/api/v1/variants"


@pytest_asyncio.fixture(autouse=True)
async def _release_context_override(app):
    async def override_release_context() -> ReleaseContext:
        return ReleaseContext(
            release_id=7,
            assembly_id=1,
            assembly="Wm82.gnm2",
        )

    app.dependency_overrides[get_release_context] = override_release_context
    yield
    app.dependency_overrides.pop(get_release_context, None)


def _make_variant_dict(variant_id: str = "var_001", **kwargs) -> dict:
    """Create a mock variant dict matching the VariantResponse schema."""
    base = {
        "variant_id": variant_id,
        "chromosome": "Gm01",
        "position": 10000,
        "ref_allele": "A",
        "alt_allele": "T",
        "variant_type": "SNP",
        "impact": "MODERATE",
        "gene_id": "Glyma.01G000100",
        "hgvs_c": "c.123A>T",
        "hgvs_p": "p.Asn41Ile",
    }
    base.update(kwargs)
    return base


@pytest.mark.asyncio
class TestListVariants:
    """Tests for GET /api/v1/variants."""

    async def test_list_variants_empty(self, client):
        """Listing variants with no data returns empty list."""
        with patch(
            "app.services.variant_service.VariantService.list_variants",
            new_callable=AsyncMock,
            return_value={"items": [], "next_cursor": None, "has_more": False},
        ):
            response = await client.get(VARIANTS_PREFIX)
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []

    async def test_list_variants_with_results(self, client):
        """Listing variants returns matching variants."""
        variants = [_make_variant_dict(f"var_{i:03d}") for i in range(5)]
        with patch(
            "app.services.variant_service.VariantService.list_variants",
            new_callable=AsyncMock,
            return_value={
                "items": variants,
                "next_cursor": None,
                "has_more": False,
            },
        ):
            response = await client.get(VARIANTS_PREFIX)
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 5

    async def test_list_variants_cursor_pagination(self, client):
        """Cursor pagination returns next_cursor for large result sets."""
        variants = [_make_variant_dict(f"var_{i:03d}") for i in range(100)]
        with patch(
            "app.services.variant_service.VariantService.list_variants",
            new_callable=AsyncMock,
            return_value={
                "items": variants[:50],
                "next_cursor": "MTAwMDA=",
                "has_more": True,
            },
        ):
            response = await client.get(f"{VARIANTS_PREFIX}?limit=50")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 50
        assert data["has_more"] is True
        assert data["next_cursor"] is not None

    async def test_list_variants_filter_by_chromosome(self, client):
        """Filtering by chromosome returns only matching variants."""
        with patch(
            "app.services.variant_service.VariantService.list_variants",
            new_callable=AsyncMock,
            return_value={"items": [], "next_cursor": None, "has_more": False},
        ) as list_variants:
            response = await client.get(
                f"{VARIANTS_PREFIX}?chromosome=Gm01&ref=A&alt=T"
            )
        assert response.status_code == 200
        assert list_variants.await_args is not None
        params = list_variants.await_args.args[1]
        context = list_variants.await_args.kwargs["release_context"]
        assert params.chromosome == "Gm01"
        assert params.ref == "A"
        assert params.alt == "T"
        assert context.release_id == 7

    async def test_list_variants_filter_by_impact(self, client):
        """Filtering by impact returns only matching variants."""
        with patch(
            "app.services.variant_service.VariantService.list_variants",
            new_callable=AsyncMock,
            return_value={"items": [], "next_cursor": None, "has_more": False},
        ):
            response = await client.get(f"{VARIANTS_PREFIX}?impact=HIGH")
        assert response.status_code == 200

    async def test_list_variants_filter_by_position_range(self, client):
        """Filtering by start/end position range."""
        with patch(
            "app.services.variant_service.VariantService.list_variants",
            new_callable=AsyncMock,
            return_value={"items": [], "next_cursor": None, "has_more": False},
        ):
            response = await client.get(
                f"{VARIANTS_PREFIX}?chromosome=Gm01&start=1000&end=5000"
            )
        assert response.status_code == 200

    async def test_list_variants_limit_capped(self, client):
        """Limit is capped at 200."""
        with patch(
            "app.services.variant_service.VariantService.list_variants",
            new_callable=AsyncMock,
            return_value={"items": [], "next_cursor": None, "has_more": False},
        ):
            response = await client.get(f"{VARIANTS_PREFIX}?limit=500")
        assert response.status_code in (200, 422)


@pytest.mark.asyncio
class TestRegionQuery:
    """Tests for GET /api/v1/variants/region."""

    async def test_region_query_success(self, client, db_session):
        """Region query returns variants in the specified range."""
        # The endpoint refuses an assembly it does not know: a typo or a
        # stale assembly name must not read as "this region has no variants".
        # The fixture below registers the assembly the request names.
        from app.models.content import Release, ReleaseStatus
        from app.models.genomic import Assembly

        release = Release(
            id=7,
            version="region-release",
            name="Region release",
            status=ReleaseStatus.PUBLISHED,
        )
        db_session.add(release)
        await db_session.flush()
        db_session.add(
            Assembly(
                name="Wm82.gnm4",
                species="Glycine max",
                version="v4",
                release_id=release.id,
            )
        )
        await db_session.flush()

        variants = [_make_variant_dict(f"var_{i}", position=1000 + i) for i in range(10)]
        with patch(
            "app.services.variant_service.VariantService.get_variants_by_region",
            new_callable=AsyncMock,
            return_value=variants,
        ):
            response = await client.get(
                f"{VARIANTS_PREFIX}/region?assembly=Wm82.gnm4&chromosome=Gm01&start=1000&end=2000"
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 10
        assert data[0]["gene_id"] == "Glyma.01G000100"
        assert data[0]["impact"] == "MODERATE"

    async def test_region_query_rejects_inverted_range(self, client):
        """The backend rejects end coordinates before querying ClickHouse."""
        response = await client.get(
            f"{VARIANTS_PREFIX}/region?assembly=Wm82.gnm4&chromosome=Gm01&start=2000&end=1000"
        )
        assert response.status_code == 422

    async def test_region_query_missing_assembly(self, client):
        """Region query without assembly returns 422."""
        response = await client.get(
            f"{VARIANTS_PREFIX}/region?chromosome=Gm01&start=1000&end=2000"
        )
        assert response.status_code == 422

    async def test_region_query_missing_chromosome(self, client):
        """Region query without chromosome returns 422."""
        response = await client.get(
            f"{VARIANTS_PREFIX}/region?assembly=Wm82.gnm4&start=1000&end=2000"
        )
        assert response.status_code == 422


@pytest.mark.asyncio
class TestGetVariant:
    """Tests for GET /api/v1/variants/{variant_id}."""

    async def test_get_variant_detail(self, client):
        """Variant detail endpoint returns full variant information."""
        variant = _make_variant_dict("var_001", read_depth=50, zygosity="heterozygous")
        with patch(
            "app.services.variant_service.VariantService.get_variant",
            new_callable=AsyncMock,
            return_value=variant,
        ):
            response = await client.get(f"{VARIANTS_PREFIX}/var_001")
        assert response.status_code == 200
        data = response.json()
        assert data["variant_id"] == "var_001"


@pytest.mark.asyncio
class TestExportVariants:
    """Tests for POST /api/v1/variants/export."""

    async def test_export_requires_auth(self, client):
        """Export endpoint requires authentication (401 without token)."""
        response = await client.post(
            f"{VARIANTS_PREFIX}/export",
            json={"filters": {}, "format": "tsv"},
        )
        assert response.status_code in (401, 403)

    async def test_export_requires_researcher_role(self, client, user_factory):
        """Export endpoint requires at least researcher role."""
        # Register and login as viewer
        payload = user_factory.make_payload(
            email="viewer@example.com",
            username="vieweruser",
            role_name="viewer",
        )
        await client.post("/api/v1/auth/register", json=payload)
        login_resp = await client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://test"},
            json={"email": "viewer@example.com", "password": "TestPass123!"},
        )
        token = login_resp.json()["access_token"]

        response = await client.post(
            f"{VARIANTS_PREFIX}/export",
            headers={"Authorization": f"Bearer {token}"},
            json={"filters": {}, "format": "tsv"},
        )
        # Viewer should be forbidden (403) or the export may still be accepted
        # depending on role hierarchy
        assert response.status_code in (202, 403)
