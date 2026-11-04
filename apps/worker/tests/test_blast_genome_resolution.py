"""Protein/transcript BLAST subjects resolve only through explicit relations.

The red line: amino-acid subject_start/end from blastp must NEVER become a
genomic interval. Missing or ambiguous relations are recorded as unresolved
and never guessed from string similarity, suffix stripping or coordinates.
"""
from __future__ import annotations

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    select,
)
from sqlalchemy.orm import Session

from soymutdb_worker import blast_genome_resolution as resolution


@pytest.fixture
def gene_db():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    assemblies = Table("assemblies", metadata,
                       Column("id", Integer, primary_key=True),
                       Column("name", String(128)), Column("version", String(64)),
                       Column("release_id", Integer))
    # ``chromosomes.assembly_id`` is part of the real schema (0001 initial
    # migration) and the resolver joins on it; a fixture without it would
    # pass a resolver that silently ignores the chromosome's assembly.
    chromosomes = Table("chromosomes", metadata,
                        Column("id", Integer, primary_key=True),
                        Column("assembly_id", Integer, nullable=False),
                        Column("name", String(64)))
    genes = Table("genes", metadata,
                  Column("gene_pk", Integer, primary_key=True),
                  Column("accession", String(64)), Column("assembly_id", Integer),
                  Column("chromosome_id", Integer), Column("start", Integer),
                  Column("end", Integer), Column("strand", String(1)))
    transcripts = Table("transcripts", metadata,
                        Column("id", String(64), primary_key=True),
                        Column("gene_id", Integer), Column("is_canonical", Boolean))
    aliases = Table("gene_aliases", metadata,
                    Column("id", Integer, primary_key=True),
                    Column("gene_id", Integer), Column("alias", String(256)),
                    Column("source", String(128)))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(assemblies), [
            {"id": 42, "name": "Wm82.a4.v1", "version": "v4", "release_id": 7},
            {"id": 43, "name": "Wm82.a5.v1", "version": "v5", "release_id": 7},
            {"id": 44, "name": "Other", "version": "v9", "release_id": 8},
        ])
        connection.execute(insert(chromosomes), [
            {"id": 1, "assembly_id": 42, "name": "chr01"},
            {"id": 2, "assembly_id": 43, "name": "chr02"},
            # Same chromosome name in another assembly: a name is not a scope.
            {"id": 3, "assembly_id": 44, "name": "chr01"},
        ])
        connection.execute(insert(genes), [
            {"gene_pk": 100, "accession": "Glyma.01G000100", "assembly_id": 42,
             "chromosome_id": 1, "start": 12000, "end": 15000, "strand": "+"},
            # Same accession in v5 is a DIFFERENT namespace; never conflated.
            {"gene_pk": 200, "accession": "Glyma.01G000100", "assembly_id": 43,
             "chromosome_id": 2, "start": 99000, "end": 99500, "strand": "-"},
            {"gene_pk": 300, "accession": "Glyma.02G000200", "assembly_id": 42,
             "chromosome_id": 1, "start": 20000, "end": 21000, "strand": "-"},
        ])
        connection.execute(insert(transcripts), [
            {"id": "Glyma.01G000100.1", "gene_id": 100, "is_canonical": True},
            {"id": "prot.Glyma.02G000200", "gene_id": 300, "is_canonical": True},
        ])
        connection.execute(insert(aliases), [
            {"id": 1, "gene_id": 100, "alias": "PROT_A", "source": "UniProt"},
            # An unsourced alias is not an explicit relation.
            {"id": 2, "gene_id": 300, "alias": "GUESS_ME", "source": None},
            # Two genes share this alias -> ambiguous, never auto-picked.
            {"id": 3, "gene_id": 100, "alias": "SHARED", "source": "curated"},
            {"id": 4, "gene_id": 300, "alias": "SHARED", "source": "curated"},
        ])
    yield engine
    engine.dispose()


def _resolver(engine, assembly_id=42, release_id=7):
    session = Session(engine)
    return resolution.BlastGenomeResolver(session, assembly_id=assembly_id,
                                          release_id=release_id), session


def test_exact_gene_transcript_and_sourced_alias_resolve(gene_db):
    resolver, session = _resolver(gene_db)
    out = resolver.resolve(["Glyma.01G000100", "Glyma.01G000100.1", "PROT_A"])
    session.close()
    assert out["Glyma.01G000100"]["status"] == "resolved"
    assert out["Glyma.01G000100"]["chromosome"] == "chr01"
    assert out["Glyma.01G000100"]["start"] == 12000
    assert out["Glyma.01G000100"]["end"] == 15000
    assert out["Glyma.01G000100"]["assembly_id"] == 42
    assert out["Glyma.01G000100"]["release_id"] == 7
    assert out["Glyma.01G000100.1"] == out["Glyma.01G000100"]
    assert out["PROT_A"] == out["Glyma.01G000100"]


def test_aa_coordinates_are_never_copied_into_a_resolution(gene_db):
    resolver, session = _resolver(gene_db)
    hit = {"subject_id": "Glyma.01G000100", "subject_start": 3, "subject_end": 17,
           "query_start": 1, "query_end": 15}
    annotated = resolution.annotate_hits([hit], resolver.resolve(["Glyma.01G000100"]))
    session.close()
    record = annotated[0]["genome_resolution"]
    assert record["status"] == "resolved"
    assert record["start"] == 12000 and record["end"] == 15000
    assert 3 not in record.values() and 17 not in record.values()
    assert "subject_start" not in record and "amino_acid" not in str(record)


def test_unresolved_cases_are_explicit_not_guessed(gene_db):
    resolver, session = _resolver(gene_db)
    out = resolver.resolve([
        "GUESS_ME",                 # unsourced alias
        "SHARED",                   # ambiguous alias
        "Glyma.01G000100.2",        # suffix stripping is forbidden
        "Glyma.01G00010",           # near-miss is forbidden
        "unknown-protein",          # no relation
    ])
    session.close()
    for key, record in out.items():
        assert record["status"] == "unresolved", key
        assert record["reason"] in {"no_exact_relation", "ambiguous_relation",
                                    "no_relation", "empty_subject_id"}


def test_cross_assembly_isolation(gene_db):
    """The same accession in v4/v5 resolves to its own assembly's locus."""
    v4, s4 = _resolver(gene_db, assembly_id=42)
    v5, s5 = _resolver(gene_db, assembly_id=43)
    a = v4.resolve(["Glyma.01G000100"])["Glyma.01G000100"]
    b = v5.resolve(["Glyma.01G000100"])["Glyma.01G000100"]
    s4.close()
    s5.close()
    assert (a["chromosome"], a["start"]) == ("chr01", 12000)
    assert (b["chromosome"], b["start"]) == ("chr02", 99000)
    assert a["assembly_id"] != b["assembly_id"]


def test_a_relation_of_another_assembly_is_never_a_candidate(gene_db):
    """Assembly scope lives in the relation query, not in a later filter.

    A transcript id and an alias are plain strings; the same value can exist in
    v4 and v5. If the relation lookup collected both namespaces and relied on
    ``_gene_rows`` to drop the foreign one afterwards, the resolution would be
    correct only as long as that downstream filter stays in place. This patches
    ``_gene_rows`` to return every gene it is given — the shape a future caller
    could have — and asserts the cross-assembly relation still resolves to
    nothing.
    """
    engine = gene_db
    metadata = MetaData()
    transcripts = Table("transcripts", metadata, autoload_with=engine)
    aliases = Table("gene_aliases", metadata, autoload_with=engine)
    genes = Table("genes", metadata, autoload_with=engine)
    with engine.begin() as connection:
        # Both relations point at gene 200, which lives in assembly 43 only.
        connection.execute(insert(transcripts).values(
            id="prot.v5only", gene_id=200, is_canonical=True,
        ))
        connection.execute(insert(aliases).values(
            id=9, gene_id=200, alias="V5_ONLY_ALIAS", source="curated",
        ))
        rows = connection.execute(
            select(genes.c.gene_pk, genes.c.accession, genes.c.chromosome_id,
                   genes.c.start, genes.c.end, genes.c.strand).where(
                genes.c.gene_pk == 200)
        ).all()

    resolver, session = _resolver(engine, assembly_id=42)

    def unfiltered(gene_pks):
        # Deliberately does NOT scope by assembly: this is what a caller that
        # trusted the relation lookup would get.
        return {
            int(pk): resolution.GeneLocus(
                gene_id=str(accession), chromosome="chr02", start=int(start),
                end=int(end), strand=str(strand or "+"),
                assembly_id=43, release_id=7,
            )
            for pk, accession, _chromosome_id, start, end, strand in rows
            if int(pk) in gene_pks
        }

    resolver._gene_rows = unfiltered  # type: ignore[method-assign]
    out = resolver.resolve(["prot.v5only", "V5_ONLY_ALIAS"])
    session.close()
    for key, record in out.items():
        assert record == {"status": "unresolved", "reason": "no_exact_relation"}, key


def test_assembly_outside_release_is_refused(gene_db):
    resolver, session = _resolver(gene_db, assembly_id=42, release_id=8)
    out = resolver.resolve(["Glyma.01G000100"])
    session.close()
    assert out["Glyma.01G000100"]["reason"] == "assembly_outside_release"


def test_a_chromosome_of_another_assembly_never_resolves(gene_db):
    """A gene cannot borrow a locus from a chromosome of another assembly.

    ``genes.chromosome_id`` is a plain FK in the worker's narrow table, so a
    cross-assembly row is representable: the resolver must refuse it rather
    than report a locus whose chromosome belongs to a different assembly.
    """
    engine = gene_db
    metadata = MetaData()
    genes = Table("genes", metadata, autoload_with=engine)
    with engine.begin() as connection:
        # Gene 400 claims to be in assembly 42 but points at chromosome 2,
        # which belongs to assembly 43.
        connection.execute(insert(genes).values(
            gene_pk=400, accession="Glyma.09G999999", assembly_id=42,
            chromosome_id=2, start=5, end=90, strand="+",
        ))
    resolver, session = _resolver(engine, assembly_id=42)
    out = resolver.resolve(["Glyma.09G999999"])
    session.close()
    assert out["Glyma.09G999999"] == {"status": "unresolved", "reason": "no_exact_relation"}


def test_programs_requiring_resolution_are_explicit():
    assert {"blastp", "blastx", "tblastn"} <= resolution.PROTEIN_SUBJECT_PROGRAMS
    assert "blastn" not in resolution.PROTEIN_SUBJECT_PROGRAMS
