"""``GET /assemblies`` and ``GET /assemblies/{assembly_id}`` contract tests.

Most of this file is about the two ways a number on these endpoints can be
*fake* rather than missing:

* reading a release's denormalised counter (``Release.gene_count``) and showing
  it once per assembly, so two assemblies both claim the whole release's genes;
* inventing a download count by matching ``DownloadFile.category`` (free text)
  against an assembly name.

The fixture below makes the real counts and the release counters *disagree* —
a fixture where they happen to coincide would pass under either implementation.
"""

from __future__ import annotations

import uuid

import pytest_asyncio

from app.models.content import DownloadFile, Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.genomic import Assembly, Chromosome, Gene, Transcript
from app.services.assembly_service import DOWNLOAD_COUNT_UNAVAILABLE

ASSEMBLIES = "/api/v1/assemblies"

# Distinct per-assembly shapes, so a copied total cannot look right.
V4_GENES = 5
V4_TRANSCRIPTS = 8
V4_CHROMOSOMES = (("Gm01", 1_000), ("Gm02", 2_000))
V5_GENES = 2
V5_TRANSCRIPTS = 2
V5_CHROMOSOMES = (("chr01", 4_000),)


async def _seed_release(db_session, token: str) -> tuple[Release, Assembly, Assembly]:
    """One published release, two assemblies, deliberately unequal contents."""
    release = Release(
        version=f"{token}-rel",
        name="assemblies fixture",
        status=ReleaseStatus.PUBLISHED,
        # Wrong-on-purpose counters. Nothing may read them.
        gene_count=999,
        variant_count=888,
        mutant_line_count=777,
    )
    db_session.add(release)
    await db_session.flush()

    v4 = Assembly(name=f"{token}-v4", species="Glycine max", version="v4", release_id=release.id)
    v5 = Assembly(name=f"{token}-v5", species="Glycine max", version="v5", release_id=release.id)
    db_session.add_all([v4, v5])
    await db_session.flush()

    await _fill(db_session, v4, V4_CHROMOSOMES, V4_GENES, V4_TRANSCRIPTS, token, "v4")
    await _fill(db_session, v5, V5_CHROMOSOMES, V5_GENES, V5_TRANSCRIPTS, token, "v5")
    await db_session.flush()
    return release, v4, v5


async def _fill(db_session, assembly, chromosomes, gene_count, transcript_count, token, tag):
    chromosome_rows = []
    for index, (name, length) in enumerate(chromosomes):
        chromosome = Chromosome(
            assembly_id=assembly.id, name=name, length=length, order=index
        )
        db_session.add(chromosome)
        chromosome_rows.append(chromosome)
    await db_session.flush()

    gene_rows = []
    for index in range(gene_count):
        gene = Gene(
            accession=f"{token}-{tag}-G{index}",
            assembly_id=assembly.id,
            chromosome_id=chromosome_rows[index % len(chromosome_rows)].id,
            biotype="protein_coding",
            start=100 + index,
            end=200 + index,
            strand="+",
        )
        db_session.add(gene)
        gene_rows.append(gene)
    await db_session.flush()

    for index in range(transcript_count):
        gene = gene_rows[index % len(gene_rows)]
        db_session.add(
            Transcript(
                id=f"{token}-{tag}-T{index}",
                gene_id=gene.gene_pk,
                start=100,
                end=200,
                strand="+",
            )
        )
    await db_session.flush()


@pytest_asyncio.fixture
async def assembly_fixture(db_session, monkeypatch):
    async def uncached(name, ttl, loader, **kwargs):
        return await loader()

    # Exercise real release resolution without sharing Redis across runs.
    monkeypatch.setattr("app.core.cache_decorator.get_or_set", uncached)
    token = uuid.uuid4().hex[:12]
    release, v4, v5 = await _seed_release(db_session, token)
    db_session.add(ActiveRelease(id=1, release_id=release.id))

    # A download file that a category-matching implementation would happily
    # attribute to v4: its category *is* the assembly name.
    db_session.add(
        DownloadFile(
            name=f"{token}-bundle",
            file_url="https://example.invalid/bundle.tar.gz",
            category=v4.name,
            release_id=release.id,
            download_count=12_345,
        )
    )
    await db_session.flush()
    return release, v4, v5


async def test_list_reports_each_assembly_own_counts(assembly_fixture, client):
    """Two assemblies in one release must not share a gene count."""
    release, v4, v5 = assembly_fixture
    response = await client.get(ASSEMBLIES, params={"release_id": release.id})
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()}

    v4_row = rows[str(v4.id)]
    v5_row = rows[str(v5.id)]

    assert v4_row["statistics"]["gene_count"] == {"value": V4_GENES, "reason": None}
    assert v5_row["statistics"]["gene_count"] == {"value": V5_GENES, "reason": None}
    assert (
        v4_row["statistics"]["gene_count"]["value"]
        != v5_row["statistics"]["gene_count"]["value"]
    )

    assert v4_row["statistics"]["transcript_count"]["value"] == V4_TRANSCRIPTS
    assert v5_row["statistics"]["transcript_count"]["value"] == V5_TRANSCRIPTS

    assert v4_row["statistics"]["chromosome_count"]["value"] == len(V4_CHROMOSOMES)
    assert v5_row["statistics"]["chromosome_count"]["value"] == len(V5_CHROMOSOMES)

    assert v4_row["statistics"]["total_length"]["value"] == sum(
        length for _, length in V4_CHROMOSOMES
    )
    assert v5_row["statistics"]["total_length"]["value"] == sum(
        length for _, length in V5_CHROMOSOMES
    )

    assert v4_row["release_id"] == release.id
    assert v4_row["release_version"] == release.version


async def test_release_counters_are_never_read(assembly_fixture, client):
    """The denormalised ``Release.*_count`` values must not appear anywhere.

    They are 999/888/777 in the fixture and no assembly contains that many
    rows, so any appearance is a copied release total.
    """
    release, _v4, _v5 = assembly_fixture
    listing = await client.get(ASSEMBLIES, params={"release_id": release.id})
    assert listing.status_code == 200
    assert "999" not in listing.text
    assert "888" not in listing.text
    assert "777" not in listing.text

    for slug in {row["id"] for row in listing.json()}:
        detail = await client.get(f"{ASSEMBLIES}/{slug}", params={"release_id": release.id})
        assert detail.status_code == 200
        assert detail.json()["statistics"]["gene_count"]["value"] != release.gene_count


async def test_download_count_is_always_null_with_a_reason(assembly_fixture, client):
    """``download_files`` has no assembly dimension, so no number may be invented.

    The fixture deliberately contains a ``DownloadFile`` whose ``category``
    equals an assembly name. Category matching would produce 12_345 here.
    """
    release, v4, v5 = assembly_fixture
    listing = await client.get(ASSEMBLIES, params={"release_id": release.id})
    assert listing.status_code == 200
    for row in listing.json():
        assert row["statistics"]["download_count"] == {
            "value": None,
            "reason": DOWNLOAD_COUNT_UNAVAILABLE,
        }

    detail = await client.get(f"{ASSEMBLIES}/{v4.id}", params={"release_id": release.id})
    assert detail.status_code == 200
    statistics = detail.json()["statistics"]
    assert statistics["download_count"] == {
        "value": None,
        "reason": DOWNLOAD_COUNT_UNAVAILABLE,
    }
    assert "12345" not in detail.text


async def test_detail_lists_chromosomes_in_order(assembly_fixture, client):
    release, v4, _v5 = assembly_fixture
    response = await client.get(f"{ASSEMBLIES}/{v4.id}", params={"release_id": release.id})
    assert response.status_code == 200
    body = response.json()
    assert [row["name"] for row in body["chromosomes"]] == [
        name for name, _ in V4_CHROMOSOMES
    ]
    assert [row["length"] for row in body["chromosomes"]] == [
        length for _, length in V4_CHROMOSOMES
    ]


async def test_unknown_assembly_is_404_and_leaks_nothing(assembly_fixture, client):
    release, v4, v5 = assembly_fixture
    unknown_id = v4.id + v5.id + 4242
    missing = await client.get(f"{ASSEMBLIES}/{unknown_id}", params={"release_id": release.id})
    assert missing.status_code == 404
    # No name or version of a real assembly may appear in the body. The release
    # id is not asserted on: the envelope carries a uuid request id, whose hex
    # digits can contain any short decimal string by coincidence.
    for row in (v4, v5):
        assert row.name not in missing.text
        assert row.version not in missing.text
    assert release.version not in missing.text


async def test_assembly_outside_the_release_is_indistinguishable_from_missing(
    assembly_fixture, db_session, client
):
    """A published *other* release owns an assembly this release must not answer."""
    release, _v4, _v5 = assembly_fixture
    other = Release(
        version=f"{uuid.uuid4().hex[:8]}-other",
        name="other release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(other)
    await db_session.flush()
    other_assembly = Assembly(
        name=f"{uuid.uuid4().hex[:8]}-other", version="v4", release_id=other.id
    )
    db_session.add(other_assembly)
    await db_session.flush()

    response = await client.get(
        f"{ASSEMBLIES}/{other_assembly.id}", params={"release_id": release.id}
    )
    assert response.status_code == 404
    assert other_assembly.name not in response.text

    # Same answer as an id that never existed: existence is not disclosed.
    never = await client.get(
        f"{ASSEMBLIES}/{other_assembly.id + 100_000}", params={"release_id": release.id}
    )
    assert never.status_code == response.status_code


async def test_list_is_empty_for_a_release_without_assemblies(db_session, client):
    token = uuid.uuid4().hex[:8]
    empty = Release(
        version=f"{token}-empty", name="no assemblies", status=ReleaseStatus.PUBLISHED
    )
    db_session.add(empty)
    await db_session.flush()

    response = await client.get(ASSEMBLIES, params={"release_id": empty.id})
    assert response.status_code == 200
    assert response.json() == []


async def test_assembly_without_annotation_reports_zeros_but_downloads_do_not(
    assembly_fixture, db_session, client
):
    """An assembly with no rows is genuinely empty, and one dimension never counts.

    Two different "nothing here" cases, deliberately asserted side by side:

    * genes / transcripts / chromosomes: the aggregates ran over this assembly
      and found no rows, so the honest answer is ``0`` with no reason;
    * downloads: nothing could be aggregated at all, so it stays ``null`` with
      ``no_linked_downloads`` and is never turned into a zero.
    """
    release, v4, _v5 = assembly_fixture
    bare = Assembly(
        name=f"{uuid.uuid4().hex[:8]}-bare",
        species="Glycine max",
        version="v9",
        release_id=release.id,
    )
    db_session.add(bare)
    await db_session.flush()

    response = await client.get(f"{ASSEMBLIES}/{bare.id}", params={"release_id": release.id})
    assert response.status_code == 200
    statistics = response.json()["statistics"]

    for field in ("gene_count", "transcript_count", "chromosome_count", "total_length"):
        assert statistics[field] == {"value": 0, "reason": None}, field

    assert statistics["download_count"] == {
        "value": None,
        "reason": DOWNLOAD_COUNT_UNAVAILABLE,
    }

    # The real assembly is unaffected: one assembly's emptiness is not another's.
    healthy = await client.get(f"{ASSEMBLIES}/{v4.id}", params={"release_id": release.id})
    assert healthy.json()["statistics"]["gene_count"] == {"value": V4_GENES, "reason": None}


async def test_gene_without_transcripts_is_a_real_zero_not_a_reason(
    assembly_fixture, db_session, client
):
    """The counterpoint: a count that ran and found nothing is ``0``, not ``null``.

    An assembly that has annotation but no transcripts must not borrow the
    "could not count it" wording -- that would be as wrong as printing 0 for a
    dimension nobody ever counted.
    """
    release, _v4, _v5 = assembly_fixture
    token = uuid.uuid4().hex[:8]
    solo = Assembly(
        name=f"{token}-solo",
        species="Glycine max",
        version="v3",
        release_id=release.id,
    )
    db_session.add(solo)
    await db_session.flush()

    chromosome = Chromosome(
        assembly_id=solo.id, name=f"{token}-c1", length=500, order=0
    )
    db_session.add(chromosome)
    await db_session.flush()
    db_session.add(
        Gene(
            accession=f"{token}-G0",
            assembly_id=solo.id,
            chromosome_id=chromosome.id,
            biotype="protein_coding",
            start=10,
            end=20,
            strand="+",
        )
    )
    await db_session.flush()

    response = await client.get(f"{ASSEMBLIES}/{solo.id}", params={"release_id": release.id})
    assert response.status_code == 200
    statistics = response.json()["statistics"]

    assert statistics["gene_count"] == {"value": 1, "reason": None}
    assert statistics["chromosome_count"] == {"value": 1, "reason": None}
    assert statistics["total_length"] == {"value": 500, "reason": None}
    # The aggregate ran over an empty set: a genuine zero.
    assert statistics["transcript_count"] == {"value": 0, "reason": None}


async def test_chromosomes_of_an_unpublished_assembly_are_404_without_rows(
    assembly_fixture, db_session, client, app
):
    """``GET /genes/assemblies/{id}/chromosomes`` must not answer ``200 + []``.

    The route used to filter a join by ``Assembly.release_id`` and return
    whatever came back, so an assembly outside the resolved release answered
    ``200 + []`` -- "this assembly exists and has no chromosomes". This asserts
    the guard end to end: the same 404 an unknown id gets, no chromosome row in
    the body, and no fallback to the release's default assembly.

    ``release_context`` is overridden per test because the app-wide fixture pins
    release 7, which this fixture's rows do not live in.
    """
    from app.services.release_context import ReleaseContext, get_release_context

    release, v4, _v5 = assembly_fixture

    async def override() -> ReleaseContext:
        return ReleaseContext(release_id=release.id, assembly_id=v4.id, assembly=v4.name)

    app.dependency_overrides[get_release_context] = override
    try:
        other = Release(
            version=f"{uuid.uuid4().hex[:8]}-unpublished",
            name="unpublished release",
            status=ReleaseStatus.DRAFT,
        )
        db_session.add(other)
        await db_session.flush()
        hidden = Assembly(
            name=f"{uuid.uuid4().hex[:8]}-hidden",
            species="Glycine max",
            version="v1",
            release_id=other.id,
        )
        db_session.add(hidden)
        await db_session.flush()
        db_session.add(
            Chromosome(
                assembly_id=hidden.id,
                name=f"{uuid.uuid4().hex[:6]}-secret",
                length=12_345,
                order=0,
            )
        )
        await db_session.flush()

        unpublished = await client.get(f"/api/v1/genes/assemblies/{hidden.id}/chromosomes")
        assert unpublished.status_code == 404
        # No row data, no hidden name or length in the error body.
        assert "secret" not in unpublished.text
        assert "12345" not in unpublished.text

        # Indistinguishable from an id that never existed.
        never = await client.get(
            f"/api/v1/genes/assemblies/{hidden.id + 100_000}/chromosomes"
        )
        assert never.status_code == unpublished.status_code

        # And the published assembly still answers, so the guard is not a blanket 404.
        visible = await client.get(f"/api/v1/genes/assemblies/{v4.id}/chromosomes")
        assert visible.status_code == 200
        assert [row["name"] for row in visible.json()] == [
            name for name, _ in V4_CHROMOSOMES
        ]
    finally:
        app.dependency_overrides.pop(get_release_context, None)
