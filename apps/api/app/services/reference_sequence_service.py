"""Bounded slices of an assembly's reference genome.

The platform keeps reference residues **out of PostgreSQL on purpose**. A soybean
genome is ~1 GB; shredding it into rows would be neither storable nor
queryable, and a per-request whole-file load would be worse. What the database
holds instead is where the file is: ``assemblies.fasta_url`` plus the samtools
``.fai`` index in ``assemblies.fai_url`` (both written by the residue importer).

A ``.fai`` line records, per contig, its length and the byte offset of its first
base together with the FASTA line layout, which is exactly enough to turn a
1-based inclusive interval into a byte range. The read itself reuses
``seqfetch_service``'s offset arithmetic and ranged read, so a slice costs one
``seek``+``read`` (or one ranged GET) rather than a genome scan.

Two callers need this: ``genomic`` (one interval, the gene body) and
``transcript`` (one interval per exon, spliced in transcription order and
reverse-complemented on the minus strand). Both go through
:func:`clamp_to_contig` first, because a coordinate that runs past the end of
its contig is a data question, not an excuse to read into the next record.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ..models.genomic import Assembly
from .seqfetch_service import FaiRecord, parse_fai, read_bytes, slice_fasta

#: Complement table for both cases; IUPAC ambiguity codes included because a
#: soft-masked or gap-bearing reference must not crash the reader.
_COMPLEMENT = str.maketrans(
    "ACGTRYSWKMBDHVNacgtryswkmbdhvn",
    "TGCAYRSWMKVHDBNtgcayrswmkvhdbn",
)


class ReferenceUnavailable(RuntimeError):
    """The assembly declares a reference that cannot be read as declared.

    Raised for an unreadable/absent ``.fai`` or FASTA, an empty index, and a
    slice whose length disagrees with the index (a stale or truncated file).
    Callers translate it into an ``unavailable`` molecule with
    ``reference_unavailable`` -- never into a guess at the residues.

    A contig the index does not carry is *not* this exception: that is missing
    data, and :func:`read_reference_index` simply returns an index without it.
    """


@dataclass(frozen=True, slots=True)
class ReferenceSlice:
    """Residues read out of a reference, with the interval actually used."""

    contig: str
    contig_length: int
    start: int
    end: int
    sequence: str

    @property
    def length(self) -> int:
        return len(self.sequence)


def reverse_complement(sequence: str) -> str:
    """Complement a nucleotide string and reverse it."""
    return sequence.translate(_COMPLEMENT)[::-1]


def read_reference_index(assembly: Assembly) -> dict[str, FaiRecord]:
    """Parse the assembly's ``.fai`` into ``{contig_name: FaiRecord}``.

    Reads only the index (a few hundred bytes), never the reference itself.
    """
    if not assembly.fasta_url or not assembly.fai_url:
        raise ReferenceUnavailable(f"assembly {assembly.name!r} declares no reference FASTA/FAI")
    try:
        text = read_bytes(assembly.fai_url)
    except Exception as exc:  # noqa: BLE001 - every transport failure means "cannot read"
        # One handler on purpose: a missing local file (OSError), a dead URL
        # (httpx.HTTPError) and a denied S3 key (ClientError) are the same
        # answer to every caller, and none of them may become a 500 on the gene
        # page. The distinction is kept in the log line, not in the contract.
        raise ReferenceUnavailable(
            f"cannot read the index of {assembly.name!r}: {exc.__class__.__name__}: {exc}"
        ) from exc
    index = parse_fai(text)
    if not index:
        raise ReferenceUnavailable(f"the index of {assembly.name!r} names no contig")
    return index


def clamp_to_contig(record: FaiRecord, start: int, end: int) -> tuple[int, int] | None:
    """Clip a 1-based inclusive interval to the contig's own length.

    ``None`` means nothing is left to read (an interval entirely outside the
    contig, or one whose end precedes its start). Returning the clamped pair --
    rather than a bare string -- lets the caller report the length it actually
    served instead of the length it asked for.
    """
    clamped_start = max(1, start)
    clamped_end = min(end, record.length)
    if clamped_start > clamped_end:
        return None
    return clamped_start, clamped_end


def slice_contig(assembly: Assembly, record: FaiRecord, start: int, end: int) -> str:
    """Read the 1-based inclusive ``[start, end]`` residues of one contig.

    ``start``/``end`` must already be clamped (:func:`clamp_to_contig`).
    """
    if not assembly.fasta_url:
        raise ReferenceUnavailable(f"assembly {assembly.name!r} declares no reference FASTA")
    expected = end - start + 1
    try:
        sequence = slice_fasta(record, assembly.fasta_url, start, end)
    except Exception as exc:  # noqa: BLE001 - same reasoning as read_reference_index
        raise ReferenceUnavailable(
            f"cannot read {assembly.name!r} at {record.name}:{start}-{end}: "
            f"{exc.__class__.__name__}: {exc}"
        ) from exc
    if len(sequence) != expected:
        # A short read means the index and the FASTA disagree (truncated file,
        # regenerated genome). Serving the prefix would silently shift every
        # downstream coordinate, so refuse.
        raise ReferenceUnavailable(
            f"{assembly.name!r} returned {len(sequence)} residues for "
            f"{record.name}:{start}-{end}, expected {expected}"
        )
    return sequence.upper()


def splice_contig(
    assembly: Assembly,
    record: FaiRecord,
    spans: Iterable[tuple[int, int]],
    *,
    strand: str,
) -> str:
    """Splice exon ``spans`` into one transcript sequence, in reading order.

    ``spans`` are 1-based inclusive and may arrive in any order: transcription
    runs 5'→3', which is ascending on ``+`` and descending on ``-``, so the
    order is derived from ``strand`` here rather than trusted from the caller.
    Each exon is clamped to the contig and spliced before anything is
    reverse-complemented -- complementing after joining would reverse the exon
    order as well as the bases.
    """
    ordered = sorted(spans, reverse=strand == "-")
    pieces: list[str] = []
    for start, end in ordered:
        interval = clamp_to_contig(record, start, end)
        if interval is None:
            continue
        piece = slice_contig(assembly, record, interval[0], interval[1])
        pieces.append(reverse_complement(piece) if strand == "-" else piece)
    return "".join(pieces)


__all__ = [
    "ReferenceSlice",
    "ReferenceUnavailable",
    "clamp_to_contig",
    "read_reference_index",
    "reverse_complement",
    "slice_contig",
    "splice_contig",
]
