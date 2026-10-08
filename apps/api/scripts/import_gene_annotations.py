"""Load a normalized, source-attributed annotation TSV into a draft release."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import BinaryIO

from app.core.database import get_engine, get_session_factory
from app.services.gene_annotation_import_service import (
    GeneAnnotationImportError,
    import_gene_annotation_tsv,
)


class _HashingReader(io.RawIOBase):
    """Hash the exact raw bytes consumed by the TSV parser."""

    def __init__(self, source: BinaryIO) -> None:
        super().__init__()
        self._source = source
        self._digest = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray) -> int:
        chunk = self._source.read(len(buffer))
        if not chunk:
            return 0
        self._digest.update(chunk)
        buffer[: len(chunk)] = chunk
        return len(chunk)

    @property
    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def _sha256_file(source: BinaryIO) -> str:
    digest = hashlib.sha256()
    source.seek(0)
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
    source.seek(0)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Import a normalized gene_id/term_id/term_name TSV into one draft "
            "release and assembly. The import is immutable and source-attributed."
        )
    )
    parser.add_argument("file", type=Path, help="UTF-8 TSV file")
    parser.add_argument("--release-id", type=int, required=True)
    parser.add_argument("--assembly-id", type=int, required=True)
    parser.add_argument("--ontology", choices=("go", "kegg"), required=True)
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument(
        "--source-url",
        required=True,
        help="Public HTTPS page or download URL for this exact annotation release",
    )
    parser.add_argument(
        "--sha256",
        help="Optional expected file SHA-256; import always stores the computed digest",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the same validation and import inside a transaction, then roll back",
    )
    return parser


async def _run(
    args: argparse.Namespace,
    source_binary: BinaryIO,
    source_sha256: str,
) -> dict[str, object]:
    engine = get_engine()
    factory = get_session_factory()
    try:
        async with factory() as db:
            async with db.begin():
                hashing_reader = _HashingReader(source_binary)
                with io.TextIOWrapper(
                    io.BufferedReader(hashing_reader),
                    encoding="utf-8-sig",
                    newline="",
                ) as stream:
                    result = await import_gene_annotation_tsv(
                        db,
                        stream,
                        release_id=args.release_id,
                        assembly_id=args.assembly_id,
                        ontology=args.ontology,
                        source_name=args.source_name,
                        source_version=args.source_version,
                        source_url=args.source_url,
                        source_sha256=source_sha256,
                    )
                    # Idempotent imports return before parsing; still consume
                    # the same descriptor so the digest covers the bytes that
                    # were checked for this invocation.
                    while stream.read(1024 * 1024):
                        pass
                if hashing_reader.hexdigest != source_sha256:
                    raise GeneAnnotationImportError(
                        "input file changed between checksum and import; no rows were committed"
                    )
                if args.dry_run:
                    await db.rollback()
        return {
            "dry_run": args.dry_run,
            "annotation_set_id": result.annotation_set_id,
            "row_count": result.row_count,
            "source_sha256": result.source_sha256,
            "already_imported": result.already_imported,
        }
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.file.is_file():
        _parser().error(f"input file does not exist: {args.file}")
    try:
        with args.file.open("rb") as source_binary:
            computed_sha256 = _sha256_file(source_binary)
            if args.sha256 and args.sha256.strip().lower() != computed_sha256:
                _parser().error("input file SHA-256 does not match --sha256")
            result = asyncio.run(_run(args, source_binary, computed_sha256))
    except (GeneAnnotationImportError, OSError, UnicodeError, ValueError) as exc:
        print(f"annotation import failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
