"""Real PostgreSQL: subject IDs resolve only through explicit gene relations.

Amino-acid alignment coordinates are never read. blastp/blastx/tblastn hits
get a locus only when their subject ID maps to a gene/alias/transcript in the
job's own assembly and release; anything else is explicitly unresolved.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models.blast import BlastDatabase, BlastJob, BlastJobStatus
from app.models.content import Release
from app.models.genomic import Assembly, Chromosome, Gene, GeneAlias, Transcript
from app.services.blast_service import BlastService


async def seed(db_session):
    release = Release(version="genome-target", name="gt", status="published")
    db_session.add(release)
    await db_session.flush()
    assembly = Assembly(name="Wm82.a4.v1", version="v4", release_id=release.id,
                        is_default=True)
    other = Assembly(name="Wm82.a2.v1", version="v2", release_id=release.id)
    db_session.add_all([assembly, other])
    await db_session.flush()
    chromosome = Chromosome(name="chr01", assembly_id=assembly.id, length=1_000_000)
    db_session.add(chromosome)
    await db_session.flush()
    gene = Gene(
        gene_pk=1, accession="Glyma.01G000100", assembly_id=assembly.id,
        chromosome_id=chromosome.id, name="Test gene", start=12000, end=15000,
        strand="+", biotype="protein_coding",
    )
    other_gene = Gene(
        gene_pk=2, accession="Glyma.01G000100", assembly_id=other.id,
        chromosome_id=chromosome.id, start=1, end=2, strand="+",
    )
    db_session.add_all([gene, other_gene])
    await db_session.flush()
    db_session.add(GeneAlias(gene_id=1, alias="protein.Glyma.01G000100.1", source="test"))
    db_session.add(Transcript(id="transcript.Glyma.01G000100.1", gene_id=1,
                              start=12000, end=15000, strand="+"))
    database = BlastDatabase(
        name="protein-db", db_type="prot", assembly_id=assembly.id,
        file_path="/private/index", engine="ncbi_blast", build_status="published",
        is_active=True, created_at=datetime.now(UTC),
    )
    db_session.add(database)
    await db_session.flush()
    await db_session.commit()
    return release, assembly, database


async def job(db_session, database, program, status=BlastJobStatus.COMPLETED, user=None):
    row = BlastJob(
        id=uuid.uuid4(), user_id=user, program=program, database_id=database.id,
        query_sequence="MKVLAAGIVGLNLGGK", status=status,
        parameters={"_search_provenance": {"engine": "ncbi_blast"}},
        submitted_at=datetime.now(UTC),
    )
    db_session.add(row)
    await db_session.flush()
    await db_session.commit()
    return row


@pytest.mark.parametrize("program", ["blastp", "blastx", "tblastn", "tblastx", "blastn"])
@pytest.mark.parametrize("subject", [
    "Glyma.01G000100", "protein.Glyma.01G000100.1", "transcript.Glyma.01G000100.1",
])
async def test_explicit_subject_resolution_never_uses_alignment_coordinates(
    db_session, program, subject,
):
    release, assembly, database = await seed(db_session)
    row = await job(db_session, database, program)
    service = BlastService()
    target = await service.resolve_genome_target(
        db_session, row.id, subject, user_id=None, user_roles=["administrator"]
    )
    assert target.status == "resolved"
    assert target.locus == "chr01:12000-15000"
    assert target.release_id == release.id
    assert target.assembly_id == assembly.id
    assert target.resolution in {"gene_accession", "gene_alias", "transcript_id"}


@pytest.mark.parametrize("program", ["blastp", "blastn"])
async def test_unknown_subject_is_explicitly_unresolved(db_session, program):
    _, _, database = await seed(db_session)
    row = await job(db_session, database, program)
    target = await BlastService().resolve_genome_target(
        db_session, row.id, "unmapped.protein.1",
        user_id=None, user_roles=["administrator"],
    )
    assert target.status == "unresolved"
    assert target.reason == "subject_not_found"
    assert target.locus is None and target.start is None


@pytest.mark.parametrize("status", [BlastJobStatus.PENDING, BlastJobStatus.RUNNING,
                                     BlastJobStatus.FAILED])
async def test_unfinished_job_never_offers_a_locus(db_session, status):
    _, _, database = await seed(db_session)
    row = await job(db_session, database, "blastp", status=status)
    target = await BlastService().resolve_genome_target(
        db_session, row.id, "Glyma.01G000100",
        user_id=None, user_roles=["administrator"],
    )
    assert target.status == "unresolved" and target.reason == "job_not_completed"


async def test_ambiguous_alias_is_reported_not_guessed(db_session):
    from app.models.genomic import Chromosome, Gene
    from app.models.genomic import GeneAlias as Alias

    release, assembly, database = await seed(db_session)
    chromosome = (await db_session.execute(
        select(Chromosome).where(Chromosome.assembly_id == assembly.id)
    )).scalar_one()
    second = Gene(
        gene_pk=3, accession="Glyma.01G999999", assembly_id=assembly.id,
        chromosome_id=chromosome.id, start=1, end=2, strand="+",
    )
    db_session.add(second)
    await db_session.flush()
    db_session.add(Alias(gene_id=3, alias="ambiguous.alias", source="test"))
    db_session.add(Alias(gene_id=1, alias="ambiguous.alias", source="test"))
    await db_session.commit()
    row = await job(db_session, database, "blastp")
    target = await BlastService().resolve_genome_target(
        db_session, row.id, "ambiguous.alias",
        user_id=None, user_roles=["administrator"],
    )
    assert target.status == "unresolved" and target.reason == "ambiguous_subject"
