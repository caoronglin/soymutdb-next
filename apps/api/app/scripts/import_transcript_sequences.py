"""Load per-transcript residues and pin the assembly's reference genome.

    python -m app.scripts.import_transcript_sequences \
        --assembly-id 1 \
        --cds .deploy/testdata/Gmax_880_Wm82.a6.v1.cds.fa \
        --protein .deploy/testdata/Gmax_880_Wm82.a6.v1.protein.fa \
        --reference-fasta /data/Gmax_880_v6.0.fa \
        --reference-fai /data/Gmax_880_v6.0.fa.fai

Run the GFF3 import (``import_gene_structure``) first: residues hang off
``transcripts.id``, and that importer replaces every transcript of the assembly.

``--cds`` / ``--protein`` fill ``transcript_sequences``. ``--reference-fasta`` /
``--reference-fai`` do something different on purpose: the reference genome is
never stored in the database, so the genomic and transcript molecules are served
by slicing the FASTA through its ``.fai`` offsets. Those flags record where the
file is on the assembly row (``fasta_url`` / ``fai_url``), which is what the
gene detail contract reads. Both must be given together -- a FASTA without an
index cannot be sliced, and an index without a FASTA names nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

from ..core.database import get_session_factory
from ..models import Assembly
from ..services.transcript_sequence_import_service import (
    ResidueFastaError,
    count_residue_records,
    import_transcript_sequences,
)


def _sources(cds: Path | None, protein: Path | None) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    if cds is not None:
        sources["cds"] = cds
    if protein is not None:
        sources["protein"] = protein
    return sources


async def _run(
    assembly_id: int,
    sources: dict[str, Path],
    *,
    reference_fasta: Path | None,
    reference_fai: Path | None,
    dry_run: bool,
    batch_size: int,
) -> int:
    for molecule, path in sources.items():
        if not path.is_file():
            print(f"{molecule} FASTA not found: {path}", file=sys.stderr)
            return 2
    for label, declared in (
        ("reference FASTA", reference_fasta),
        ("reference FAI", reference_fai),
    ):
        if declared is not None and not declared.is_file():
            print(f"{label} not found: {declared}", file=sys.stderr)
            return 2

    if (reference_fasta is None) != (reference_fai is None):
        print(
            "--reference-fasta and --reference-fai must be given together",
            file=sys.stderr,
        )
        return 2

    if dry_run:
        # Parse the files without opening a connection, so a malformed header is
        # reported even when no database is reachable.
        try:
            counts = count_residue_records(sorted(sources.items()))
        except ResidueFastaError as exc:
            print(f"malformed FASTA: {exc}", file=sys.stderr)
            return 2
        for molecule, count in counts.items():
            print(f"dry run    : {molecule}: {count} records")
        return 0

    async with get_session_factory()() as session:
        assembly = (
            await session.execute(select(Assembly).where(Assembly.id == assembly_id))
        ).scalar_one_or_none()
        if assembly is None:
            print(f"no assembly with id {assembly_id}", file=sys.stderr)
            return 2

        print(f"assembly   : {assembly.id} {assembly.name} ({assembly.version})")

        if reference_fasta is not None and reference_fai is not None:
            assembly.fasta_url = str(reference_fasta)
            assembly.fai_url = str(reference_fai)
            print(f"reference  : {assembly.fasta_url}")
            print(f"index      : {assembly.fai_url}")

        try:
            report = await import_transcript_sequences(
                session, assembly_id=assembly_id, sources=sources, batch_size=batch_size
            )
        except ResidueFastaError as exc:
            # Nothing is committed: the whole import is one transaction, so a
            # malformed record leaves the store exactly as it was.
            print(f"malformed FASTA: {exc}", file=sys.stderr)
            return 2
        await session.commit()

    for key, value in report.as_dict().items():
        print(f"  {key:<32} {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assembly-id", type=int, required=True)
    parser.add_argument("--cds", type=Path, default=None, help="CDS FASTA per transcript")
    parser.add_argument("--protein", type=Path, default=None, help="protein FASTA per transcript")
    parser.add_argument("--reference-fasta", type=Path, default=None)
    parser.add_argument("--reference-fai", type=Path, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and count only; never writes and never connects",
    )
    parser.add_argument("--batch-size", type=int, default=5_000)
    args = parser.parse_args(argv)

    sources = _sources(args.cds, args.protein)
    if not sources:
        parser.error("at least one of --cds / --protein is required")
    return asyncio.run(
        _run(
            args.assembly_id,
            sources,
            reference_fasta=args.reference_fasta,
            reference_fai=args.reference_fai,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
