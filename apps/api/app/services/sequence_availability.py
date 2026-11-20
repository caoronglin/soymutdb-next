"""Per-gene sequence availability, decided once for every consumer.

The gene detail response must answer "can I get this gene's protein sequence?"
without inventing one. There is exactly one place that knows the answer, so the
portal, the API schema and any future MCP tool cannot disagree.

Two kinds of residue back the four molecules, and the difference decides the
answer:

* ``cds`` and ``protein`` come from ``transcript_sequences``, written by the
  annotation importer. A molecule is ``available`` only when a row exists for a
  transcript of *this* gene; nothing is inferred from the gene biotype, the
  annotation's reputation, or the fact that some other gene has residues.
* ``genomic`` and ``transcript`` are derived from the assembly's reference
  FASTA (``assemblies.fasta_url`` + ``.fai``): the gene body for ``genomic``,
  the exons spliced in reading order for ``transcript``. Nothing is stored, so
  they are ``available`` only when the assembly declares a readable reference
  and the interval actually falls inside a contig the index knows.

``reason`` stays a machine-readable ``prefix:molecule`` pair with a stable
prefix vocabulary: ``no_sequence_store`` when the platform holds nothing for
that molecule, ``reference_unavailable`` when the assembly declares a reference
that cannot be read (a log warning says why), and -- only alongside
``available`` -- ``residue_exceeds_inline_limit`` when the residues exist but
are too long to inline in a detail response.

One isoform answers for all four molecules (see
:func:`representative_transcript`), because the contract carries no transcript id:
a CDS from one isoform shown beside a transcript from another would be two
numbers in one table that do not agree.

Release scoping is inherited, not re-invented: the residue query is keyed by the
gene's surrogate ``gene_pk`` (unique per assembly) and the caller only passes a
gene it already resolved inside the request's release. When a caller passes a
``release_context`` the load re-checks it, because serving residues for a gene
outside the resolved release would be exactly the leak the rest of gene detail
is built to prevent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.genomic import Assembly, Exon, Gene, Transcript, TranscriptSequence
from ..schemas.gene_evidence import AVAILABILITY_LITERALS, SequenceAvailability
from ..utils.residue import residue_digest
from .reference_sequence_service import (
    ReferenceUnavailable,
    clamp_to_contig,
    read_reference_index,
    slice_contig,
    splice_contig,
)
from .release_context import ReleaseContext
from .seqfetch_service import FaiRecord

logger = logging.getLogger(__name__)

#: Machine-readable reason, stable across releases so clients can key on it.
NO_SEQUENCE_STORE = "no_sequence_store"
#: The assembly names a reference FASTA/FAI that cannot be read or parsed.
REFERENCE_UNAVAILABLE = "reference_unavailable"
#: The residues exist but exceed :data:`MAX_INLINE_RESIDUES`; served with length
#: and reason only, so a detail response never carries an unbounded string.
RESIDUE_EXCEEDS_INLINE_LIMIT = "residue_exceeds_inline_limit"

MOLECULE_LABELS = {
    "genomic": "genomic",
    "cds": "coding_sequence",
    "transcript": "transcript",
    "protein": "protein",
}

#: The four molecules a gene detail page offers, in the order it renders them.
MOLECULES = ("genomic", "cds", "transcript", "protein")

#: Residues longer than this are reported by length only. One soybean gene body
#: is at most ~105 kb today, so this bounds the payload without hiding data a
#: reader can still fetch by coordinates (SeqFetch).
MAX_INLINE_RESIDUES = 200_000

#: ``AVAILABILITY_LITERALS`` is declared ``available`` then ``unavailable``;
#: naming both once here keeps that order in a single place.
AVAILABLE, UNAVAILABLE = AVAILABILITY_LITERALS


def _reason(prefix: str, molecule: str) -> str:
    return f"{prefix}:{MOLECULE_LABELS[molecule]}"


def _unavailable(molecule: str, prefix: str = NO_SEQUENCE_STORE) -> SequenceAvailability:
    return SequenceAvailability(
        molecule=molecule,  # type: ignore[arg-type]
        availability=UNAVAILABLE,  # type: ignore[arg-type]
        reason=_reason(prefix, molecule),
    )


def _available(molecule: str, sequence: str) -> SequenceAvailability:
    return SequenceAvailability(
        molecule=molecule,  # type: ignore[arg-type]
        availability=AVAILABLE,  # type: ignore[arg-type]
        length=len(sequence),
        checksum=residue_digest(sequence),
        sequence=sequence,
    )


def _available_too_long(molecule: str, length: int) -> SequenceAvailability:
    """Residues that exist but must not be inlined; ``length`` is still true."""
    return SequenceAvailability(
        molecule=molecule,  # type: ignore[arg-type]
        availability=AVAILABLE,  # type: ignore[arg-type]
        reason=_reason(RESIDUE_EXCEEDS_INLINE_LIMIT, molecule),
        length=length,
    )


@dataclass(frozen=True, slots=True)
class StoredResidue:
    """One ``transcript_sequences`` row, with the transcript's canonical flag."""

    transcript_id: str
    length: int
    sha256: str
    sequence: str
    is_canonical: bool


@dataclass(frozen=True, slots=True)
class TranscriptSpans:
    """The exon layout of one transcript, used to splice its residues."""

    transcript_id: str
    spans: tuple[tuple[int, int], ...]
    strand: str
    is_canonical: bool

    @property
    def spliced_length(self) -> int:
        return sum(end - start + 1 for start, end in self.spans)


@dataclass(frozen=True, slots=True)
class ReferenceState:
    """The assembly's contig index, or the reason there is none."""

    index: dict[str, FaiRecord] | None
    #: ``None`` when ``index`` is usable; otherwise the reason prefix to report.
    reason: str = NO_SEQUENCE_STORE


@dataclass(frozen=True, slots=True)
class TranscriptLayout:
    """One isoform of a gene, reduced to what decides which one speaks for it."""

    transcript_id: str
    is_canonical: bool
    cds_length: int
    spliced_length: int


def transcript_layouts(
    stored: dict[str, list[StoredResidue]],
    spans_by_transcript: dict[str, TranscriptSpans],
) -> list[TranscriptLayout]:
    """Every transcript of the gene that has residues, exons, or both."""
    cds_lengths = {residue.transcript_id: residue.length for residue in stored.get("cds", [])}
    layouts: dict[str, TranscriptLayout] = {}
    for transcript_id, spans in spans_by_transcript.items():
        layouts[transcript_id] = TranscriptLayout(
            transcript_id=transcript_id,
            is_canonical=spans.is_canonical,
            cds_length=cds_lengths.get(transcript_id, 0),
            spliced_length=spans.spliced_length,
        )
    for residues in stored.values():
        for residue in residues:
            layouts.setdefault(
                residue.transcript_id,
                TranscriptLayout(
                    transcript_id=residue.transcript_id,
                    is_canonical=residue.is_canonical,
                    cds_length=cds_lengths.get(residue.transcript_id, 0),
                    spliced_length=0,
                ),
            )
    return list(layouts.values())


def representative_transcript(
    layouts: list[TranscriptLayout],
) -> TranscriptLayout | None:
    """The isoform that answers for the whole gene.

    The contract carries one ``sequence`` per molecule and no transcript id, so
    a reader cannot tell which isoform a residue came from. Picking separately
    per molecule would therefore publish a CDS from one isoform next to a
    transcript from another -- two numbers in the same table that do not agree
    with each other. One isoform answers for all of them: canonical first (the
    annotation's own choice when it states one), then the longest CDS, then the
    longest spliced body, then the transcript id as a deterministic tiebreak.
    """
    if not layouts:
        return None
    return min(
        layouts,
        key=lambda layout: (
            not layout.is_canonical,
            -layout.cds_length,
            -layout.spliced_length,
            layout.transcript_id,
        ),
    )


def representative_residue(candidates: list[StoredResidue]) -> StoredResidue | None:
    """Longest residue in a molecule, used only when the isoform lacks it.

    Availability is a gene-level question (:func:`_residue_entry`), so a gene
    whose speaking isoform has no protein row can still be answered by another
    transcript's row. That fallback never happens on a complete annotation --
    every transcript ships both molecules -- and it is kept rather than reported
    as ``unavailable`` because the residue really does exist for this gene.
    """
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda residue: (
            not residue.is_canonical,
            -residue.length,
            residue.transcript_id,
        ),
    )


def representative_spans(
    spans_by_transcript: dict[str, TranscriptSpans],
) -> TranscriptSpans | None:
    """The transcript whose exons are spliced for the ``transcript`` molecule."""
    if not spans_by_transcript:
        return None
    return min(
        spans_by_transcript.values(),
        key=lambda spans: (
            not spans.is_canonical,
            -spans.spliced_length,
            spans.transcript_id,
        ),
    )


async def load_stored_residues(db: AsyncSession, gene: Gene) -> dict[str, list[StoredResidue]]:
    """Residues stored for this gene's transcripts, grouped by molecule.

    Keyed by ``gene.gene_pk``, which is unique per assembly, so another
    assembly's transcripts can never answer for this gene even when the gene
    accessions happen to be equal across versions.
    """
    result = await db.execute(
        select(
            TranscriptSequence.transcript_id,
            TranscriptSequence.molecule,
            TranscriptSequence.length,
            TranscriptSequence.sha256,
            TranscriptSequence.sequence,
            Transcript.is_canonical,
        )
        .join(Transcript, Transcript.id == TranscriptSequence.transcript_id)
        .where(Transcript.gene_id == gene.gene_pk)
    )
    grouped: dict[str, list[StoredResidue]] = {}
    for transcript_id, molecule, length, sha256, sequence, is_canonical in result.all():
        grouped.setdefault(molecule, []).append(
            StoredResidue(
                transcript_id=transcript_id,
                length=length,
                sha256=sha256,
                sequence=sequence,
                is_canonical=is_canonical,
            )
        )
    return grouped


async def load_transcript_spans(db: AsyncSession, gene: Gene) -> dict[str, TranscriptSpans]:
    """Exon layout of every transcript of this gene, keyed by transcript id."""
    result = await db.execute(
        select(
            Exon.transcript_id,
            Exon.start,
            Exon.end,
            Transcript.strand,
            Transcript.is_canonical,
        )
        .join(Transcript, Transcript.id == Exon.transcript_id)
        .where(Transcript.gene_id == gene.gene_pk)
        .order_by(Exon.transcript_id, Exon.start)
    )
    grouped: dict[str, list[tuple[int, int]]] = {}
    strand_by_transcript: dict[str, str] = {}
    canonical_by_transcript: dict[str, bool] = {}
    for transcript_id, start, end, strand, is_canonical in result.all():
        grouped.setdefault(transcript_id, []).append((start, end))
        strand_by_transcript[transcript_id] = strand
        canonical_by_transcript[transcript_id] = is_canonical
    return {
        transcript_id: TranscriptSpans(
            transcript_id=transcript_id,
            spans=tuple(spans),
            strand=strand_by_transcript[transcript_id],
            is_canonical=canonical_by_transcript[transcript_id],
        )
        for transcript_id, spans in grouped.items()
    }


def reference_state(assembly: Assembly) -> ReferenceState:
    """Read the assembly's ``.fai`` (a few hundred bytes), never the genome."""
    if not assembly.fasta_url or not assembly.fai_url:
        return ReferenceState(index=None, reason=NO_SEQUENCE_STORE)
    try:
        return ReferenceState(index=read_reference_index(assembly))
    except ReferenceUnavailable as exc:
        # The detail page must survive an operator's broken path: the molecule
        # is unavailable, the reason says it is the reference and not the gene,
        # and the log line carries the actual path error.
        logger.warning("reference unavailable for assembly %s: %s", assembly.name, exc)
        return ReferenceState(index=None, reason=REFERENCE_UNAVAILABLE)


def _residue_entry(
    molecule: str,
    stored: list[StoredResidue],
    representative: TranscriptLayout | None,
) -> SequenceAvailability:
    """A stored molecule: available when any transcript of the gene has it.

    The residues come from the gene's speaking isoform so that the CDS, the
    protein and the spliced transcript shown together describe one transcript.
    """
    residue = next(
        (
            candidate
            for candidate in stored
            if representative is not None
            and candidate.transcript_id == representative.transcript_id
        ),
        representative_residue(stored),
    )
    if residue is None:
        return _unavailable(molecule)
    if residue.length > MAX_INLINE_RESIDUES:
        return _available_too_long(molecule, residue.length)
    return SequenceAvailability(
        molecule=molecule,  # type: ignore[arg-type]
        availability=AVAILABLE,  # type: ignore[arg-type]
        length=residue.length,
        checksum=residue.sha256,
        sequence=residue.sequence,
    )


def _genomic_entry(
    gene: Gene, record: FaiRecord | None, reference: ReferenceState
) -> SequenceAvailability:
    """The gene body, read from the reference and clamped to its contig."""
    if record is None:
        return _unavailable("genomic", reference.reason)
    interval = clamp_to_contig(record, gene.start, gene.end)
    if interval is None:
        return _unavailable("genomic")
    length = interval[1] - interval[0] + 1
    if length > MAX_INLINE_RESIDUES:
        return _available_too_long("genomic", length)
    try:
        sequence = slice_contig(gene.assembly, record, interval[0], interval[1])
    except ReferenceUnavailable as exc:
        logger.warning("reference slice failed for gene %s: %s", gene.accession, exc)
        return _unavailable("genomic", REFERENCE_UNAVAILABLE)
    return _available("genomic", sequence)


def _transcript_entry(
    gene: Gene,
    record: FaiRecord | None,
    reference: ReferenceState,
    representative: TranscriptLayout | None,
    spans_by_transcript: dict[str, TranscriptSpans],
) -> SequenceAvailability:
    """The exons of the speaking isoform, spliced in reading order."""
    if record is None:
        return _unavailable("transcript", reference.reason)
    spans = (
        spans_by_transcript.get(representative.transcript_id)
        if representative is not None
        else None
    ) or representative_spans(spans_by_transcript)
    if spans is None:
        return _unavailable("transcript")
    clamped = [
        interval
        for interval in (clamp_to_contig(record, start, end) for start, end in spans.spans)
        if interval is not None
    ]
    if not clamped:
        return _unavailable("transcript")
    length = sum(end - start + 1 for start, end in clamped)
    if length > MAX_INLINE_RESIDUES:
        return _available_too_long("transcript", length)
    try:
        sequence = splice_contig(gene.assembly, record, clamped, strand=spans.strand)
    except ReferenceUnavailable as exc:
        logger.warning("reference splice failed for gene %s: %s", gene.accession, exc)
        return _unavailable("transcript", REFERENCE_UNAVAILABLE)
    return _available("transcript", sequence)


def availability_entries(
    gene: Gene,
    *,
    stored: dict[str, list[StoredResidue]],
    spans_by_transcript: dict[str, TranscriptSpans],
    reference: ReferenceState,
) -> list[SequenceAvailability]:
    """Assemble the four molecules from already-loaded inputs (no database)."""
    record = reference.index.get(gene.chromosome.name) if reference.index else None
    representative = representative_transcript(transcript_layouts(stored, spans_by_transcript))
    return [
        _genomic_entry(gene, record, reference),
        _residue_entry("cds", stored.get("cds", []), representative),
        _transcript_entry(gene, record, reference, representative, spans_by_transcript),
        _residue_entry("protein", stored.get("protein", []), representative),
    ]


def _in_release_scope(gene: Gene, release_context: ReleaseContext | None) -> bool:
    """Whether this gene belongs to the release the request resolved."""
    if release_context is None:
        return True
    if (
        release_context.assembly_id is not None
        and int(release_context.assembly_id) != gene.assembly_id
    ):
        return False
    return gene.assembly.release_id == release_context.release_id


async def load_gene_sequences(
    db: AsyncSession,
    gene: Gene,
    *,
    release_context: ReleaseContext | None = None,
) -> list[SequenceAvailability]:
    """The four molecules a gene detail page offers, with honest availability.

    The answer is per gene and per molecule: a coding gene in an assembly whose
    CDS/protein FASTA was imported reports ``available`` with real residues, a
    gene with nothing stored keeps the ``no_sequence_store:<molecule>`` reason
    shape clients already key on, and a gene outside the resolved release
    returns no residues at all.
    """
    if not _in_release_scope(gene, release_context):
        return [_unavailable(molecule) for molecule in MOLECULES]

    stored = await load_stored_residues(db, gene)
    reference = reference_state(gene.assembly)
    # Exons are only read when they can be spliced: without a usable reference
    # the transcript molecule has no answer, and the query would be wasted.
    record = reference.index.get(gene.chromosome.name) if reference.index else None
    spans_by_transcript = await load_transcript_spans(db, gene) if record is not None else {}
    return availability_entries(
        gene,
        stored=stored,
        spans_by_transcript=spans_by_transcript,
        reference=reference,
    )


__all__ = [
    "MAX_INLINE_RESIDUES",
    "MOLECULES",
    "MOLECULE_LABELS",
    "NO_SEQUENCE_STORE",
    "REFERENCE_UNAVAILABLE",
    "RESIDUE_EXCEEDS_INLINE_LIMIT",
    "ReferenceState",
    "StoredResidue",
    "TranscriptLayout",
    "TranscriptSpans",
    "availability_entries",
    "load_gene_sequences",
    "load_stored_residues",
    "load_transcript_spans",
    "reference_state",
    "representative_residue",
    "representative_spans",
    "representative_transcript",
    "transcript_layouts",
]
