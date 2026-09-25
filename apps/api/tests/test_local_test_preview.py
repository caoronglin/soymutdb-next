"""Tests for the loopback-only local test-data preview boundary."""

from __future__ import annotations

import csv
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.v1 import preview_test_data
from app.models.content import Release, ReleaseStatus
from app.models.genomic import Assembly, Chromosome, Gene
from app.models.local_test_preview import LocalTestMutationSite
from app.services.local_test_preview_import_service import (
    parse_gene_features,
    parse_mutation_sites,
    read_fai,
    validate_local_test_database,
)
from app.services.local_test_preview_service import (
    PREVIEW_ANNOTATION_VERSION,
    PREVIEW_ASSEMBLY_NAME,
    PREVIEW_DATASET_KEY,
    PREVIEW_RELEASE_VERSION,
)


def _request(peer_host: str, *, forwarded_for: str | None = None) -> Request:
    headers = [(b"host", b"localhost")]
    if forwarded_for:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/preview/test-data/meta",
            "raw_path": b"/api/v1/preview/test-data/meta",
            "query_string": b"",
            "headers": headers,
            "server": ("localhost", 80),
            "client": (peer_host, 12345),
        }
    )


def test_preview_gate_requires_opted_in_baseline_development(monkeypatch):
    settings = SimpleNamespace(
        local_test_preview_enabled=True,
        app_env="dev",
        deployment_mode="baseline",
    )
    monkeypatch.setattr(preview_test_data, "get_settings", lambda: settings)

    preview_test_data.require_local_test_preview(_request("127.0.0.1"))

    settings.local_test_preview_enabled = False
    with pytest.raises(HTTPException) as disabled:
        preview_test_data.require_local_test_preview(_request("127.0.0.1"))
    assert disabled.value.status_code == 404

    settings.local_test_preview_enabled = True
    settings.deployment_mode = "extended"
    with pytest.raises(HTTPException) as extended:
        preview_test_data.require_local_test_preview(_request("127.0.0.1"))
    assert extended.value.status_code == 404


def test_preview_gate_uses_tcp_peer_and_ignores_spoofed_host_and_forwarded_ip(monkeypatch):
    monkeypatch.setattr(
        preview_test_data,
        "get_settings",
        lambda: SimpleNamespace(
            local_test_preview_enabled=True,
            app_env="dev",
            deployment_mode="baseline",
        ),
    )
    with pytest.raises(HTTPException) as blocked:
        preview_test_data.require_local_test_preview(
            _request("203.0.113.8", forwarded_for="127.0.0.1")
        )
    assert blocked.value.status_code == 404


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://user:secret@127.0.0.1:5432/soymutdb",
        "postgresql+asyncpg://user:secret@127.0.0.1:55432/production",
        "postgresql+asyncpg://user:secret@example.org:55432/soymutdb",
        "sqlite+aiosqlite:///tmp/not-allowed.db",
    ],
)
def test_importer_rejects_non_disposable_or_non_postgres_targets(url):
    with pytest.raises(ValueError):
        validate_local_test_database(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://user:secret@127.0.0.1:55432/soymutdb",
        "postgresql+asyncpg://user:secret@[::1]:55432/soymutdb",
        "postgresql+asyncpg://user:secret@localhost:55432/soymutdb",
    ],
)
def test_importer_accepts_only_the_dedicated_loopback_target(url):
    validate_local_test_database(url)


def test_sample_data_parsers_preserve_a6_namespace_and_coordinate_semantics(tmp_path):
    fai_path = tmp_path / "sample.fa.fai"
    fai_path.write_text(
        "".join(f"Gm{index:02d}\t100000\t0\t60\t61\n" for index in range(1, 21)),
        encoding="utf-8",
    )
    chromosome_lengths = read_fai(fai_path)

    accession = f"Glyma.01G000100.{PREVIEW_ANNOTATION_VERSION}"
    encoded_name = quote("Glyma.01G000100", safe=".")
    gff_path = tmp_path / "sample.gff3"
    gff_path.write_text(
        "##gff-version 3\n"
        "##assembly-version v6.0\n"
        f"##annot-version {PREVIEW_ANNOTATION_VERSION}\n"
        f"Gm01\tphytozomev13\tgene\t20\t100\t.\t+\t.\tID={accession};Name={encoded_name}\n",
        encoding="utf-8",
    )
    genes = parse_gene_features(
        gff_path,
        chromosome_lengths,
        annotation_sha256="a" * 64,
    )
    assert len(genes) == 1
    assert genes[0].accession == accession
    assert genes[0].name == "Glyma.01G000100"
    assert genes[0].attributes["local_preview_dataset_key"] == PREVIEW_DATASET_KEY

    sites_path = tmp_path / "sample.tsv"
    columns = [
        "株系",
        "突变体系（株系母+位置）",
        "染色体号",
        "位点",
        "可信度（高/中/低）",
        "基因号",
        "特征",
        "可获得",
    ]
    with sites_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        writer.writerow(
            {
                "株系": "SOYTE1M00001",
                "突变体系（株系母+位置）": "SOYTE1M-Gm01-50",
                "染色体号": "Gm01",
                "位点": "50",
                "可信度（高/中/低）": "H",
                "基因号": accession,
                "特征": "gene|-30",
                "可获得": "Y",
            }
        )
    sites = parse_mutation_sites(
        sites_path,
        chromosome_lengths,
        {accession},
        expected_rows=1,
    )
    assert len(sites) == 1
    assert sites[0].position == 50
    assert sites[0].confidence == "H"
    assert sites[0].available is True
    assert not hasattr(sites[0], "ref")
    assert not hasattr(sites[0], "alt")


@pytest.mark.asyncio
async def test_preview_api_returns_unpublished_v6_data_without_variant_fields(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(
        preview_test_data,
        "get_settings",
        lambda: SimpleNamespace(
            local_test_preview_enabled=True,
            app_env="dev",
            deployment_mode="baseline",
        ),
    )
    release = Release(
        version=PREVIEW_RELEASE_VERSION,
        name="Local v6 test data",
        status=ReleaseStatus.DRAFT.value,
        assembly=PREVIEW_ASSEMBLY_NAME,
        notes="LOCAL_TEST_PREVIEW_DATASET=03_soymut-a6-test",
    )
    db_session.add(release)
    await db_session.flush()
    assembly = Assembly(
        name=PREVIEW_ASSEMBLY_NAME,
        version="v6.0",
        species="Glycine max",
        is_default=False,
        release_id=release.id,
    )
    db_session.add(assembly)
    await db_session.flush()
    release.assembly_id = assembly.id
    chromosome = Chromosome(
        assembly_id=assembly.id,
        name="Gm01",
        length=59600650,
        order=1,
    )
    db_session.add(chromosome)
    await db_session.flush()

    gene = Gene(
        accession=f"Glyma.01G000100.{PREVIEW_ANNOTATION_VERSION}",
        assembly_id=assembly.id,
        chromosome_id=chromosome.id,
        name="Glyma.01G000100",
        biotype="gene",
        start=78503,
        end=103594,
        strand="-",
        attributes={"local_preview_dataset_key": PREVIEW_DATASET_KEY},
    )
    db_session.add(gene)
    await db_session.flush()
    db_session.add(
        LocalTestMutationSite(
            dataset_key=PREVIEW_DATASET_KEY,
            source_site_key="SOYTE1M-Gm01-98256",
            mutant_line_name="SOYTE1M00001",
            assembly_id=assembly.id,
            release_id=release.id,
            chromosome_id=chromosome.id,
            gene_pk=gene.gene_pk,
            position=98256,
            confidence="H",
            feature="gene|-5225.5",
            available=True,
            source_file="mu-infor_Gmax_880_Wm82-test.txt",
            source_sha256="b" * 64,
            annotation_file="Gmax_880_Wm82.a6.v1.gene.gff3",
            annotation_sha256="a" * 64,
            annotation_version=PREVIEW_ANNOTATION_VERSION,
        )
    )
    await db_session.flush()

    meta_response = await client.get("/api/v1/preview/test-data/meta")
    assert meta_response.status_code == 200
    meta = meta_response.json()
    assert meta["preview"] is True
    assert meta["publication_status"] == "unpublished"
    assert meta["assembly"]["name"] == "Gmax_880_v6.0"
    assert meta["annotation_version"] == "Wm82.a6.v1"
    assert meta["dataset"]["row_count"] == 1
    assert meta_response.headers["cache-control"] == "private, no-store"

    gene_response = await client.get(
        "/api/v1/preview/test-data/genes",
        params={"gene_id": "Glyma.01G000100"},
    )
    assert gene_response.status_code == 200
    gene_item = gene_response.json()["items"][0]
    assert gene_item["gene_id"] == f"Glyma.01G000100.{PREVIEW_ANNOTATION_VERSION}"
    assert gene_item["mutation_site_count"] == 1

    site_response = await client.get(
        "/api/v1/preview/test-data/mutation-sites",
        params={"chromosome": "Gm01", "start": 98000, "end": 99000},
    )
    assert site_response.status_code == 200
    site_body = site_response.json()
    assert site_body["coordinate_system"] == "1-based-inclusive"
    assert site_body["items"][0]["source_site_key"] == "SOYTE1M-Gm01-98256"
    assert site_body["items"][0]["position"] == 98256
    assert site_body["items"][0]["gene_id"] == gene_item["gene_id"]
    assert "ref_allele" not in site_body["items"][0]
    assert "alt_allele" not in site_body["items"][0]

