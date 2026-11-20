"""SeqFetch service – extract genomic sequences by gene ID or region.

Storage scheme (see ``assemblies.fasta_url`` / ``assemblies.fai_url``)
-----------------------------------------------------------------------
Reference sequence data lives **outside PostgreSQL**: the ``assemblies``
table stores a genome FASTA path (``fasta_url``) plus a samtools ``faidx``
index path (``fai_url``), each either ``s3://bucket/key`` or an ``https://``
URL.  There is no sequence column on the gene models.

Extraction uses the same trick as ``samtools faidx``: the ``.fai`` file maps
chromosome names to the byte offset of the first base in the FASTA file and
records the per-line layout (``linebases`` / ``linewidth``).  A 1-based
coordinate interval is converted into a byte range and fetched with a single
ranged GET (S3 ``Range`` / HTTP ``Range`` header); newlines are stripped from
the returned block, which is guaranteed to start/end on base characters.

Results whose FASTA payload would exceed :data:`MAX_INLINE_BYTES` (10 MiB)
are uploaded to the analyses bucket under ``seqfetch/`` and returned as a
pre-signed download URL instead of an inline body.

Every I/O helper is a module-level function so tests can mock the FASTA /
FAI / upload layers without touching the orchestration logic.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.exceptions import ValidationError
from ..models.genomic import Assembly, Chromosome, Gene
from ..schemas.seqfetch import SeqFetchRequest, SeqFetchResponse
from ..utils.s3 import get_s3_client, parse_s3_path

settings = get_settings()

#: Hard ceiling for a single batch request.
MAX_GENES: int = 200
#: Inline FASTA size cap – larger results are delivered as a file.
MAX_INLINE_BYTES: int = 10 * 1024 * 1024
#: Per-interval extraction cap (bp) to keep ranged reads bounded.
MAX_REGION_BP: int = 1_000_000
#: Object-key namespace for SeqFetch result files (``seqfetch/...``).
SEQFETCH_PREFIX: str = "seqfetch"
#: Result-file lifetime for pre-signed download URLs (seconds).
SEQFETCH_EXPIRES_IN: int = 600
#: Chromosome names follow the actual assembly naming (chr1, chr1A, Gm01, …),
#: so the pattern is deliberately loose: name + 1-based inclusive interval.
_REGION_RE = re.compile(r"^([A-Za-z0-9_.]+):(\d+)-(\d+)$")


# ---------------------------------------------------------------------------
# FAI index helpers (pure functions)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FaiRecord:
    """One chromosome entry from a samtools ``.fai`` file."""

    name: str
    length: int
    offset: int
    linebases: int
    linewidth: int


def parse_fai(text: str | bytes) -> dict[str, FaiRecord]:
    """Parse samtools faidx text into ``{chromosome_name: FaiRecord}``.

    FAI line format: ``name<TAB>length<TAB>offset<TAB>linebases<TAB>linewidth``.
    Malformed lines are skipped so a truncated index degrades gracefully.
    """
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    records: dict[str, FaiRecord] = {}
    for line in text.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 5:
            continue
        name, length, offset, linebases, linewidth = parts[:5]
        try:
            records[name] = FaiRecord(
                name=name,
                length=int(length),
                offset=int(offset),
                linebases=int(linebases),
                linewidth=int(linewidth),
            )
        except ValueError:
            continue
    return records


def fai_byte_range(rec: FaiRecord, start: int, end: int) -> tuple[int, int]:
    """Convert a 1-based inclusive interval into a FASTA byte range.

    Sequence position ``i`` (0-based) sits at file byte
    ``offset + (i // linebases) * linewidth + (i % linebases)`` – the same
    arithmetic ``samtools faidx`` uses.  Returns an inclusive ``(start, end)``
    byte range; the returned block may contain newline bytes between bases.
    """
    pos0 = start - 1
    pos1 = end - 1
    b_start = rec.offset + (pos0 // rec.linebases) * rec.linewidth + (pos0 % rec.linebases)
    b_end = rec.offset + (pos1 // rec.linebases) * rec.linewidth + (pos1 % rec.linebases)
    return b_start, b_end


# ---------------------------------------------------------------------------
# I/O helpers (mockable)
# ---------------------------------------------------------------------------


def read_bytes(path: str, byte_range: tuple[int, int] | None = None) -> bytes:
    """Read *path*, optionally with a byte range.

    Three storage shapes are supported, because the same column carries all of
    them: ``s3://bucket/key`` (the deployed layout), an ``https://`` URL, and a
    local filesystem path -- either absolute (``/data/genome.fa``) or
    ``file:///data/genome.fa``. Local paths matter for the workstation and
    single-host deployments, where the reference genome is a mounted file of
    over a gigabyte; ``seek``+``read`` gives the same bounded read a ranged GET
    does, without loading the file.

    Synchronous boto3 / httpx / file reads are the established pattern in this
    API (see ``app.utils.s3`` and ``app.services.presign``).
    """
    if byte_range is not None:
        b_start, b_end = byte_range
        range_header = f"bytes={b_start}-{b_end}"
    else:
        range_header = None

    if "://" not in path or path.startswith("file://"):
        local_path = path.removeprefix("file://")
        if byte_range is None:
            with open(local_path, "rb") as handle:
                return handle.read()
        local_start, local_end = byte_range
        with open(local_path, "rb") as handle:
            handle.seek(local_start)
            return handle.read(local_end - local_start + 1)

    if path.startswith("s3://"):
        s3 = get_s3_client()
        bucket, key = parse_s3_path(path)
        params: dict[str, Any] = {"Bucket": bucket, "Key": key}
        if range_header is not None:
            params["Range"] = range_header
        body = s3.get_object(**params)["Body"]
        try:
            return bytes(body.read())
        finally:
            body.close()

    response = httpx.get(
        path,
        headers={"Range": range_header} if range_header else None,
        timeout=settings.api_timeout_file_transfer,
    )
    response.raise_for_status()
    return response.content


def _strip_newlines(block: bytes) -> str:
    """Drop FASTA line-wrapping bytes from a ranged block."""
    return (
        block.replace(b"\r\n", b"\n")
        .replace(b"\n", b"")
        .replace(b"\r", b"")
        .decode("ascii", errors="replace")
    )


def slice_fasta(rec: FaiRecord, fasta_path: str, start: int, end: int) -> str:
    """Extract the 1-based inclusive ``[start, end]`` sequence from a FASTA.

    Reads exactly the byte range covering the interval (including any
    wrapped lines inside it) and strips newlines – the block starts at the
    first requested base and ends at the last one, so no trimming is needed.
    """
    length = end - start + 1
    block = read_bytes(fasta_path, fai_byte_range(rec, start, end))
    sequence = _strip_newlines(block)
    return sequence[:length]


def _format_fasta(records: list[tuple[str, str]]) -> str:
    """Join ``(header, sequence)`` pairs into FASTA text."""
    return "".join(f">{header}\n{sequence}\n" for header, sequence in records)


def _upload_result_file(fasta_text: str) -> str:
    """Store a large FASTA payload in S3 and return a pre-signed GET URL."""
    s3 = get_s3_client()
    bucket = settings.s3_analyses_bucket
    object_key = f"{SEQFETCH_PREFIX}/{uuid.uuid4()}.fa"
    s3.put_object(Bucket=bucket, Key=object_key, Body=fasta_text.encode("utf-8"))
    return str(
        s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": object_key},
            ExpiresIn=SEQFETCH_EXPIRES_IN,
        )
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SeqFetchService:
    """Orchestrates DB lookups + FASTA slicing for the SeqFetch tool."""

    async def extract(
        self,
        db: AsyncSession,
        request: SeqFetchRequest,
        *,
        release_id: int | None = None,
    ) -> SeqFetchResponse:
        if request.genes is not None:
            assert request.assembly is not None
            return await self._extract_by_genes(
                db, request.genes, request.assembly, release_id=release_id
            )
        assert request.assembly is not None and request.region is not None
        return await self._extract_by_region(
            db, request.assembly, request.region, release_id=release_id
        )

    # ------------------------------------------------------------------ #
    # Genes mode
    # ------------------------------------------------------------------ #

    async def _extract_by_genes(
        self,
        db: AsyncSession,
        gene_ids: list[str],
        assembly_name: str,
        *,
        release_id: int | None = None,
    ) -> SeqFetchResponse:
        if not gene_ids:
            raise ValidationError("'genes' must contain at least one gene ID")
        if len(gene_ids) > MAX_GENES:
            raise ValidationError(f"'genes' accepts at most {MAX_GENES} IDs")

        assembly_stmt = select(Assembly).where(Assembly.name == assembly_name)
        if release_id is not None:
            assembly_stmt = assembly_stmt.where(Assembly.release_id == release_id)
        assembly_result = await db.execute(assembly_stmt)
        assembly_context = assembly_result.scalar_one_or_none()
        if assembly_context is None:
            raise ValidationError(f"Unknown assembly '{assembly_name}'")

        result = await db.execute(
            select(Gene).where(
                Gene.assembly_id == assembly_context.id,
                Gene.accession.in_(gene_ids),
            )
        )
        found = {g.accession: g for g in result.scalars().all()}

        missing = [gid for gid in gene_ids if gid not in found]
        records: list[tuple[str, str]] = []
        for gid in gene_ids:
            gene = found.get(gid)
            if gene is None:
                continue
            chromosome = gene.chromosome  # lazy="joined"
            assembly = gene.assembly  # lazy="joined"
            if chromosome is None or assembly is None:
                missing.append(gid)
                continue
            if not assembly.fasta_url or not assembly.fai_url:
                missing.append(gid)
                continue
            fasta_path = assembly.fasta_url
            index = parse_fai(read_bytes(assembly.fai_url))
            rec = index.get(chromosome.name)
            if rec is None:
                missing.append(gid)
                continue
            start, end = gene.start, gene.end
            if start < 1 or end > rec.length or end < start:
                missing.append(gid)
                continue
            sequence = slice_fasta(rec, fasta_path, start, end)
            records.append((f"{gid} assembly={assembly_name}", sequence))

        return self._build_response(records, missing=missing)

    # ------------------------------------------------------------------ #
    # Region mode
    # ------------------------------------------------------------------ #

    async def _extract_by_region(
        self,
        db: AsyncSession,
        assembly_name: str,
        region: str,
        *,
        release_id: int | None = None,
    ) -> SeqFetchResponse:
        chromosome_name, start, end = self._parse_region(region)

        assembly_stmt = select(Assembly).where(Assembly.name == assembly_name)
        if release_id is not None:
            assembly_stmt = assembly_stmt.where(Assembly.release_id == release_id)
        result = await db.execute(assembly_stmt)
        assembly = result.scalar_one_or_none()
        if assembly is None:
            raise ValidationError(f"Unknown assembly '{assembly_name}'")
        if not assembly.fasta_url or not assembly.fai_url:
            raise ValidationError(f"Assembly '{assembly_name}' has no sequence files configured")

        chrom_result = await db.execute(
            select(Chromosome).where(
                Chromosome.assembly_id == assembly.id,
                Chromosome.name == chromosome_name,
            )
        )
        chromosome = chrom_result.scalar_one_or_none()
        if chromosome is None:
            raise ValidationError(
                f"Chromosome '{chromosome_name}' not found in assembly '{assembly_name}'"
            )

        if end - start + 1 > MAX_REGION_BP:
            raise ValidationError(f"Region exceeds the {MAX_REGION_BP} bp extraction limit")
        if start < 1 or end > chromosome.length:
            raise ValidationError(
                f"Region out of bounds for '{chromosome_name}' (length {chromosome.length})"
            )

        index = parse_fai(read_bytes(assembly.fai_url))
        rec = index.get(chromosome_name)
        if rec is None:
            raise ValidationError(f"Chromosome '{chromosome_name}' missing from FASTA index")
        sequence = slice_fasta(rec, assembly.fasta_url, start, end)
        return self._build_response(
            [(f"{assembly_name}:{chromosome_name}:{start}-{end}", sequence)]
        )

    # ------------------------------------------------------------------ #
    # Shared response assembly
    # ------------------------------------------------------------------ #

    def _build_response(
        self,
        records: list[tuple[str, str]],
        missing: list[str] | None = None,
    ) -> SeqFetchResponse:
        fasta_text = _format_fasta(records)
        too_large = len(fasta_text.encode("utf-8")) > MAX_INLINE_BYTES
        if too_large:
            return SeqFetchResponse(
                count=len(records),
                truncated=True,
                missing=missing or [],
                download_url=_upload_result_file(fasta_text),
                expires_in=SEQFETCH_EXPIRES_IN,
            )
        return SeqFetchResponse(
            sequence=fasta_text,
            count=len(records),
            truncated=False,
            missing=missing or [],
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_region(region: str) -> tuple[str, int, int]:
        """Parse ``chr:start-end`` (1-based inclusive) into its parts."""
        match = _REGION_RE.match(region.strip())
        if match is None:
            raise ValidationError("region must match 'chr:start-end' (e.g. 'chr1:1000-2000')")
        chromosome_name, start_s, end_s = match.groups()
        start, end = int(start_s), int(end_s)
        if end < start:
            raise ValidationError("region end must be >= start")
        return chromosome_name, start, end


__all__ = [
    "FaiRecord",
    "MAX_GENES",
    "MAX_INLINE_BYTES",
    "MAX_REGION_BP",
    "SEQFETCH_EXPIRES_IN",
    "SEQFETCH_PREFIX",
    "SeqFetchService",
    "fai_byte_range",
    "parse_fai",
    "read_bytes",
    "slice_fasta",
]
