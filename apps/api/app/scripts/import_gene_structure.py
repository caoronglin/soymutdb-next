"""Load transcript structure (mRNA / CDS / UTR) from a GFF3 into the catalogue.

    python -m app.scripts.import_gene_structure \
        --gff3 .deploy/testdata/annotations.gff3 --assembly-id 1

The search importer stores gene rows only, so until this runs the schema can
describe where a gene is but not what it contains: ``transcripts`` and ``exons``
stay empty and no table can hold a CDS or a UTR at all. The portal's genome view
has always been able to draw those segments; this is what gives it something to
draw.

Replace-in-place, one transaction: everything already stored for the assembly's
genes is deleted first (``ON DELETE CASCADE`` clears their parts and exons), so
re-running is safe and cannot leave a half-updated mix.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

from ..core.database import get_session_factory
from ..models import Assembly
from ..services.gene_structure_import_service import (
    import_gene_structure,
    parse_structure_features,
    sha256_of_file,
)


async def _run(gff3: Path, assembly_id: int, *, dry_run: bool, batch_size: int) -> int:
    if not gff3.exists():
        print(f"annotation not found: {gff3}", file=sys.stderr)
        return 2

    print(f"annotation : {gff3}  ({sha256_of_file(gff3)[:12]}…)")

    if dry_run:
        # Count the file without opening a connection, so the parse can be
        # checked against the annotation even when no database is reachable.
        transcripts = parts = exons = 0
        for transcript in parse_structure_features(gff3):
            transcripts += 1
            parts += len(transcript.parts)
            exons += len(transcript.exon_spans())
        print(f"dry run    : {transcripts} transcripts, {parts} parts, {exons} exons")
        return 0

    async with get_session_factory()() as session:
        assembly = (
            await session.execute(select(Assembly).where(Assembly.id == assembly_id))
        ).scalar_one_or_none()
        if assembly is None:
            print(f"no assembly with id {assembly_id}", file=sys.stderr)
            return 2

        print(f"assembly   : {assembly.id} {assembly.name} ({assembly.version})")

        report = await import_gene_structure(
            session, gff3, assembly_id=assembly_id, batch_size=batch_size
        )
        await session.commit()

    for key, value in report.as_dict().items():
        print(f"  {key:<26} {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gff3", type=Path, required=True)
    parser.add_argument("--assembly-id", type=int, required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and count only; never writes",
    )
    parser.add_argument("--batch-size", type=int, default=5_000)
    args = parser.parse_args(argv)
    return asyncio.run(
        _run(args.gff3, args.assembly_id, dry_run=args.dry_run, batch_size=args.batch_size)
    )


if __name__ == "__main__":
    raise SystemExit(main())
