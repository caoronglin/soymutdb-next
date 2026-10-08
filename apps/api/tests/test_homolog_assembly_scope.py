"""PostgreSQL/HTTP regression for explicit homolog assembly filtering."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.content import Release, ReleaseStatus
from app.models.genomic import Assembly, Chromosome, Gene
from app.models.homolog import GeneHomolog, HomologType


@pytest_asyncio.fixture
async def homolog_references(db_session, monkeypatch):
    async def uncached(name, ttl, loader, **kwargs):
        return await loader()

    # Exercise real release resolution without sharing Redis across test runs.
    monkeypatch.setattr("app.core.cache_decorator.get_or_set", uncached)
    token = uuid.uuid4().hex[:16]
    published = Release(version=f"{token}-published", name="scope", status=ReleaseStatus.PUBLISHED)
    draft = Release(version=f"{token}-draft", name="draft", status=ReleaseStatus.DRAFT)
    db_session.add_all([published, draft])
    await db_session.flush()
    assemblies = {}
    for version, release in (("v4", published), ("v5", published), ("draft", draft)):
        assembly = Assembly(name=f"{token}-{version}", version=version, release_id=release.id)
        db_session.add(assembly)
        await db_session.flush()
        chromosome = Chromosome(assembly_id=assembly.id, name="chr01", length=10000)
        db_session.add(chromosome)
        await db_session.flush()
        gene = Gene(
            accession="Glyma.01G000100",
            assembly_id=assembly.id,
            chromosome_id=chromosome.id,
            biotype="protein_coding",
            start=100,
            end=200,
            strand="+",
        )
        db_session.add(gene)
        await db_session.flush()
        db_session.add_all(
            GeneHomolog(
                gene_id=gene.gene_pk,
                homolog_species="Arabidopsis thaliana",
                homolog_gene_id=f"{version}-target-{index}",
                homolog_type=HomologType.ORTHOLOG,
                source="scope-regression",
            )
            for index in (1, 2)
        )
        assemblies[version] = assembly.id
    await db_session.flush()
    return published.id, assemblies


@pytest.mark.parametrize("version", ["v4", "v5", "draft"])
async def test_explicit_assembly_excludes_other_assemblies_and_drafts(
    app, homolog_references, version
):
    release_id, assemblies = homolog_references
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/homologs/search",
            params={"release_id": release_id, "assembly_id": assemblies[version]},
        )
    assert response.status_code == 200
    data = response.json()
    expected = [] if version == "draft" else [f"{version}-target-1", f"{version}-target-2"]
    assert [row["homolog_gene_id"] for row in data["items"]] == expected
    assert data["total"] == len(expected)
    for row in data["items"]:
        assert "id" not in row and "gene_pk" not in row
    assert "draft-target" not in response.text


@pytest.mark.parametrize("version", ["v4", "v5"])
async def test_cursor_pages_stay_in_the_explicit_assembly(app, homolog_references, version):
    release_id, assemblies = homolog_references
    params = {"release_id": release_id, "assembly_id": assemblies[version], "page_size": 1}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/api/v1/homologs/search", params=params)
        assert first.status_code == 200
        assert first.json()["total"] == 2
        assert first.json()["items"][0]["homolog_gene_id"] == f"{version}-target-1"
        cursor = first.json()["next_cursor"]
        assert cursor
        second = await client.get("/api/v1/homologs/search", params={**params, "cursor": cursor})
        offset = await client.get("/api/v1/homologs/search", params={**params, "page": 2})
        other_assembly = assemblies["v5" if version == "v4" else "v4"]
        mismatched = await client.get(
            "/api/v1/homologs/search",
            params={**params, "assembly_id": other_assembly, "cursor": cursor},
        )
    assert mismatched.status_code == 422
    assert offset.status_code == 200
    assert [row["homolog_gene_id"] for row in offset.json()["items"]] == [f"{version}-target-2"]
    assert offset.json()["total"] == 2
    assert offset.json()["has_more"] is False
    assert second.status_code == 200
    assert second.json()["total"] is None
    assert [row["homolog_gene_id"] for row in second.json()["items"]] == [f"{version}-target-2"]
    assert second.json()["has_more"] is False
    assert second.json()["next_cursor"] is None
