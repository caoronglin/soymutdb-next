"""Regression tests for mutant-line API endpoints (public_id contract).

Contract mapping (database-core-contract):
- DB-CORE-2 / ID-01: public records are located by ``public_id`` only.
- DB-CORE-2 / ID-02: internal persistence keys are not accepted as
  locators and produce the same not-found envelope as unknown ids.
- DB-CORE-5: unpublished records (no public_id, is_public=False, deleted)
  never appear in public responses.
"""

from __future__ import annotations

import pytest

from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.genomic import Assembly, Chromosome
from app.models.variant import (
    MutantLine,
    Phenotype,
    VariantSummary,
    VariantType,
)

MUTANTS_PREFIX = "/api/v1/mutants"


@pytest.mark.asyncio
async def test_list_mutant_lines_reports_postgres_variant_summary_counts(
    client, db_session
):
    """The list projection aggregates FK-linked PostgreSQL summary rows."""
    assembly = Assembly(name="Wm82.gnm2", version="2")
    db_session.add(assembly)
    await db_session.flush()
    chromosome = Chromosome(
        assembly_id=assembly.id, name="Gm01", length=1_000_000, order=1
    )
    counted_line = MutantLine(name="counted", public_id="SMCNT0001")
    zero_line = MutantLine(name="zero", public_id="SMZR00001")
    deleted_line = MutantLine(
        name="deleted", public_id="SMDELETE01", is_deleted=True
    )
    db_session.add_all([chromosome, counted_line, zero_line, deleted_line])
    await db_session.flush()
    db_session.add_all(
        [
            VariantSummary(
                assembly_id=assembly.id,
                chromosome_id=chromosome.id,
                position=100,
                ref="A",
                alt="T",
                variant_type=VariantType.SNP,
                mutant_line_id=counted_line.id,
            ),
            VariantSummary(
                assembly_id=assembly.id,
                chromosome_id=chromosome.id,
                position=200,
                ref="G",
                alt="C",
                variant_type=VariantType.SNP,
                mutant_line_id=counted_line.id,
            ),
        ]
    )
    await db_session.commit()

    response = await client.get(MUTANTS_PREFIX)
    counted_detail = await client.get(f"{MUTANTS_PREFIX}/{counted_line.public_id}")
    zero_detail = await client.get(f"{MUTANTS_PREFIX}/{zero_line.public_id}")

    assert response.status_code == 200
    assert counted_detail.status_code == 200
    assert zero_detail.status_code == 200
    lines_by_name = {line["name"]: line for line in response.json()}
    assert lines_by_name["counted"]["variant_count"] == 2
    assert lines_by_name["zero"]["variant_count"] == 0
    assert counted_detail.json()["variant_count"] == 2
    assert zero_detail.json()["variant_count"] == 0
    assert "deleted" not in lines_by_name


@pytest.mark.asyncio
async def test_public_responses_carry_public_id_only(client, db_session):
    """Public responses expose public_id and never the persistence key."""
    line = MutantLine(name="dual-id", public_id="SMDATA001")
    db_session.add(line)
    await db_session.commit()

    list_response = await client.get(MUTANTS_PREFIX)
    detail_response = await client.get(f"{MUTANTS_PREFIX}/{line.public_id}")

    assert list_response.status_code == 200
    [item] = list_response.json()
    assert item["public_id"] == "SMDATA001"
    assert "id" not in item and "internal_id" not in item
    assert f'"{line.id}"' not in list_response.text

    assert detail_response.status_code == 200
    assert detail_response.json()["public_id"] == "SMDATA001"
    assert f'"{line.id}"' not in detail_response.text


@pytest.mark.asyncio
async def test_internal_persistence_key_is_not_a_public_locator(client, db_session):
    """ID-02: an existing internal id must not disclose its existence."""
    release = Release(
        version="mutant-locator-release",
        name="mutant locator release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(release)
    await db_session.flush()
    db_session.add(ActiveRelease(id=1, release_id=release.id))
    line = MutantLine(
        name="hidden-key",
        public_id="SMHIDDEN01",
        release_id=release.id,
    )
    db_session.add(line)
    await db_session.commit()

    response = await client.get(f"{MUTANTS_PREFIX}/{line.id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"

    search = await client.get(
        "/api/v1/search", params={"query": str(line.id)}
    )
    assert search.status_code == 200
    # The internal id is never echoed back as a result identity.
    assert all(
        item["id"] != str(line.id) for item in search.json()["results"]
    )


@pytest.mark.asyncio
async def test_missing_public_id_records_fail_closed(client, db_session):
    """Public routes exclude records without a public identifier."""
    unpublished = MutantLine(name="no-public-id", public_id=None)
    db_session.add(unpublished)
    await db_session.commit()

    list_response = await client.get(MUTANTS_PREFIX)
    assert list_response.status_code == 200
    assert list_response.json() == []

    detail_response = await client.get(f"{MUTANTS_PREFIX}/{unpublished.id}")
    assert detail_response.status_code == 404


@pytest.mark.asyncio
async def test_non_public_mutant_line_is_not_disclosed(client, db_session):
    """Public mutant routes treat embargoed lines as not found."""
    public_line = MutantLine(name="public-line", public_id="SMOPEN001")
    embargoed_line = MutantLine(
        name="embargoed-line", public_id="SMEMBRG01", is_public=False
    )
    db_session.add_all([public_line, embargoed_line])
    await db_session.flush()
    db_session.add(
        Phenotype(
            mutant_line_id=embargoed_line.id,
            trait_category="growth",
            trait_name="embargoed trait",
            trait_value="secret",
        )
    )
    await db_session.commit()

    list_response = await client.get(MUTANTS_PREFIX)
    detail_response = await client.get(f"{MUTANTS_PREFIX}/{embargoed_line.public_id}")
    phenotype_response = await client.get(
        f"{MUTANTS_PREFIX}/{embargoed_line.public_id}/phenotypes"
    )

    assert list_response.status_code == 200
    assert [line["name"] for line in list_response.json()] == ["public-line"]
    assert detail_response.status_code == 404
    assert detail_response.json()["error"] == {
        "code": "not_found",
        "message": f"Mutant line {embargoed_line.public_id} not found",
        "details": {},
    }
    assert phenotype_response.status_code == 404
    assert phenotype_response.json()["error"] == detail_response.json()["error"]


@pytest.mark.asyncio
async def test_public_id_lookup_is_case_insensitive_with_crockford_lookalikes(
    client, db_session
):
    """Normalized look-alike spellings resolve to the same record."""
    line = MutantLine(name="normalize-me", public_id="SM10AB25")
    db_session.add(line)
    await db_session.commit()

    response = await client.get(f"{MUTANTS_PREFIX}/{line.public_id.lower()}")
    assert response.status_code == 200
    # I→1 and O→0 are Crockford look-alike transcriptions.
    response = await client.get(f"{MUTANTS_PREFIX}/sm1oab25")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_mutant_lines_filters_mutagen_and_orders_case_insensitively_by_public_id(
    client, db_session
):
    """Browse results have deterministic case-insensitive public_id ordering."""
    beta = MutantLine(name="beta", public_id="SMBETA0001", mutagen="EMS")
    alpha_upper = MutantLine(name="ALPHA", public_id="SMALPHAA1", mutagen="EMS")
    alpha_lower = MutantLine(name="alpha", public_id="SMALPHAX1", mutagen="EMS")
    zeta = MutantLine(name="Zeta", public_id="SMZETA0001", mutagen="EMS")
    other_mutagen = MutantLine(
        name="Aardvark", public_id="SMARDVARK1", mutagen="Fast neutron"
    )
    hidden = MutantLine(
        name="Hidden", public_id="SMHIDDEN02", mutagen="EMS", is_public=False
    )
    deleted = MutantLine(
        name="Deleted", public_id="SMDELETED1", mutagen="EMS", is_deleted=True
    )
    db_session.add_all(
        [
            beta,
            alpha_upper,
            alpha_lower,
            zeta,
            other_mutagen,
            hidden,
            deleted,
        ]
    )
    await db_session.commit()

    response = await client.get(MUTANTS_PREFIX, params={"mutagen": "EMS"})

    assert response.status_code == 200
    assert [line["name"] for line in response.json()] == [
        "ALPHA",
        "alpha",
        "beta",
        "Zeta",
    ]
    assert alpha_upper.id < alpha_lower.id
    assert all(line["name"] not in {"Hidden", "Deleted"} for line in response.json())


@pytest.mark.asyncio
async def test_list_mutant_lines_applies_limit_after_stable_public_id_ordering(
    client, db_session
):
    """The list limit selects the first deterministic ordering window."""
    alpha_upper = MutantLine(name="ALPHA", public_id="SMLMTA001")
    alpha_lower = MutantLine(name="alpha", public_id="SMLMTX001")
    beta = MutantLine(name="beta", public_id="SMLMTB001")
    db_session.add_all([alpha_upper, alpha_lower, beta])
    await db_session.commit()

    response = await client.get(MUTANTS_PREFIX, params={"limit": 2})

    assert response.status_code == 200
    assert [line["name"] for line in response.json()] == ["ALPHA", "beta"]
    assert alpha_upper.id < alpha_lower.id


def test_list_mutant_lines_query_orders_by_lower_name_then_id(monkeypatch):
    """The query retains its aggregate join and has a deterministic sort key."""
    import asyncio

    from app.api.v1.mutants import list_mutant_lines

    captured = {}

    class Result:
        def all(self):
            return []

    class Session:
        async def execute(self, statement):
            captured["statement"] = statement
            return Result()

    asyncio.run(list_mutant_lines(db=Session(), mutagen="EMS", limit=2))

    statement = captured["statement"]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "LEFT OUTER JOIN variant_summaries" in compiled
    assert "count(variant_summaries.id)" in compiled
    assert "mutant_lines.mutagen = 'EMS'" in compiled
    assert "mutant_lines.is_deleted IS false" in compiled
    assert "mutant_lines.is_public IS true" in compiled
    assert "mutant_lines.public_id IS NOT NULL" in compiled
    assert "ORDER BY lower(mutant_lines.public_id), mutant_lines.id" in compiled
    assert "LIMIT 2" in compiled
