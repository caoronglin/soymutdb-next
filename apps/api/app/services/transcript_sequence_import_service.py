"""Import per-transcript CDS and protein residues from the annotation's FASTA.

    python -m app.scripts.import_transcript_sequences \
        --assembly-id 1 \
        --cds Gmax_880_Wm82.a6.v1.cds.fa \
        --protein Gmax_880_Wm82.a6.v1.protein.fa

The search importer stores gene rows and ``import_gene_structure`` stores the
transcript/exon model; neither keeps a single residue. This module fills
``transcript_sequences`` from the two files the annotation ships per transcript,
which is what lets the gene detail contract answer ``available`` instead of
``no_sequence_store``.

What it reads, and how strictly
-------------------------------
One record per transcript. The transcript id is the record id in the CDS file
and, in the protein file, the ``transcript=`` attribute the annotation writes on
each header (the record id there carries a ``.p`` suffix and is not a
transcript). A header that yields no usable id, an empty record, a duplicate id
and a character outside the molecule's alphabet all raise: a residue loader that
skipped a malformed record would leave a gene silently ``unavailable`` with no
trace of why.

Replace-in-place, one transaction
---------------------------------
Every stored residue belonging to the assembly's transcripts is deleted first,
so a re-run cannot leave a half-updated mix and cannot accumulate rows for
transcripts that no longer exist. The transcript table itself is left alone:
``transcript_sequences`` follows it by ``ON DELETE CASCADE``, which means the
GFF3 import must run *before* this one (it replaces all transcripts of the
assembly and would otherwise clear residues imported ahead of it).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from sqlalchemy import CursorResult, delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Gene, Transcript, TranscriptSequence
from ..models.genomic import TRANSCRIPT_SEQUENCE_MOLECULES
from ..utils.residue import residue_digest
from .gene_structure_import_service import sha256_of_file

#: Accepted residues per molecule. Anything else is a malformed record, not a
#: residue the platform should serve.
DNA_ALPHABET: frozenset[str] = frozenset("ACGTRYSWKMBDHVN")
PROTEIN_ALPHABET: frozenset[str] = frozenset("ACDEFGHIKLMNPQRSTVWYBXZJUO*")

ALPHABETS: dict[str, frozenset[str]] = {
    "cds": DNA_ALPHABET,
    "protein": PROTEIN_ALPHABET,
}

#: ``transcripts.id`` is ``String(64)``; an id longer than that cannot exist in
#: the catalogue, so the header is malformed rather than merely unknown.
MAX_TRANSCRIPT_ID_LENGTH: int = 64

DEFAULT_BATCH_SIZE = 5_000

#: Header attributes some sources use to name the transcript of a protein
#: record, in preference order.
_PROTEIN_PARENT_KEYS = ("transcript", "transcript_id")

#: Returned by :meth:`TranscriptIndex.resolve` when a record id names more than
#: one transcript of the assembly. A residue attached to the wrong isoform is a
#: wrong protein, so the import refuses instead of picking one.
AMBIGUOUS = object()


@dataclass(frozen=True, slots=True)
class ResidueRecord:
    """One FASTA record, reduced to the transcript it belongs to."""

    transcript_id: str
    sequence: str


@dataclass(slots=True)
class ResidueImportReport:
    """Counts the caller can assert on, per molecule plus the replacement."""

    assembly_id: int
    source_sha256: dict[str, str] = field(default_factory=dict)
    records_read: dict[str, int] = field(default_factory=dict)
    unknown_transcripts: dict[str, int] = field(default_factory=dict)
    replaced: int = 0
    stored: int = 0

    def as_dict(self) -> dict[str, object]:
        flat: dict[str, object] = {
            "assembly_id": self.assembly_id,
            "replaced": self.replaced,
            "stored": self.stored,
        }
        for molecule in sorted(self.source_sha256):
            flat[f"{molecule}_source_sha256"] = self.source_sha256[molecule]
            flat[f"{molecule}_records"] = self.records_read.get(molecule, 0)
            flat[f"{molecule}_unknown_transcripts"] = self.unknown_transcripts.get(molecule, 0)
        return flat


class ResidueFastaError(ValueError):
    """A FASTA that cannot be read as residues; the import must not continue."""


def _malformed(path: Path, line_number: int, detail: str) -> ResidueFastaError:
    return ResidueFastaError(f"{path}:{line_number}: {detail}")


def _header_transcript_id(path: Path, line_number: int, header: str, molecule: str) -> str:
    """The transcript id of one header line, or a hard failure.

    ``protein`` headers from the SoyBase-style annotation look like
    ``>Glyma.07G273800.2.p pacid=… transcript=Glyma.07G273800.2 locus=…``: the
    record id is the *protein* id, so the parent transcript is the attribute.
    When the attribute is absent the record id is used as-is -- a FASTA whose
    records are named after their transcripts is a normal shape, and a suffix
    guess (``.p`` -> strip) would invent a mapping the file never stated.
    """
    fields = header.split()
    if not fields:
        raise _malformed(path, line_number, "empty FASTA header")
    record_id = fields[0]
    attributes = {
        key: value
        for key, _, value in (field.partition("=") for field in fields[1:])
        if key and value
    }
    if molecule == "protein":
        for key in _PROTEIN_PARENT_KEYS:
            if attributes.get(key):
                record_id = attributes[key]
                break
    if not record_id or len(record_id) > MAX_TRANSCRIPT_ID_LENGTH:
        raise _malformed(
            path,
            line_number,
            f"header names no transcript id of at most {MAX_TRANSCRIPT_ID_LENGTH} "
            f"characters: {header[:120]!r}",
        )
    return record_id


def parse_residue_fasta(path: Path, *, molecule: str) -> Iterator[ResidueRecord]:
    """Yield one :class:`ResidueRecord` per FASTA record, validating as it goes.

    Fails closed: a header without a transcript id, a record without residues, a
    residue outside :data:`ALPHABETS` and a duplicated transcript id all raise
    :class:`ResidueFastaError` naming the file and line. Skipping any of them
    would publish a gene as ``unavailable`` for a reason no one can see.
    """
    alphabet = ALPHABETS.get(molecule)
    if alphabet is None:
        raise ValueError(
            f"unknown molecule {molecule!r}; expected one of "
            f"{', '.join(TRANSCRIPT_SEQUENCE_MOLECULES)}"
        )

    transcript_id: str | None = None
    header_line = 0
    chunks: list[str] = []
    seen: set[str] = set()

    def flush(parent_id: str) -> ResidueRecord:
        sequence = "".join(chunks)
        if not sequence:
            raise _malformed(path, header_line, f"record {parent_id!r} carries no residues")
        if parent_id in seen:
            raise _malformed(path, header_line, f"transcript {parent_id!r} appears twice")
        seen.add(parent_id)
        return ResidueRecord(transcript_id=parent_id, sequence=sequence)

    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if transcript_id is not None:
                    yield flush(transcript_id)
                transcript_id = _header_transcript_id(path, line_number, line[1:], molecule)
                header_line = line_number
                chunks = []
                continue
            if transcript_id is None:
                raise _malformed(path, line_number, "residues before the first FASTA header")
            residues = line.upper()
            illegal = set(residues) - alphabet
            if illegal:
                raise _malformed(
                    path,
                    line_number,
                    f"record {transcript_id!r} contains {sorted(illegal)} which is "
                    f"not a {molecule} residue",
                )
            chunks.append(residues)

    if transcript_id is not None:
        yield flush(transcript_id)


def _batched(rows: Sequence[dict[str, object]], size: int) -> Iterator[Sequence[dict[str, object]]]:
    for offset in range(0, len(rows), size):
        yield rows[offset : offset + size]


@dataclass(frozen=True, slots=True)
class TranscriptIndex:
    """Maps a FASTA record id onto ``transcripts.id`` for one assembly.

    ``transcripts.id`` is the storage key, and the annotation importer prefixes
    it with the annotation version (``Glyma.01G000100.2.Wm82.a6.v1``) while the
    FASTA file names the record ``Glyma.01G000100.2`` -- the transcript's own
    ``name``. Both spellings have to resolve, in that order: an exact ``id``
    first, then the transcription's ``name``.

    A name shared by two transcripts resolves to :data:`AMBIGUOUS` rather than
    to either of them.
    """

    ids: frozenset[str]
    by_name: dict[str, list[str]]

    def resolve(self, record_id: str) -> str | object | None:
        """``transcripts.id``, :data:`AMBIGUOUS`, or ``None`` when unknown."""
        if record_id in self.ids:
            return record_id
        candidates = self.by_name.get(record_id, [])
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            return AMBIGUOUS
        return None


async def _assembly_transcripts(session: AsyncSession, assembly_id: int) -> TranscriptIndex:
    """Every transcript of the assembly, the only valid residue parents.

    Written as a join on the surrogate gene key, so another assembly's
    transcripts -- a distinct coordinate namespace -- can never be matched by a
    coincidentally equal id.
    """
    result = await session.execute(
        select(Transcript.id, Transcript.name)
        .join(Gene, Transcript.gene_id == Gene.gene_pk)
        .where(Gene.assembly_id == assembly_id)
    )
    ids: set[str] = set()
    by_name: dict[str, list[str]] = {}
    for transcript_id, name in result.all():
        ids.add(transcript_id)
        if name:
            by_name.setdefault(name, []).append(transcript_id)
    return TranscriptIndex(ids=frozenset(ids), by_name=by_name)


async def import_transcript_sequences(
    session: AsyncSession,
    *,
    assembly_id: int,
    sources: dict[str, Path],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> ResidueImportReport:
    """Load ``sources`` (molecule -> FASTA) for one assembly, replacing stores.

    Read-only counterpart: ``app.services.sequence_availability``.
    """
    if not sources:
        raise ValueError("no residue source given")
    unknown_molecules = set(sources) - set(TRANSCRIPT_SEQUENCE_MOLECULES)
    if unknown_molecules:
        raise ValueError(
            f"unknown molecule(s) {sorted(unknown_molecules)}; the store holds "
            f"{', '.join(TRANSCRIPT_SEQUENCE_MOLECULES)}"
        )
    for path in sources.values():
        if not path.is_file():
            raise FileNotFoundError(f"residue source not found: {path}")

    report = ResidueImportReport(assembly_id=assembly_id)
    for molecule, path in sources.items():
        report.source_sha256[molecule] = sha256_of_file(path)

    index = await _assembly_transcripts(session, assembly_id)
    if not index.ids:
        raise ValueError(f"no transcripts stored for assembly {assembly_id}; import the GFF3 first")

    # Replace, inside this transaction. The subquery keeps the statement to one
    # bound parameter: the soybean assembly has 80,374 transcripts and asyncpg
    # refuses statements with more than 32,767 of them.
    deleted = await session.execute(
        delete(TranscriptSequence).where(
            TranscriptSequence.transcript_id.in_(
                select(Transcript.id)
                .join(Gene, Transcript.gene_id == Gene.gene_pk)
                .where(Gene.assembly_id == assembly_id)
            )
        )
    )
    report.replaced = int(cast(CursorResult, deleted).rowcount or 0)

    for molecule, path in sources.items():
        rows: list[dict[str, object]] = []
        read = 0
        unknown = 0
        for record in parse_residue_fasta(path, molecule=molecule):
            read += 1
            resolved = index.resolve(record.transcript_id)
            if resolved is AMBIGUOUS:
                raise ResidueFastaError(
                    f"{path}: record {record.transcript_id!r} names "
                    f"{len(index.by_name.get(record.transcript_id, []))} transcripts of "
                    f"assembly {assembly_id}; refusing to attach residues to a guess"
                )
            if resolved is None:
                unknown += 1
                continue
            rows.append(
                {
                    "transcript_id": resolved,
                    "molecule": molecule,
                    "length": len(record.sequence),
                    "sha256": residue_digest(record.sequence),
                    "sequence": record.sequence,
                }
            )
        for batch in _batched(rows, batch_size):
            await session.execute(insert(TranscriptSequence), list(batch))
        report.records_read[molecule] = read
        report.unknown_transcripts[molecule] = unknown
        report.stored += len(rows)

    return report


def count_residue_records(sources: Iterable[tuple[str, Path]]) -> dict[str, int]:
    """Parse every source without a database, for ``--dry-run``.

    Runs the same parser, so a malformed header is reported by a dry run too:
    the point of the flag is to validate the files, not to skip them.
    """
    counts: dict[str, int] = {}
    for molecule, path in sources:
        counts[molecule] = sum(1 for _ in parse_residue_fasta(path, molecule=molecule))
    return counts


__all__ = [
    "ALPHABETS",
    "AMBIGUOUS",
    "DNA_ALPHABET",
    "PROTEIN_ALPHABET",
    "ResidueFastaError",
    "ResidueImportReport",
    "ResidueRecord",
    "TranscriptIndex",
    "count_residue_records",
    "import_transcript_sequences",
    "parse_residue_fasta",
]
