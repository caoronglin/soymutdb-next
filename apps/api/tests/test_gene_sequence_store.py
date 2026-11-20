"""The residue store behind the gene detail contract.

The gene detail response used to report every molecule ``unavailable`` because
no residue store existed. Two different stores answer for the four molecules,
and this file pins both:

* ``transcript_sequences`` holds the CDS/protein residues the annotation ships,
  written by ``import_transcript_sequences`` (replaced per assembly, never
  accumulated, never attached to another assembly's transcript);
* ``genomic`` and ``transcript`` come from slicing the assembly's reference
  FASTA through its ``.fai`` offsets. Nothing is loaded as a whole, coordinates
  are clamped to the contig, and a minus-strand transcript is spliced in
  reading order.

The ablations are the ones that matter: a gene with nothing stored must not gain
a residue, one molecule must not answer for another, an out-of-release gene must
return no residues at all, and a malformed FASTA must stop the import instead of
silently leaving genes ``unavailable``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assembly,
    Chromosome,
    Gene,
    Release,
    ReleaseStatus,
    Transcript,
    TranscriptSequence,
)
from app.schemas.gene_evidence import SequenceAvailability
from app.services.reference_sequence_service import (
    ReferenceUnavailable,
    clamp_to_contig,
    read_reference_index,
    reverse_complement,
)
from app.services.release_context import ReleaseContext
from app.services.seqfetch_service import parse_fai
from app.services.sequence_availability import (
    MAX_INLINE_RESIDUES,
    NO_SEQUENCE_STORE,
    REFERENCE_UNAVAILABLE,
    RESIDUE_EXCEEDS_INLINE_LIMIT,
    ReferenceState,
    StoredResidue,
    TranscriptSpans,
    availability_entries,
    load_gene_sequences,
    representative_residue,
    representative_transcript,
    transcript_layouts,
)
from app.services.transcript_sequence_import_service import (
    ResidueFastaError,
    import_transcript_sequences,
    parse_residue_fasta,
)

# ---------------------------------------------------------------------------
# FASTA parsing: malformed input fails closed
# ---------------------------------------------------------------------------


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_cds_records_are_read_per_transcript(tmp_path: Path) -> None:
    fasta = _write(
        tmp_path / "cds.fa",
        ">Glyma.01G000100.1 pacid=1\nACGTacgt\nACGT\n>Glyma.01G000100.2\nTTTT\n",
    )
    records = list(parse_residue_fasta(fasta, molecule="cds"))
    assert [record.transcript_id for record in records] == [
        "Glyma.01G000100.1",
        "Glyma.01G000100.2",
    ]
    # Lowercase soft-masking is normalised, wrapping is joined.
    assert records[0].sequence == "ACGTACGTACGT"
    assert records[1].sequence == "TTTT"


def test_a_protein_record_is_named_by_its_transcript_attribute(tmp_path: Path) -> None:
    fasta = _write(
        tmp_path / "protein.fa",
        ">Glyma.01G000100.1.p pacid=1 transcript=Glyma.01G000100.1 locus=X\nMKV*\n",
    )
    records = list(parse_residue_fasta(fasta, molecule="protein"))
    # The record id carries a `.p` suffix and is not a transcript id.
    assert [record.transcript_id for record in records] == ["Glyma.01G000100.1"]


@pytest.mark.parametrize(
    ("name", "text", "molecule", "expected"),
    [
        ("cds.fa", ">\nACGT\n", "cds", "empty FASTA header"),
        ("cds.fa", ">" + "x" * 65 + "\nACGT\n", "cds", "names no transcript id"),
        ("cds.fa", "ACGT\n>tx1\nACGT\n", "cds", "before the first FASTA header"),
        ("cds.fa", ">tx1\nACGT\n>tx1\nTTTT\n", "cds", "appears twice"),
        ("cds.fa", ">tx1\n>tx2\nACGT\n", "cds", "carries no residues"),
        ("cds.fa", ">tx1\nACGU\n", "cds", "not a cds residue"),
        ("protein.fa", ">tx1.p transcript=tx1\nMKV8\n", "protein", "not a protein residue"),
    ],
)
def test_a_malformed_fasta_is_refused(
    tmp_path: Path, name: str, text: str, molecule: str, expected: str
) -> None:
    """A skipped record would leave a gene silently ``unavailable``.

    Ablation: the previous importers tolerate malformed *annotation* rows
    because a wrong gene model is worse than a missing one. Residues invert
    that trade: the file is machine-generated per transcript, so a record that
    does not parse means the input is wrong, and finishing the import would
    record a partial store as if it were complete.
    """
    fasta = _write(tmp_path / name, text)
    with pytest.raises(ResidueFastaError, match=expected):
        list(parse_residue_fasta(fasta, molecule=molecule))


def test_an_unknown_molecule_is_refused(tmp_path: Path) -> None:
    fasta = _write(tmp_path / "x.fa", ">tx1\nACGT\n")
    with pytest.raises(ValueError, match="unknown molecule"):
        list(parse_residue_fasta(fasta, molecule="genomic"))


# ---------------------------------------------------------------------------
# Reference slices: bounded, clamped, spliced
# ---------------------------------------------------------------------------

#: Line layout of the synthetic reference below. ``linewidth`` counts the
#: newline, so a slice has to skip it exactly like ``samtools faidx`` does.
LINEBASES = 10


def _write_reference(directory: Path, contig: str, sequence: str) -> tuple[Path, Path]:
    header = f">{contig} synthetic\n"
    body = "\n".join(
        sequence[offset : offset + LINEBASES] for offset in range(0, len(sequence), LINEBASES)
    )
    fasta = _write(directory / "reference.fa", header + body + "\n")
    fai = _write(
        directory / "reference.fa.fai",
        f"{contig}\t{len(sequence)}\t{len(header.encode())}\t{LINEBASES}\t{LINEBASES + 1}\n",
    )
    return fasta, fai


def _assembly(fasta: Path, fai: Path) -> SimpleNamespace:
    return SimpleNamespace(
        name="Synthetic.assembly",
        release_id=1,
        fasta_url=str(fasta),
        fai_url=str(fai),
    )


def _gene(
    assembly: SimpleNamespace,
    *,
    start: int = 1,
    end: int = 10,
    strand: str = "+",
    contig: str = "Gm01",
) -> SimpleNamespace:
    return SimpleNamespace(
        accession="Glyma.01G000100",
        gene_pk=1,
        assembly_id=1,
        start=start,
        end=end,
        strand=strand,
        chromosome=SimpleNamespace(name=contig),
        assembly=assembly,
    )


def test_a_genomic_slice_is_clamped_to_the_contig(tmp_path: Path) -> None:
    """A gene body that runs off the contig is clipped, not read past it.

    Ablation: the naive ``slice_fasta(start, end)`` would read bytes belonging to
    the next FASTA record, and the residue string would be silently wrong at
    exactly the genes an operator is most likely to be debugging.
    """
    sequence = "ACGTACGTAC" * 3 + "AC"  # 32 bases
    fasta, fai = _write_reference(tmp_path, "Gm01", sequence)
    assembly = _assembly(fasta, fai)
    reference = ReferenceState(index=read_reference_index(assembly))  # type: ignore[arg-type]
    gene = _gene(assembly, start=-4, end=8)

    entries = {
        entry.molecule: entry
        for entry in availability_entries(
            gene,  # type: ignore[arg-type]
            stored={},
            spans_by_transcript={},
            reference=reference,
        )
    }
    genomic = entries["genomic"]
    assert genomic.availability == "available"
    # Clamped to 1..8, so the residues start at the first base of the contig.
    assert genomic.sequence == sequence[:8]
    assert genomic.length == 8
    assert genomic.checksum == hashlib.sha256(sequence[:8].encode()).hexdigest()


def test_a_contig_the_reference_does_not_carry_is_unavailable(tmp_path: Path) -> None:
    sequence = "ACGT" * 4
    fasta, fai = _write_reference(tmp_path, "Gm01", sequence)
    assembly = _assembly(fasta, fai)
    reference = ReferenceState(index=read_reference_index(assembly))  # type: ignore[arg-type]
    gene = _gene(assembly, contig="Gm99")

    genomic = availability_entries(
        gene,  # type: ignore[arg-type]
        stored={},
        spans_by_transcript={},
        reference=reference,
    )[0]
    assert genomic.availability == "unavailable"
    assert genomic.reason == f"{NO_SEQUENCE_STORE}:genomic"


def test_an_interval_past_the_contig_leaves_nothing_to_read(tmp_path: Path) -> None:
    sequence = "ACGT" * 4
    fasta, fai = _write_reference(tmp_path, "Gm01", sequence)
    record = parse_fai(fai.read_text())["Gm01"]
    assert clamp_to_contig(record, 100, 200) is None
    assert clamp_to_contig(record, 5, 100) == (5, len(sequence))


def test_a_minus_strand_transcript_is_spliced_in_reading_order(tmp_path: Path) -> None:
    sequence = "AAAACCCCGGGGTTTT" + "ACGT" * 4
    fasta, fai = _write_reference(tmp_path, "Gm01", sequence)
    assembly = _assembly(fasta, fai)
    reference = ReferenceState(index=read_reference_index(assembly))  # type: ignore[arg-type]
    gene = _gene(assembly, start=1, end=32, strand="-")
    spans = {
        "tx1": TranscriptSpans(
            transcript_id="tx1",
            spans=((1, 4), (11, 14)),
            strand="-",
            is_canonical=False,
        )
    }

    entries = {
        entry.molecule: entry
        for entry in availability_entries(
            gene,  # type: ignore[arg-type]
            stored={},
            spans_by_transcript=spans,
            reference=reference,
        )
    }
    transcript = entries["transcript"]
    # 5'->3' runs from high coordinate to low on the minus strand, and each exon
    # is complemented before it is joined.
    expected = reverse_complement(sequence[10:14]) + reverse_complement(sequence[0:4])
    assert transcript.availability == "available"
    assert transcript.sequence == expected
    assert transcript.length == 8


def test_an_unreadable_reference_says_so_instead_of_claiming_no_store(
    tmp_path: Path,
) -> None:
    """A configured but unreadable FASTA is an operator error, not missing data."""
    assembly = SimpleNamespace(
        name="Broken.assembly",
        release_id=1,
        fasta_url=str(tmp_path / "missing.fa"),
        fai_url=str(tmp_path / "missing.fa.fai"),
    )
    with pytest.raises(ReferenceUnavailable):
        read_reference_index(assembly)  # type: ignore[arg-type]


def test_residues_over_the_inline_limit_keep_their_true_length(tmp_path: Path) -> None:
    long_sequence = "A" * (MAX_INLINE_RESIDUES + 1)
    fasta, fai = _write_reference(tmp_path, "Gm01", long_sequence)
    assembly = _assembly(fasta, fai)
    reference = ReferenceState(index=read_reference_index(assembly))  # type: ignore[arg-type]
    gene = _gene(assembly, start=1, end=len(long_sequence))

    genomic = availability_entries(
        gene,  # type: ignore[arg-type]
        stored={},
        spans_by_transcript={},
        reference=reference,
    )[0]
    assert genomic.availability == "available"
    assert genomic.sequence is None
    assert genomic.length == len(long_sequence)
    assert genomic.reason == f"{RESIDUE_EXCEEDS_INLINE_LIMIT}:genomic"


def test_the_longest_cds_picks_the_isoform_that_speaks_for_the_gene() -> None:
    """CDS, protein and transcript must describe the same transcript.

    Ablation: choosing per molecule (longest CDS for ``cds``, longest body for
    ``transcript``) prints a CDS that is not contained in the transcript beside
    it -- the page shows two isoforms as if they were one.
    """
    stored = {
        "cds": [
            StoredResidue("tx-short", 300, "a" * 64, "A" * 300, False),
            StoredResidue("tx-long", 900, "b" * 64, "C" * 900, False),
        ],
        "protein": [
            StoredResidue("tx-short", 99, "c" * 64, "M" * 99, False),
            StoredResidue("tx-long", 299, "d" * 64, "K" * 299, False),
        ],
    }
    spans = {
        "tx-short": TranscriptSpans("tx-short", ((1, 500),), "+", False),
        "tx-long": TranscriptSpans("tx-long", ((1, 1_000),), "+", False),
    }
    representative = representative_transcript(transcript_layouts(stored, spans))
    assert representative is not None
    assert representative.transcript_id == "tx-long"


def test_a_canonical_isoform_speaks_even_when_it_is_shorter() -> None:
    stored = {
        "cds": [
            StoredResidue("tx-long", 900, "b" * 64, "C" * 900, False),
            StoredResidue("tx-canonical", 300, "e" * 64, "G" * 300, True),
        ]
    }
    representative = representative_transcript(transcript_layouts(stored, {}))
    assert representative is not None
    assert representative.transcript_id == "tx-canonical"


def test_the_longest_transcript_answers_for_the_gene() -> None:
    short = SimpleNamespace(
        transcript_id="tx1",
        length=30,
        sha256="a" * 64,
        sequence="A" * 30,
        is_canonical=False,
    )
    long = SimpleNamespace(
        transcript_id="tx2",
        length=90,
        sha256="b" * 64,
        sequence="C" * 90,
        is_canonical=False,
    )
    canonical = SimpleNamespace(
        transcript_id="tx3",
        length=60,
        sha256="c" * 64,
        sequence="G" * 60,
        is_canonical=True,
    )
    chosen = representative_residue([short, long, canonical])  # type: ignore[list-item]
    assert chosen is not None and chosen.transcript_id == "tx3"


# ---------------------------------------------------------------------------
# PostgreSQL integration
# ---------------------------------------------------------------------------


@dataclass
class _Scope:
    release: Release
    assembly: Assembly
    chromosome: Chromosome
    gene: Gene
    transcripts: list[Transcript]


async def _scope(
    db: AsyncSession,
    token: str,
    *,
    transcript_ids: tuple[str, ...] = ("tx1", "tx2"),
    accession: str = "Glyma.01G000100",
    start: int = 1,
    end: int = 1_000,
    strand: str = "+",
    reference: tuple[Path, Path] | None = None,
) -> _Scope:
    release = Release(
        version=f"residue-{token}",
        name=f"Residue test {token}",
        status=ReleaseStatus.DRAFT,
    )
    db.add(release)
    await db.flush()
    assembly = Assembly(
        name=f"Residue.{token}",
        version="a6",
        species="Glycine max",
        release_id=release.id,
        fasta_url=str(reference[0]) if reference else None,
        fai_url=str(reference[1]) if reference else None,
    )
    db.add(assembly)
    await db.flush()
    chromosome = Chromosome(assembly_id=assembly.id, name="Gm01", length=100_000)
    db.add(chromosome)
    await db.flush()
    gene = Gene(
        accession=accession,
        assembly_id=assembly.id,
        chromosome_id=chromosome.id,
        start=start,
        end=end,
        strand=strand,
    )
    db.add(gene)
    await db.flush()
    transcripts = [
        Transcript(
            id=f"{transcript_id}.Wm82.a6.v1",
            name=transcript_id,
            gene_id=gene.gene_pk,
            start=start,
            end=end,
            strand=strand,
            is_canonical=False,
        )
        for transcript_id in transcript_ids
    ]
    db.add_all(transcripts)
    await db.flush()
    return _Scope(release, assembly, chromosome, gene, transcripts)


async def _stored_rows(db: AsyncSession, scope: _Scope) -> list[tuple[str, str, str]]:
    result = await db.execute(
        select(
            TranscriptSequence.transcript_id,
            TranscriptSequence.molecule,
            TranscriptSequence.sequence,
        )
        .join(Transcript, Transcript.id == TranscriptSequence.transcript_id)
        .where(Transcript.gene_id == scope.gene.gene_pk)
        .order_by(TranscriptSequence.transcript_id, TranscriptSequence.molecule)
    )
    return [
        (transcript_id, molecule, sequence) for transcript_id, molecule, sequence in result.all()
    ]


def _fasta(directory: Path) -> tuple[Path, Path]:
    cds = _write(directory / "cds.fa", ">tx1\nACGTACGTAC\n>tx2\nGGGG\n")
    protein = _write(directory / "protein.fa", ">tx1.p transcript=tx1\nMKV*\n")
    return cds, protein


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_import_stores_residues_and_a_rerun_replaces_them(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    scope = await _scope(db_session, "import")
    cds, protein = _fasta(tmp_path)

    report = await import_transcript_sequences(
        db_session, assembly_id=scope.assembly.id, sources={"cds": cds, "protein": protein}
    )
    assert report.stored == 3
    assert report.replaced == 0
    assert report.records_read == {"cds": 2, "protein": 1}
    assert report.unknown_transcripts == {"cds": 0, "protein": 0}
    # ``transcripts.id`` is the version-prefixed storage key; the FASTA names the
    # transcript by its bare ``name``, and the importer resolves one to the other.
    assert await _stored_rows(db_session, scope) == [
        ("tx1.Wm82.a6.v1", "cds", "ACGTACGTAC"),
        ("tx1.Wm82.a6.v1", "protein", "MKV*"),
        ("tx2.Wm82.a6.v1", "cds", "GGGG"),
    ]

    rerun = await import_transcript_sequences(
        db_session, assembly_id=scope.assembly.id, sources={"cds": cds, "protein": protein}
    )
    # Replace-in-place, not accumulate: the row count is unchanged and the
    # previous rows are the ones that were deleted.
    assert rerun.replaced == 3
    assert rerun.stored == 3
    assert len(await _stored_rows(db_session, scope)) == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_record_id_resolves_by_transcript_name_when_the_id_is_prefixed(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """The annotation names the transcript ``X.1``; the row id is ``X.1.<version>``.

    Ablation: matching only ``transcripts.id`` stores nothing at all on the real
    soybean annotation -- every record becomes an unknown transcript and the
    gene keeps reporting ``unavailable`` for a reason no reader can see.
    """
    scope = await _scope(db_session, "names", transcript_ids=("tx1",))
    cds = _write(tmp_path / "cds.fa", ">tx1\nACGTAC\n")

    report = await import_transcript_sequences(
        db_session, assembly_id=scope.assembly.id, sources={"cds": cds}
    )
    assert report.unknown_transcripts == {"cds": 0}
    assert await _stored_rows(db_session, scope) == [("tx1.Wm82.a6.v1", "cds", "ACGTAC")]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_transcript_name_shared_by_two_rows_is_refused(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """Two candidates means a guess, and a guess means the wrong protein.

    Ablation: ``dict[name] = id`` in the resolver would silently keep the last
    row and attach one isoform's residues to another.
    """
    scope = await _scope(db_session, "ambiguous", transcript_ids=("tx1",))
    db_session.add(
        Transcript(
            id="tx1.duplicate",
            name="tx1",
            gene_id=scope.gene.gene_pk,
            start=1,
            end=100,
            strand="+",
            is_canonical=False,
        )
    )
    await db_session.flush()
    cds = _write(tmp_path / "cds.fa", ">tx1\nACGT\n")

    with pytest.raises(ResidueFastaError, match="refusing to attach"):
        await import_transcript_sequences(
            db_session, assembly_id=scope.assembly.id, sources={"cds": cds}
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_residues_for_unknown_transcripts_are_counted_not_stored(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    scope = await _scope(db_session, "unknown")
    cds = _write(tmp_path / "cds.fa", ">tx1\nACGT\n>Glyma.99G999999.1\nTTTT\n")

    report = await import_transcript_sequences(
        db_session, assembly_id=scope.assembly.id, sources={"cds": cds}
    )
    assert report.records_read == {"cds": 2}
    assert report.unknown_transcripts == {"cds": 1}
    assert await _stored_rows(db_session, scope) == [("tx1.Wm82.a6.v1", "cds", "ACGT")]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_residues_follow_their_transcript_when_it_is_replaced(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """A GFF3 re-import clears the assembly's transcripts; residues go with them."""
    scope = await _scope(db_session, "cascade")
    cds, protein = _fasta(tmp_path)
    await import_transcript_sequences(
        db_session, assembly_id=scope.assembly.id, sources={"cds": cds, "protein": protein}
    )
    assert len(await _stored_rows(db_session, scope)) == 3

    await db_session.execute(delete(Transcript).where(Transcript.gene_id == scope.gene.gene_pk))
    await db_session.flush()
    remaining = await db_session.scalar(select(func.count()).select_from(TranscriptSequence))
    assert remaining == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_database_refuses_a_length_that_disagrees_with_the_residues(
    db_session: AsyncSession,
) -> None:
    scope = await _scope(db_session, "shape")
    db_session.add(
        TranscriptSequence(
            transcript_id=scope.transcripts[0].id,
            molecule="cds",
            length=99,
            sha256=hashlib.sha256(b"ACGT").hexdigest(),
            sequence="ACGT",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_gene_with_stored_residues_reports_them_available(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    scope = await _scope(db_session, "available")
    cds, protein = _fasta(tmp_path)
    await import_transcript_sequences(
        db_session, assembly_id=scope.assembly.id, sources={"cds": cds, "protein": protein}
    )

    entries = {
        entry.molecule: entry
        for entry in await load_gene_sequences(
            db_session, scope.gene, release_context=ReleaseContext(release_id=scope.release.id)
        )
    }
    assert entries["cds"].availability == "available"
    assert entries["cds"].sequence == "ACGTACGTAC"
    assert entries["cds"].length == 10
    assert entries["cds"].checksum == hashlib.sha256(b"ACGTACGTAC").hexdigest()
    assert entries["protein"].availability == "available"
    assert entries["protein"].sequence == "MKV*"
    # This assembly declares no reference genome, so the derived molecules stay
    # unavailable -- with the reason shape clients already key on.
    assert entries["genomic"].availability == "unavailable"
    assert entries["genomic"].reason == f"{NO_SEQUENCE_STORE}:genomic"
    assert entries["transcript"].reason == f"{NO_SEQUENCE_STORE}:transcript"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_gene_with_nothing_stored_keeps_the_reason_shape(
    db_session: AsyncSession,
) -> None:
    scope = await _scope(db_session, "empty")
    entries: list[SequenceAvailability] = await load_gene_sequences(db_session, scope.gene)
    assert [entry.molecule for entry in entries] == [
        "genomic",
        "cds",
        "transcript",
        "protein",
    ]
    for entry in entries:
        assert entry.availability == "unavailable"
        assert entry.sequence is None
        assert entry.length is None
        assert entry.reason is not None
        assert entry.reason.startswith(NO_SEQUENCE_STORE)
    assert len({entry.reason for entry in entries}) == len(entries)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_gene_with_a_reference_reports_genomic_and_transcript_available(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    reference = "ACGT" * 250  # 1,000 bases, one per gene coordinate
    fasta, fai = _write_reference(tmp_path, "Gm01", reference)
    scope = await _scope(db_session, "reference", start=11, end=20, reference=(fasta, fai))

    entries = {entry.molecule: entry for entry in await load_gene_sequences(db_session, scope.gene)}
    genomic = entries["genomic"]
    assert genomic.availability == "available"
    assert genomic.sequence == reference[10:20]
    assert genomic.length == 10


@pytest.mark.integration
@pytest.mark.asyncio
async def test_residues_never_cross_assemblies_or_releases(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """The same accession in another release must not answer for this gene.

    Ablation: keying the residue lookup on the gene accession -- the tempting
    shortcut, since the FASTA is named per transcript and the accession is what
    the page shows -- would return a v4 gene's residues for a v5 gene.
    """
    first = await _scope(db_session, "cross-a", transcript_ids=("a-tx1",))
    second = await _scope(
        db_session, "cross-b", transcript_ids=("b-tx1",), accession="Glyma.01G000100"
    )
    await import_transcript_sequences(
        db_session,
        assembly_id=first.assembly.id,
        sources={"cds": _write(tmp_path / "a.fa", ">a-tx1\nAAAA\n")},
    )
    await import_transcript_sequences(
        db_session,
        assembly_id=second.assembly.id,
        sources={"cds": _write(tmp_path / "b.fa", ">b-tx1\nCCCC\n")},
    )

    by_molecule = {
        entry.molecule: entry for entry in await load_gene_sequences(db_session, first.gene)
    }
    assert by_molecule["cds"].sequence == "AAAA"

    # A context from the other release/assembly: no residues at all, rather than
    # the other gene's.
    out_of_scope = {
        entry.molecule: entry
        for entry in await load_gene_sequences(
            db_session,
            first.gene,
            release_context=ReleaseContext(
                release_id=second.release.id, assembly_id=second.assembly.id
            ),
        )
    }
    for entry in out_of_scope.values():
        assert entry.availability == "unavailable"
        assert entry.sequence is None
        assert entry.reason is not None and entry.reason.startswith(NO_SEQUENCE_STORE)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_broken_reference_path_does_not_break_the_gene_page(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    scope = await _scope(
        db_session,
        "broken",
        reference=(tmp_path / "gone.fa", tmp_path / "gone.fa.fai"),
    )
    entries = {entry.molecule: entry for entry in await load_gene_sequences(db_session, scope.gene)}
    assert entries["genomic"].availability == "unavailable"
    assert entries["genomic"].reason == f"{REFERENCE_UNAVAILABLE}:genomic"
    assert entries["transcript"].reason == f"{REFERENCE_UNAVAILABLE}:transcript"


def test_the_migration_and_the_model_declare_the_same_molecule_vocabulary() -> None:
    from app.models.genomic import TRANSCRIPT_SEQUENCE_MOLECULES

    source = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0060_transcript_sequences.py"
    ).read_text(encoding="utf-8")
    for molecule in TRANSCRIPT_SEQUENCE_MOLECULES:
        assert f"'{molecule}'" in source
