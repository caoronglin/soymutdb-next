"""Durable writers for reference-FASTA and GFF3 annotation imports.

Why this module exists
    Two import feature flags were documented as *"writer not yet closed"*, and
    the documentation was accurate:

    * ``FastaAdapter.run`` raised ``UnsupportedImportError`` outright — no
      reference sequence or chromosome length was ever persisted;
    * ``ingest.import_gff3`` streamed the file, counted ``gene`` / ``mRNA`` /
      ``exon`` rows and returned the counts. It opened no session and wrote no
      row, so a green import reported "48,387 genes" while the catalogue stayed
      empty.

    Enabling a flag therefore could not mean "stored". These writers close that
    gap for the two formats whose shape is fixed and whose real inputs exist in
    the repository's test data: a FASTA plus its ``.fai`` index, and a GFF3
    annotation.

Contract
    * Sync SQLAlchemy sessions (``soymutdb_worker.utils.db.get_db``), Core
      tables from ``soymutdb_worker.tables``. The worker never imports the API.
    * Replace-in-place per assembly: a re-run cannot leave a half-updated mix of
      old and new annotation. The FASTA writer replaces ``chromosomes`` rows for
      the assembly; the GFF3 writer replaces the genes it re-inserts together
      with their transcripts, parts and exons.
    * Fail closed on anything the file does not actually say: an unknown
      chromosome, coordinates outside the reference length, a duplicate gene or
      transcript id, a strand other than ``+``/``-``, or a transcript whose gene
      is absent from the same file. A partial write is never reported as a pass.
    * Exons are *derived*, never copied: this annotation carries no ``exon``
      feature, and an exon is by definition the union of the CDS/UTR parts it
      contains. Deriving here keeps the two views consistent at the source.
"""

from __future__ import annotations

import hashlib
import io
import logging
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from ..tables import chromosomes, exons, genes, transcript_parts, transcripts

logger = logging.getLogger(__name__)

#: GFF3 feature type -> ``transcript_parts.part_type``. Mirrors the API's
#: ``gene_structure_import_service.PART_TYPES``: the two writers describe the
#: same file, so they must agree on the vocabulary.
PART_TYPES: dict[str, str] = {
    "CDS": "cds",
    "five_prime_UTR": "five_prime_utr",
    "three_prime_UTR": "three_prime_utr",
}

#: Transcript feature types. This annotation uses ``mRNA``; ``transcript`` is
#: accepted because it is the other legal GFF3 spelling for the same concept.
TRANSCRIPT_TYPES: frozenset[str] = frozenset({"mRNA", "transcript"})

DEFAULT_BATCH_SIZE = 5_000


class AnnotationWriteError(ValueError):
    """A file that cannot be stored faithfully. Never converted into a pass."""


@dataclass(slots=True)
class FastaWriteReport:
    chromosomes: int
    replaced: int
    fasta_sha256: str | None


@dataclass(slots=True)
class Gff3WriteReport:
    genes: int
    transcripts: int
    parts: int
    exons: int
    replaced_genes: int


@dataclass(slots=True)
class _TranscriptDraft:
    gene_id: str
    name: str | None
    start: int
    end: int
    strand: str
    biotype: str
    #: ``(part_type, start, end)`` in file order.
    parts: list[tuple[str, int, int]] = field(default_factory=list)

    def exon_spans(self) -> list[tuple[int, int]]:
        """Union of the parts, with *touching* spans merged.

        For 1-based inclusive coordinates the base after 199 is 200, so
        ``(100, 199)`` and ``(200, 300)`` are one continuous stretch. This
        matches the API writer's ``_merge_contiguous_spans``.
        """
        ordered = sorted((s, e) for _, s, e in self.parts if e >= s)
        merged: list[list[int]] = []
        for start, end in ordered:
            if merged and start <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return [(start, end) for start, end in merged]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_fai(path: Path) -> OrderedDict[str, int]:
    """Read ``name<TAB>length`` from a ``.fai`` index, in file order.

    Order is preserved because ``chromosomes.order`` is what the browser and the
    search UI use to present a stable karyotype order; sorting by name would put
    ``Gm10`` before ``Gm2``.
    """
    lengths: OrderedDict[str, int] = OrderedDict()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            columns = raw.rstrip("\r\n").split("\t")
            if len(columns) < 5:
                raise AnnotationWriteError(f"FAI line {line_number} has fewer than 5 fields")
            name = columns[0].strip()
            if not name:
                raise AnnotationWriteError(f"FAI line {line_number} has no sequence name")
            try:
                length = int(columns[1])
            except ValueError as exc:
                raise AnnotationWriteError(
                    f"FAI line {line_number} has an invalid length"
                ) from exc
            if length < 1:
                raise AnnotationWriteError(f"FAI line {line_number} has a non-positive length")
            if name in lengths:
                raise AnnotationWriteError(f"FAI repeats the sequence name {name!r}")
            lengths[name] = length
    if not lengths:
        raise AnnotationWriteError("FAI index is empty")
    return lengths


def _assembly_chromosomes(session: Session, assembly_id: int) -> dict[str, int]:
    rows = session.execute(
        select(chromosomes.c.name, chromosomes.c.id).where(
            chromosomes.c.assembly_id == assembly_id
        )
    ).all()
    return {str(name): int(pk) for name, pk in rows if name is not None}


def write_reference_fai(
    session: Session,
    *,
    assembly_id: int,
    fai_path: Path,
    fasta_path: Path | None = None,
    replace: bool = True,
) -> FastaWriteReport:
    """Persist the reference sequence lengths for one assembly.

    Only the index is read: the ``.fai`` is the authoritative statement of what
    the reference *is* (names, lengths, order), and reading a multi-gigabyte
    FASTA to learn the same numbers would add hours to every import without
    changing a single stored value. When ``fasta_path`` is supplied it must
    exist, so an operator who points at a missing genome is told immediately
    instead of after a successful-looking length import.
    """
    if fasta_path is not None and not fasta_path.exists():
        raise AnnotationWriteError(f"reference FASTA not found: {fasta_path}")

    lengths = parse_fai(fai_path)
    existing = _assembly_chromosomes(session, assembly_id)
    replaced = len(existing) if replace else 0
    if replace:
        # Delete the assembly's rows first: a re-import with a renamed or
        # shortened sequence must not leave the previous definition behind.
        session.execute(delete(chromosomes).where(chromosomes.c.assembly_id == assembly_id))

    rows = [
        {
            "assembly_id": assembly_id,
            "name": name,
            "length": length,
            "order": order,
        }
        for order, (name, length) in enumerate(lengths.items())
    ]
    for offset in range(0, len(rows), DEFAULT_BATCH_SIZE):
        session.execute(insert(chromosomes), rows[offset : offset + DEFAULT_BATCH_SIZE])
    session.flush()

    return FastaWriteReport(
        chromosomes=len(rows),
        replaced=replaced,
        fasta_sha256=_sha256_file(fasta_path) if fasta_path is not None else None,
    )


def parse_gff3_attributes(raw: str, *, line_number: int) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for field_text in raw.strip().split(";"):
        if not field_text:
            continue
        key, _, value = field_text.partition("=")
        key = key.strip()
        if not key:
            raise AnnotationWriteError(f"GFF3 line {line_number} has an attribute without a key")
        attributes.setdefault(key, value.strip())
    return attributes


@dataclass(slots=True)
class _GeneDraft:
    accession: str
    chromosome: str
    start: int
    end: int
    strand: str
    name: str | None
    biotype: str
    description: str | None


def _iter_gff3_rows(path: Path) -> Iterator[list[str]]:
    """Stream 9-column GFF3 data rows, skipping directives and comments."""
    opener = io.open
    if path.suffix == ".gz":
        import gzip

        def _open() -> Any:  # pragma: no cover - gzip path exercised by caller
            return gzip.open(path, "rt", encoding="utf-8", newline="")

        handle = _open()
    else:
        handle = opener(path, "r", encoding="utf-8", newline="")
    try:
        for line_number, raw in enumerate(handle, 1):
            if not raw or raw.startswith("#"):
                continue
            columns = raw.rstrip("\r\n").split("\t")
            if len(columns) != 9:
                raise AnnotationWriteError(f"GFF3 line {line_number} must contain 9 fields")
            yield columns
    finally:
        handle.close()


def write_gff3_annotation(
    session: Session,
    *,
    assembly_id: int,
    path: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Gff3WriteReport:
    """Store genes, transcripts, CDS/UTR parts and derived exons.

    Two passes over the file, both streaming:

    1. collect gene rows and transcript drafts (bounded by the annotation, not
       by the file size — a transcript draft holds only its part coordinates);
    2. write genes, read their surrogate keys back, then write transcripts,
       parts and exons.

    A single pass would have to buffer every row of a 120 MB annotation, and the
    ``genes.gene_pk`` surrogate is only known after the gene insert.
    """
    if not path.exists():
        raise AnnotationWriteError(f"annotation not found: {path}")

    chromosome_ids = _assembly_chromosomes(session, assembly_id)
    if not chromosome_ids:
        raise AnnotationWriteError(
            "no chromosomes registered for this assembly: import the reference "
            "FASTA (and its .fai index) before the annotation"
        )
    # The reference lengths are the only defensible coordinate bound.
    lengths = {
        str(name): int(length)
        for name, length in session.execute(
            select(chromosomes.c.name, chromosomes.c.length).where(
                chromosomes.c.assembly_id == assembly_id
            )
        ).all()
        if name is not None
    }

    gene_drafts: OrderedDict[str, _GeneDraft] = OrderedDict()
    transcript_drafts: OrderedDict[str, _TranscriptDraft] = OrderedDict()

    for columns in _iter_gff3_rows(path):
        chromosome, _, feature_type, start_raw, end_raw, _, strand, _, attr_raw = columns
        if feature_type not in {"gene"} | TRANSCRIPT_TYPES | set(PART_TYPES):
            continue
        if chromosome not in chromosome_ids:
            raise AnnotationWriteError(
                f"annotation uses chromosome {chromosome!r}, which the assembly has not registered"
            )
        try:
            start = int(start_raw)
            end = int(end_raw)
        except ValueError as exc:
            raise AnnotationWriteError(
                f"annotation has non-integer coordinates: {columns!r}"
            ) from exc
        reference_length = lengths.get(chromosome)
        if start < 1 or end < start or (reference_length is not None and end > reference_length):
            raise AnnotationWriteError(
                f"annotation has out-of-range coordinates {chromosome}:{start}-{end}"
            )
        if strand not in {"+", "-"}:
            raise AnnotationWriteError(f"annotation has an invalid strand {strand!r}")
        attributes = parse_gff3_attributes(attr_raw, line_number=0)
        feature_id = attributes.get("ID", "").strip()

        if feature_type == "gene":
            if not feature_id:
                raise AnnotationWriteError("a gene row has no ID attribute")
            if feature_id in gene_drafts:
                raise AnnotationWriteError(f"annotation repeats gene id {feature_id!r}")
            gene_drafts[feature_id] = _GeneDraft(
                accession=feature_id,
                chromosome=chromosome,
                start=start,
                end=end,
                strand=strand,
                name=attributes.get("Name") or None,
                biotype="gene",
                description=attributes.get("description") or None,
            )
            continue

        if feature_type in TRANSCRIPT_TYPES:
            if not feature_id:
                raise AnnotationWriteError("a transcript row has no ID attribute")
            parent = attributes.get("Parent", "").strip()
            if not parent:
                raise AnnotationWriteError(f"transcript {feature_id!r} names no Parent gene")
            if feature_id in transcript_drafts:
                raise AnnotationWriteError(f"annotation repeats transcript id {feature_id!r}")
            transcript_drafts[feature_id] = _TranscriptDraft(
                gene_id=parent,
                name=attributes.get("Name") or None,
                start=start,
                end=end,
                strand=strand,
                biotype=feature_type,
            )
            continue

        # CDS / UTR: attach to the transcript named by Parent.
        parent = attributes.get("Parent", "").strip()
        if not parent:
            raise AnnotationWriteError(f"{feature_type} row names no Parent transcript")
        target = transcript_drafts.get(parent)
        if target is None:
            raise AnnotationWriteError(
                f"{feature_type} row references transcript {parent!r}, "
                "which the file never declares"
            )
        target.parts.append((PART_TYPES[feature_type], start, end))

    if not gene_drafts:
        raise AnnotationWriteError("annotation declares no genes")

    orphans = sorted({draft.gene_id for draft in transcript_drafts.values()} - set(gene_drafts))
    if orphans:
        raise AnnotationWriteError(
            "annotation has transcripts whose gene is absent from the same file: "
            + ", ".join(orphans[:5])
        )

    # Replace-in-place: the genes this file re-inserts are removed first, and the
    # schema's ON DELETE CASCADE clears their transcripts, parts and exons.
    existing = [
        int(pk)
        for (pk,) in session.execute(
            select(genes.c.gene_pk).where(
                genes.c.assembly_id == assembly_id,
                genes.c.accession.in_(list(gene_drafts)),
            )
        ).all()
    ]
    if existing:
        session.execute(delete(genes).where(genes.c.gene_pk.in_(existing)))
        session.flush()

    gene_rows = [
        {
            "accession": draft.accession,
            "assembly_id": assembly_id,
            "chromosome_id": chromosome_ids[draft.chromosome],
            "name": draft.name,
            "biotype": draft.biotype,
            "start": draft.start,
            "end": draft.end,
            "strand": draft.strand,
            "description": draft.description,
        }
        for draft in gene_drafts.values()
    ]
    for offset in range(0, len(gene_rows), batch_size):
        session.execute(insert(genes), gene_rows[offset : offset + batch_size])
    session.flush()

    gene_pks: dict[str, int] = {}
    accessions = list(gene_drafts)
    for offset in range(0, len(accessions), batch_size):
        batch = accessions[offset : offset + batch_size]
        for accession, pk in session.execute(
            select(genes.c.accession, genes.c.gene_pk).where(
                genes.c.assembly_id == assembly_id,
                genes.c.accession.in_(batch),
            )
        ).all():
            gene_pks[str(accession)] = int(pk)

    missing = set(gene_drafts) - set(gene_pks)
    if missing:
        raise AnnotationWriteError(
            "gene rows were not readable back after insert: " + ", ".join(sorted(missing)[:5])
        )

    transcript_rows = [
        {
            "id": transcript_id,
            "gene_id": gene_pks[draft.gene_id],
            "is_canonical": False,
            "name": draft.name,
            "biotype": draft.biotype,
            "start": draft.start,
            "end": draft.end,
            "strand": draft.strand,
        }
        for transcript_id, draft in transcript_drafts.items()
    ]
    for offset in range(0, len(transcript_rows), batch_size):
        session.execute(insert(transcripts), transcript_rows[offset : offset + batch_size])

    part_rows: list[dict[str, Any]] = []
    exon_rows: list[dict[str, Any]] = []
    for transcript_id, draft in transcript_drafts.items():
        for order, (part_type, start, end) in enumerate(draft.parts):
            part_rows.append(
                {
                    "transcript_id": transcript_id,
                    "part_type": part_type,
                    "start": start,
                    "end": end,
                    "order": order,
                }
            )
        for order, (start, end) in enumerate(draft.exon_spans()):
            exon_rows.append(
                {"transcript_id": transcript_id, "start": start, "end": end, "order": order}
            )

    for offset in range(0, len(part_rows), batch_size):
        session.execute(insert(transcript_parts), part_rows[offset : offset + batch_size])
    for offset in range(0, len(exon_rows), batch_size):
        session.execute(insert(exons), exon_rows[offset : offset + batch_size])
    session.flush()

    return Gff3WriteReport(
        genes=len(gene_rows),
        transcripts=len(transcript_rows),
        parts=len(part_rows),
        exons=len(exon_rows),
        replaced_genes=len(existing),
    )


def assembly_gene_count(session: Session, assembly_id: int) -> int:
    """How many genes the assembly actually holds — never a parsed row count."""
    return int(
        session.execute(
            select(func.count()).select_from(genes).where(genes.c.assembly_id == assembly_id)
        ).scalar_one()
    )


__all__ = [
    "AnnotationWriteError",
    "DEFAULT_BATCH_SIZE",
    "FastaWriteReport",
    "Gff3WriteReport",
    "PART_TYPES",
    "TRANSCRIPT_TYPES",
    "assembly_gene_count",
    "parse_fai",
    "parse_gff3_attributes",
    "write_gff3_annotation",
    "write_reference_fai",
]
