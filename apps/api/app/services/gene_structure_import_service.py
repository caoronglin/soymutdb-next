"""Import transcript structure (mRNA / CDS / UTR) from a GFF3 annotation.

The search importer (``local_test_preview_import_service``) reads GFF3 **gene**
rows only, on the stated grounds that transcript and CDS rows are not needed to
search. That is true for search and false for anything that draws a gene model:
the portal's genome view has always been able to render ``cds`` / ``utr5`` /
``utr3`` segments (``genome_view_svg.StructurePart.kind``,
``packages/genome-view/src/gene-structure.ts``), and until this module existed
there was no row anywhere in the schema that could supply one.

What it writes, from one pass over the file:

* ``transcripts``      — one row per ``mRNA`` feature.
* ``transcript_parts`` — one row per ``CDS`` / ``five_prime_UTR`` /
  ``three_prime_UTR`` feature, typed.
* ``exons``            — derived, not copied: GFF3 carries no ``exon`` feature,
  and an exon is by definition the union of the parts it contains. Merging here
  keeps the two views consistent at the source instead of asking every reader to
  re-derive it.

Coordinates are 1-based inclusive throughout, matching the GFF3.

Idempotent by replacement: everything already stored for the assembly's genes is
deleted first, inside the same transaction, so a re-run cannot leave a
half-updated mix. Nothing outside the assembly is touched.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Exon, Gene, Transcript, TranscriptPart

#: GFF3 feature type → ``transcript_parts.part_type``.
PART_TYPES: dict[str, str] = {
    "CDS": "cds",
    "five_prime_UTR": "five_prime_utr",
    "three_prime_UTR": "three_prime_utr",
}

#: ``transcript_parts.id`` is a BigInt sequence; these are the column names the
#: bulk insert fills. Kept explicit so a future column addition cannot silently
#: shift the payload.
_PART_COLUMNS = ("transcript_id", "part_type", "start", "end", "order")

DEFAULT_BATCH_SIZE = 5_000


@dataclass(slots=True)
class PartFeature:
    """One CDS/UTR feature, in file order."""

    part_type: str
    start: int
    end: int


def _merge_contiguous_spans(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Union of spans where *touching* counts as overlapping.

    For 1-based inclusive coordinates that is ````start <= last_end + 1````: the
    base after 199 is 200, so (100, 199) and (200, 300) describe one continuous
    stretch.

    Deliberately separate from ``genome_view_svg.merge_exon_spans``, which uses
    the strict ``start <= last_end`` because it answers a different question:
    when several isoforms' exons are collapsed for a gene-level lane, two exons
    that merely abut must stay separate — the gap between them is an intron, and
    merging would erase it from the picture.
    """
    ordered = sorted((start, end) for start, end in intervals if end >= start)
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1] + 1:
            last_start, last_end = merged[-1]
            merged[-1] = (last_start, max(last_end, end))
            continue
        merged.append((start, end))
    return merged


@dataclass(slots=True)
class TranscriptFeature:
    """One mRNA feature and the structural parts that hang off it."""

    transcript_id: str
    gene_accession: str
    start: int
    end: int
    strand: str
    biotype: str
    name: str | None = None
    parts: list[PartFeature] = field(default_factory=list)

    def exon_spans(self) -> list[tuple[int, int]]:
        """Exons of this transcript, as the union of its parts.

        A transcript with no CDS/UTR rows (some annotations only ship exons)
        falls back to its own body so it still renders as one segment.

        Uses :func:`_merge_contiguous_spans`, NOT the shared
        ``merge_exon_spans``: that one decides by ``start <= last_end``, which is
        right for the cross-isoform union it was written for (two exons that
        merely touch are still two exons) and wrong here. Within one transcript,
        a CDS at 200-300 and a 5' UTR at 100-199 are *contiguous* — 199 and 200
        are neighbouring bases in 1-based inclusive coordinates — so they are one
        exon and must merge. Reusing the shared helper silently split every
        single-exon gene model into a CDS box plus a UTR box with a hairline gap.
        """
        spans = _merge_contiguous_spans([(part.start, part.end) for part in self.parts])
        return spans or [(self.start, self.end)]


@dataclass(slots=True)
class StructureImportReport:
    """Counts the caller can assert on."""

    annotation_sha256: str
    gene_rows_skipped: int = 0
    transcripts: int = 0
    parts: int = 0
    exons: int = 0
    transcripts_without_gene: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "annotation_sha256": self.annotation_sha256,
            "gene_rows_skipped": self.gene_rows_skipped,
            "transcripts": self.transcripts,
            "parts": self.parts,
            "exons": self.exons,
            "transcripts_without_gene": self.transcripts_without_gene,
        }


def sha256_of_file(path: Path) -> str:
    """Content hash of the annotation, recorded so a run can be tied to its input."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_attributes(raw: str) -> dict[str, str]:
    """Parse a GFF3 column 9 into a dict.

    Values are percent-decoded only for the characters GFF3 escapes; the
    accession keys this module reads (``ID``, ``Parent``, ``Name``,
    ``biotype``) never contain them in practice, but decoding keeps a Name with
    a comma or a percent sign readable.
    """
    attributes: dict[str, str] = {}
    for field_text in raw.strip().split(";"):
        if not field_text:
            continue
        key, _, value = field_text.partition("=")
        key = key.strip()
        if not key:
            continue
        decoded = value.strip()
        if "%" in decoded:
            decoded = decoded.replace("%2C", ",").replace("%3B", ";").replace("%25", "%")
        attributes[key] = decoded
    return attributes


def parse_structure_features(path: Path) -> Iterator[TranscriptFeature]:
    """Yield one :class:`TranscriptFeature` per mRNA, with its parts attached.

    A transcript is yielded only once its parts have been read — when the *next*
    mRNA line arrives, or at end of file. Yielding on the mRNA line itself would
    hand the caller a feature whose ``parts`` list is still empty, because the
    generator would then resume and append to an object the caller has already
    finished with.

    GFF3 groups a feature's children directly beneath it, so an open transcript
    is enough state. A part naming an unknown parent is dropped rather than
    attached to a neighbouring transcript: a wrong gene model is worse than a
    missing one.
    """
    current: TranscriptFeature | None = None
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            if not raw or raw.startswith("#"):
                continue
            columns = raw.rstrip("\r\n").split("\t")
            if len(columns) != 9:
                continue
            feature_type = columns[2]

            if feature_type == "mRNA":
                if current is not None:
                    yield current
                    current = None
                attributes = _parse_attributes(columns[8])
                transcript_id = attributes.get("ID", "")
                parent = attributes.get("Parent", "")
                if not transcript_id or not parent or len(transcript_id) > 64:
                    continue
                current = TranscriptFeature(
                    transcript_id=transcript_id,
                    gene_accession=parent,
                    start=int(columns[3]),
                    end=int(columns[4]),
                    strand=columns[6] if columns[6] in {"+", "-"} else "+",
                    biotype=attributes.get("biotype") or "mRNA",
                    name=attributes.get("Name"),
                )
                continue

            part_type = PART_TYPES.get(feature_type)
            if part_type is None or current is None:
                continue
            attributes = _parse_attributes(columns[8])
            if attributes.get("Parent", "") != current.transcript_id:
                continue
            start = int(columns[3])
            end = int(columns[4])
            if end < start:
                continue
            current.parts.append(PartFeature(part_type=part_type, start=start, end=end))

    if current is not None:
        yield current


def _batched(rows: Sequence[dict[str, object]], size: int) -> Iterator[Sequence[dict[str, object]]]:
    for offset in range(0, len(rows), size):
        yield rows[offset : offset + size]


async def import_gene_structure(
    session: AsyncSession,
    path: Path,
    *,
    assembly_id: int,
    batch_size: int = DEFAULT_BATCH_SIZE,
    report: StructureImportReport | None = None,
    features: Iterable[TranscriptFeature] | None = None,
) -> StructureImportReport:
    """Load ``mRNA`` / ``CDS`` / UTR rows for one assembly.

    ``features`` lets a caller stream an already-parsed annotation (a test, or a
    caller that also wants the gene rows); otherwise the file is read here.

    The assembly's existing transcripts are deleted first — ``ON DELETE
    CASCADE`` removes their parts and exons — so the import replaces rather than
    accumulates and a second run is a no-op in effect.
    """
    import_report = report if report is not None else StructureImportReport(annotation_sha256="")
    if not import_report.annotation_sha256:
        import_report.annotation_sha256 = sha256_of_file(path)

    gene_rows = await session.execute(
        select(Gene.accession, Gene.gene_pk).where(Gene.assembly_id == assembly_id)
    )
    gene_pks = {accession: gene_pk for accession, gene_pk in gene_rows.all()}
    if not gene_pks:
        raise ValueError(f"No genes stored for assembly {assembly_id}")

    # Replace, inside this transaction: cascade clears transcript_parts and
    # exons. Scoped to the assembly's genes so another assembly's annotation --
    # a distinct coordinate namespace -- is never affected.
    #
    # Written as a subquery, not `in_(list(gene_pks.values()))`: the soybean
    # annotation has 48,387 genes and asyncpg refuses any statement with more
    # than 32,767 bound parameters, so the list form dies on a real assembly
    # ("the number of query arguments cannot exceed 32767"). The subquery sends
    # one parameter.
    await session.execute(
        delete(Transcript).where(
            Transcript.gene_id.in_(
                select(Gene.gene_pk).where(Gene.assembly_id == assembly_id)
            )
        )
    )

    transcript_rows: list[dict[str, object]] = []
    part_rows: list[dict[str, object]] = []
    exon_rows: list[dict[str, object]] = []

    source = features if features is not None else parse_structure_features(path)
    for transcript in source:
        gene_pk = gene_pks.get(transcript.gene_accession)
        if gene_pk is None:
            # The gene is outside this assembly (or the annotation mixes
            # versions); its transcript would have no valid parent.
            import_report.transcripts_without_gene += 1
            continue

        transcript_rows.append(
            {
                "id": transcript.transcript_id,
                "gene_id": gene_pk,
                "name": transcript.name,
                "biotype": transcript.biotype,
                "start": transcript.start,
                "end": transcript.end,
                "strand": transcript.strand,
                "is_canonical": False,
            }
        )

        # `order` is the file order within a type, which is how GFF3 encodes
        # transcript direction: for a minus-strand gene the CDS rows run from
        # high coordinate to low. Re-sorting by start would silently reverse the
        # reading frame of every minus-strand gene.
        counters: dict[str, int] = {}
        for part in transcript.parts:
            order = counters.get(part.part_type, 0) + 1
            counters[part.part_type] = order
            part_rows.append(
                {
                    "transcript_id": transcript.transcript_id,
                    "part_type": part.part_type,
                    "start": part.start,
                    "end": part.end,
                    "order": order,
                }
            )
        spans = transcript.exon_spans()
        exon_rows_before = len(exon_rows)
        for order, (start, end) in enumerate(spans, start=1):
            exon_rows.append(
                {
                    "transcript_id": transcript.transcript_id,
                    "start": start,
                    "end": end,
                    "order": order,
                }
            )

        import_report.transcripts += 1
        import_report.parts += len(transcript.parts)
        import_report.exons += len(exon_rows) - exon_rows_before

        if len(part_rows) >= batch_size * 4:
            # Parents first: `transcript_parts` and `exons` both carry a foreign
            # key to `transcripts.id`, and both are checked per statement, so
            # inserting a child batch before its parent batch fails outright.
            await session.execute(insert(Transcript), transcript_rows)
            await session.execute(insert(TranscriptPart), part_rows)
            await session.execute(insert(Exon), exon_rows)
            part_rows, exon_rows, transcript_rows = [], [], []

    for batch in _batched(transcript_rows, batch_size):
        await session.execute(insert(Transcript), list(batch))
    for batch in _batched(part_rows, batch_size):
        await session.execute(insert(TranscriptPart), list(batch))
    for batch in _batched(exon_rows, batch_size):
        await session.execute(insert(Exon), list(batch))

    return import_report


__all__ = [
    "PART_TYPES",
    "PartFeature",
    "StructureImportReport",
    "TranscriptFeature",
    "import_gene_structure",
    "parse_structure_features",
    "sha256_of_file",
]
