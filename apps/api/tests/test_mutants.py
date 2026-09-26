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
import pytest_asyncio

from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.genomic import Assembly, Chromosome
from app.models.variant import (
    MutantLine,
    Phenotype,
    VariantSummary,
    VariantType,
)
from app.services.release_context import ReleaseContext

MUTANTS_PREFIX = "/api/v1/mutants"


@pytest_asyncio.fixture
async def published_release(db_session):
    """Active published release that public mutant fixtures must join."""
    release = Release(
        version="mutants-public-release",
        name="mutants public release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(release)
    await db_session.flush()
    db_session.add(ActiveRelease(id=1, release_id=release.id))
    await db_session.flush()
    return release


@pytest.mark.asyncio
async def test_list_mutant_lines_reports_postgres_variant_summary_counts(
    client, db_session, published_release
):
    """The list projection aggregates FK-linked PostgreSQL summary rows."""
    assembly = Assembly(name="Wm82.gnm2", version="2")
    db_session.add(assembly)
    await db_session.flush()
    chromosome = Chromosome(
        assembly_id=assembly.id, name="Gm01", length=1_000_000, order=1
    )
    counted_line = MutantLine(
        name="counted", public_id="SMCNT0001", release_id=published_release.id
    )
    zero_line = MutantLine(
        name="zero", public_id="SMZR00001", release_id=published_release.id
    )
    deleted_line = MutantLine(
        name="deleted",
        public_id="SMDELETE01",
        is_deleted=True,
        release_id=published_release.id,
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
async def test_public_responses_carry_public_id_only(
    client, db_session, published_release
):
    """Public responses expose public_id and never the persistence key."""
    line = MutantLine(
        name="dual-id", public_id="SMDATA001", release_id=published_release.id
    )
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
async def test_missing_public_id_records_fail_closed(
    client, db_session, published_release
):
    """Public routes exclude records without a public identifier."""
    unpublished = MutantLine(
        name="no-public-id", public_id=None, release_id=published_release.id
    )
    db_session.add(unpublished)
    await db_session.commit()

    list_response = await client.get(MUTANTS_PREFIX)
    assert list_response.status_code == 200
    assert list_response.json() == []

    detail_response = await client.get(f"{MUTANTS_PREFIX}/{unpublished.id}")
    assert detail_response.status_code == 404


@pytest.mark.asyncio
async def test_non_public_mutant_line_is_not_disclosed(
    client, db_session, published_release
):
    """Public mutant routes treat embargoed lines as not found."""
    public_line = MutantLine(
        name="public-line", public_id="SMOPEN001", release_id=published_release.id
    )
    embargoed_line = MutantLine(
        name="embargoed-line",
        public_id="SMEMBRG01",
        is_public=False,
        release_id=published_release.id,
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
    client, db_session, published_release
):
    """Normalized look-alike spellings resolve to the same record."""
    line = MutantLine(
        name="normalize-me", public_id="SM10AB25", release_id=published_release.id
    )
    db_session.add(line)
    await db_session.commit()

    response = await client.get(f"{MUTANTS_PREFIX}/{line.public_id.lower()}")
    assert response.status_code == 200
    # I→1 and O→0 are Crockford look-alike transcriptions.
    response = await client.get(f"{MUTANTS_PREFIX}/sm1oab25")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_mutant_lines_filters_mutagen_and_orders_case_insensitively_by_public_id(
    client, db_session, published_release
):
    """Browse results have deterministic case-insensitive public_id ordering."""
    rid = published_release.id
    beta = MutantLine(name="beta", public_id="SMBETA0001", mutagen="EMS", release_id=rid)
    alpha_upper = MutantLine(name="ALPHA", public_id="SMALPHAA1", mutagen="EMS", release_id=rid)
    alpha_lower = MutantLine(name="alpha", public_id="SMALPHAX1", mutagen="EMS", release_id=rid)
    zeta = MutantLine(name="Zeta", public_id="SMZETA0001", mutagen="EMS", release_id=rid)
    other_mutagen = MutantLine(
        name="Aardvark", public_id="SMARDVARK1", mutagen="Fast neutron", release_id=rid
    )
    hidden = MutantLine(
        name="Hidden", public_id="SMHIDDEN02", mutagen="EMS", is_public=False, release_id=rid
    )
    deleted = MutantLine(
        name="Deleted", public_id="SMDELETED1", mutagen="EMS", is_deleted=True, release_id=rid
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
    client, db_session, published_release
):
    """The list limit selects the first deterministic ordering window."""
    rid = published_release.id
    alpha_upper = MutantLine(name="ALPHA", public_id="SMLMTA001", release_id=rid)
    alpha_lower = MutantLine(name="alpha", public_id="SMLMTX001", release_id=rid)
    beta = MutantLine(name="beta", public_id="SMLMTB001", release_id=rid)
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

    asyncio.run(
        list_mutant_lines(
            db=Session(),
            release_context=ReleaseContext(release_id=7),
            mutagen="EMS",
            limit=2,
        )
    )

    statement = captured["statement"]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "LEFT OUTER JOIN variant_summaries" in compiled
    assert "count(variant_summaries.id)" in compiled
    assert "mutant_lines.release_id = 7" in compiled
    assert "mutant_lines.mutagen = 'EMS'" in compiled
    assert "mutant_lines.is_deleted IS false" in compiled
    assert "mutant_lines.is_public IS true" in compiled
    assert "mutant_lines.public_id IS NOT NULL" in compiled
    assert "ORDER BY lower(mutant_lines.public_id), mutant_lines.id" in compiled
    assert "LIMIT 2" in compiled


@pytest.mark.asyncio
async def test_public_routes_exclude_draft_and_unreleased_records(
    client, db_session, published_release
):
    """P0-01: only the active published release is visible publicly."""
    draft_release = Release(
        version="mutants-draft-release",
        name="mutants draft release",
        status=ReleaseStatus.DRAFT,
    )
    published_but_inactive = Release(
        version="mutants-old-release",
        name="mutants old release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add_all([draft_release, published_but_inactive])
    await db_session.flush()

    visible = MutantLine(
        name="visible", public_id="SMVISIBLE1", release_id=published_release.id
    )
    draft_line = MutantLine(
        name="draft", public_id="SMDRAFT001", release_id=draft_release.id
    )
    inactive_line = MutantLine(
        name="inactive", public_id="SMINACTIV1", release_id=published_but_inactive.id
    )
    null_release_line = MutantLine(name="null-release", public_id="SMNULLREL1")
    db_session.add_all([visible, draft_line, inactive_line, null_release_line])
    await db_session.flush()
    db_session.add(
        Phenotype(
            mutant_line_id=draft_line.id,
            trait_category="growth",
            trait_name="draft trait",
            trait_value="hidden",
        )
    )
    await db_session.commit()

    list_response = await client.get(MUTANTS_PREFIX)
    assert list_response.status_code == 200
    assert [line["name"] for line in list_response.json()] == ["visible"]

    for hidden in (draft_line, inactive_line, null_release_line):
        detail = await client.get(f"{MUTANTS_PREFIX}/{hidden.public_id}")
        assert detail.status_code == 404, hidden.name
        assert detail.json()["error"]["code"] == "not_found"
    phenotype = await client.get(f"{MUTANTS_PREFIX}/{draft_line.public_id}/phenotypes")
    assert phenotype.status_code == 404


@pytest.mark.asyncio
async def test_public_mutant_routes_fail_closed_without_active_release(
    client, db_session
):
    """P0-01: with no active published release the public surface is unavailable."""
    db_session.add(MutantLine(name="orphan", public_id="SMORPHAN01"))
    await db_session.commit()

    list_response = await client.get(MUTANTS_PREFIX)
    detail_response = await client.get(f"{MUTANTS_PREFIX}/SMORPHAN01")
    phenotype_response = await client.get(
        f"{MUTANTS_PREFIX}/SMORPHAN01/phenotypes"
    )

    assert list_response.status_code == 503
    assert detail_response.status_code == 503
    assert phenotype_response.status_code == 503
