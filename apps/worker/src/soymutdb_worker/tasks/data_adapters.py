"""Import adapters for published data-set kinds.

Adapters without a persistence writer remain registered so queued work fails
with an explicit, auditable error instead of being reported as successfully
inserted.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import hmac
import io
import math
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from soymutdb_worker.config import get_setting
from soymutdb_worker.shared import _ensure_jobs_package

_ensure_jobs_package()

from soymutdb_jobs.module_schema import (  # noqa: E402
    iter_module_rows_from_stream,
    validate_module_file_streaming_from_stream,
)

ProgressCallback = Callable[..., Any]


@dataclass(frozen=True)
class ImportContext:
    import_task_id: int
    data_set_id: int
    release_id: str
    file_key: str
    assembly: str | None = None
    module_key: str | None = None
    schema_version: int | None = None
    checksum: str | None = None
    filename: str | None = None


@dataclass(frozen=True)
class AdapterResult:
    records: int
    inserted: int
    skipped: int
    evidence: dict[str, Any]


class DataAdapter(Protocol):
    kind: str

    def validate(self, context: ImportContext) -> dict[str, Any]: ...

    def run(
        self, context: ImportContext, *, progress: ProgressCallback | None = None
    ) -> AdapterResult: ...


class UnsupportedImportError(RuntimeError):
    """Raised when an import cannot satisfy the pipeline's safety contract."""


class _HashingReader:
    """Record a SHA-256 while the existing bounded parser consumes a source.

    The wrapper implements just enough of the read-only IO protocol for
    ``io.TextIOWrapper`` and ``gzip.GzipFile``; the digest therefore covers
    the bytes actually stored in the object, compressed bytes included.
    """

    def __init__(self, source: Any) -> None:
        self._source = source
        self._digest = hashlib.sha256()
        self._closed = False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            raise ValueError("checksum calculation requires bounded reads")
        chunk = self._source.read(size)
        if not isinstance(chunk, bytes):
            raise ValueError("import stream must yield bytes")
        self._digest.update(chunk)
        return chunk

    def read1(self, size: int = -1) -> bytes:
        return self.read(size)

    def readinto(self, buffer: Any) -> int:
        chunk = self.read(len(buffer))
        buffer[: len(chunk)] = chunk
        return len(chunk)

    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def checksum_sha256(self) -> str:
        return self._digest.hexdigest()


def _verify_source_checksum(context: ImportContext, actual: str) -> bool:
    """Verify an optional caller declaration against the streamed object bytes."""
    if context.checksum is None:
        return False
    expected = context.checksum.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("source checksum must be a SHA-256 hex digest")
    if not hmac.compare_digest(expected, actual):
        raise ValueError("source checksum mismatch")
    return True


def _path(context: ImportContext) -> Path:
    path = Path(context.file_key)
    if not path.exists():
        raise FileNotFoundError(context.file_key)
    return path


def _progress(callback: ProgressCallback | None, **values: Any) -> None:
    if callback:
        callback(**values)


class _TextAdapter:
    kind = ""

    def validate(self, context: ImportContext) -> dict[str, Any]:
        path = _path(context)
        return {"file": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class FastaAdapter(_TextAdapter):
    kind = "fasta"

    def run(self, context: ImportContext, *, progress=None) -> AdapterResult:
        raise UnsupportedImportError(
            "fasta import is disabled: durable persistence writer, artifact upload, "
            "and release registration are not implemented"
        )


class Gff3Adapter(_TextAdapter):
    kind = "gff3"

    def run(self, context: ImportContext, *, progress=None) -> AdapterResult:
        raise UnsupportedImportError(
            "gff3 import is disabled: durable persistence writer and release "
            "registration are not implemented"
        )


class VcfAdapter:
    kind = "vcf"

    def validate(self, context):
        return {"file": context.file_key}

    def run(self, context, *, progress=None) -> AdapterResult:
        """Drive the ADR-0005 staging/verify/finalize protocol for a VCF.

        The durable writer lives in ingest.py, which imports this module at
        load time, so the import is deferred to avoid a module cycle. The
        protocol keeps its own feature gate (SOYMUTDB_ENABLE_VCF_IMPORT,
        default OFF): while the gate is off the import raises the same
        UnsupportedImportError it did before, so the capability remains
        fail-closed (P1-2). With the gate on, this is the real production path
        — enabling the flag is what requires real-ClickHouse acceptance.
        """
        from .ingest import import_vcf

        _progress(progress, progress=5)
        result = import_vcf(context.release_id, context.file_key, context.assembly or "")
        if result.get("status") != "published":
            raise UnsupportedImportError(
                "vcf import did not publish: "
                f"{result.get('reason', 'unknown')} "
                f"(import_id={result.get('import_id')})"
            )
        written = int(result.get("written_rows") or 0)
        _progress(progress, processed=written, total=written, progress=100)
        return AdapterResult(
            records=written,
            inserted=written,
            skipped=0,
            evidence={
                "import_id": result.get("import_id"),
                "written_rows": written,
                "idempotent": bool(result.get("idempotent")),
            },
        )


class BlastDbAdapter(_TextAdapter):
    kind = "blast_db"

    def run(self, context, *, progress=None):
        raise UnsupportedImportError(
            "blast_db import is disabled: durable persistence requires artifact "
            "upload and database registration"
        )


class UnsupportedCsvAdapter(_TextAdapter):
    """Fail closed until a real business-key upsert writer exists."""

    def __init__(self, kind: str):
        self.kind = kind

    def run(self, context, *, progress=None):
        raise UnsupportedImportError(
            f"{self.kind} import is disabled: no persistence writer is implemented; "
            "refusing to report parsed CSV rows as inserted"
        )


@contextmanager
def _open_module_source(context: ImportContext) -> Iterator[Any]:
    """Open a source without downloading or reading it all at once."""
    path = Path(context.file_key)
    if path.exists():
        with path.open("rb") as source:
            yield source
        return

    from soymutdb_worker.utils.s3 import stream_s3_file

    source_key = context.file_key
    # Browser-direct multipart uploads store bare ``data/<dataset>/...``
    # object keys in the configured analyses bucket. Preserve explicit URIs
    # and legacy ``bucket/key`` values so only this platform-owned namespace
    # receives the configured-bucket prefix.
    if source_key.startswith("data/"):
        analyses_bucket = get_setting("S3_ANALYSES_BUCKET", "analyses")
        source_key = f"{analyses_bucket}/{source_key}"

    with stream_s3_file(source_key) as source:
        yield source


@contextmanager
def _open_csv_text(
    context: ImportContext,
) -> Iterator[tuple[_HashingReader, io.TextIOWrapper]]:
    """Yield hashing bytes plus a streaming UTF-8 text view of the source."""
    filename = context.filename or context.file_key
    with _open_module_source(context) as source:
        hashing = _HashingReader(source)
        raw: Any = hashing
        if filename.endswith(".gz"):
            raw = gzip.GzipFile(fileobj=hashing, mode="rb")
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        try:
            yield hashing, text
        finally:
            text.close()


class _RowError(ValueError):
    """A row-level validation failure collected into bounded diagnostics."""


def _is_comment_row(row: dict[Any, Any]) -> bool:
    return any(
        isinstance(value, str) and value.lstrip().startswith("#")
        for value in row.values()
    )


def _cell(row: dict[Any, Any], name: str) -> str:
    value = row.get(name)
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else ""


def _required_text(
    row: dict[Any, Any], name: str, row_number: int, *, max_length: int
) -> str:
    value = _cell(row, name)
    if not value:
        raise _RowError(f"row {row_number}: {name} is required")
    if len(value) > max_length:
        raise _RowError(f"row {row_number}: {name} exceeds {max_length} characters")
    return value


def _optional_text(
    row: dict[Any, Any], name: str, row_number: int, *, max_length: int
) -> str | None:
    value = _cell(row, name)
    if not value:
        return None
    if len(value) > max_length:
        raise _RowError(f"row {row_number}: {name} exceeds {max_length} characters")
    return value


def _optional_float(row: dict[Any, Any], name: str, row_number: int) -> float | None:
    value = _cell(row, name)
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise _RowError(f"row {row_number}: {name} must be a number") from exc
    if not math.isfinite(parsed):
        raise _RowError(f"row {row_number}: {name} must be finite")
    if parsed < 0:
        raise _RowError(f"row {row_number}: {name} must be non-negative")
    return parsed


def _optional_int(
    row: dict[Any, Any], name: str, row_number: int, *, minimum: int | None = None
) -> int | None:
    value = _cell(row, name)
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise _RowError(f"row {row_number}: {name} must be an integer") from exc
    if minimum is not None and parsed < minimum:
        raise _RowError(f"row {row_number}: {name} must be at least {minimum}")
    return parsed


def _required_int(
    row: dict[Any, Any], name: str, row_number: int, *, minimum: int = 1
) -> int:
    parsed = _optional_int(row, name, row_number, minimum=minimum)
    if parsed is None:
        raise _RowError(f"row {row_number}: {name} is required")
    return parsed


class _CsvUpsertAdapter(_TextAdapter):
    """Streaming CSV writer with a transactional, idempotent upsert.

    Subclasses supply the assembly-scoped reference lookups, row validation,
    natural key and PostgreSQL upsert.  The base owns the shared contract:
    explicit assembly, data-set binding, single transaction, streamed checksum
    evidence, bounded diagnostics and fail-closed row handling.
    """

    required_headers: tuple[str, ...] = ()
    batch_size = 10_000
    diagnostic_limit = 200

    def _require_assembly(self, context: ImportContext) -> str:
        assembly = (context.assembly or "").strip()
        if not assembly:
            raise ValueError(f"{self.kind} imports require an explicit assembly")
        return assembly

    def _references(self, session: Any, assembly: str) -> Any:
        raise NotImplementedError

    def _parse_row(
        self, raw: dict[Any, Any], references: Any, row_number: int
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _row_key(self, payload: dict[str, Any]) -> tuple[Any, ...]:
        raise NotImplementedError

    def _upsert(self, session: Any, payloads: list[dict[str, Any]]) -> int:
        raise NotImplementedError

    def _reference_evidence(self, references: Any) -> dict[str, Any]:
        return {}

    def _reader(self, text: io.TextIOWrapper) -> csv.DictReader:
        reader = csv.DictReader(text)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise ValueError(f"{self.kind} import source has no header row")
        normalized = [(name or "").strip() for name in fieldnames]
        missing = [name for name in self.required_headers if name not in normalized]
        if missing:
            raise ValueError(
                f"{self.kind} import is missing required columns: {', '.join(missing)}"
            )
        reader.fieldnames = normalized
        return reader

    def validate(self, context: ImportContext) -> dict[str, Any]:
        assembly = self._require_assembly(context)
        with _open_csv_text(context) as (hashing, text):
            for _raw in self._reader(text):
                pass
            checksum = hashing.checksum_sha256
        return {
            "kind": self.kind,
            "assembly": assembly,
            "checksum": checksum,
            "checksum_verified": _verify_source_checksum(context, checksum),
        }

    def run(self, context: ImportContext, *, progress=None) -> AdapterResult:
        assembly = self._require_assembly(context)
        filename = context.filename or Path(context.file_key).name
        rows_seen = 0
        inserted = 0
        skipped = 0
        duplicates = 0
        diagnostics: list[str] = []
        batch: dict[tuple[Any, ...], dict[str, Any]] = {}
        checksum = ""
        checksum_verified = False

        from sqlalchemy import select

        from soymutdb_worker.tables import data_sets
        from soymutdb_worker.utils.db import get_db

        with get_db() as session:
            # One transaction protects the public view: validation failures
            # and checksum mismatches roll back every batch upsert together.
            data_set_type = session.execute(
                select(data_sets.c.type)
                .where(data_sets.c.id == context.data_set_id)
                .with_for_update()
            ).scalar_one_or_none()
            if data_set_type is None:
                raise ValueError(f"{self.kind} import data set does not exist")
            if data_set_type != self.kind:
                raise ValueError(
                    f"{self.kind} import requires a {self.kind} data set"
                )

            references = self._references(session, assembly)

            with _open_csv_text(context) as (hashing, text):
                reader = self._reader(text)
                for raw in reader:
                    row_number = reader.line_num
                    if _is_comment_row(raw):
                        continue
                    try:
                        payload = self._parse_row(raw, references, row_number)
                    except _RowError as exc:
                        skipped += 1
                        if len(diagnostics) < self.diagnostic_limit:
                            diagnostics.append(str(exc))
                        continue
                    rows_seen += 1
                    key = self._row_key(payload)
                    if key in batch:
                        # PostgreSQL refuses to upsert the same key twice in
                        # one statement; keep the last occurrence explicitly.
                        duplicates += 1
                        batch.pop(key)
                    batch[key] = payload
                    if len(batch) >= self.batch_size:
                        inserted += self._upsert(session, list(batch.values()))
                        batch.clear()
                        _progress(
                            progress, processed=rows_seen, total=rows_seen, progress=0
                        )
                if batch:
                    inserted += self._upsert(session, list(batch.values()))
                checksum = hashing.checksum_sha256

            checksum_verified = _verify_source_checksum(context, checksum)

            if diagnostics:
                raise ValueError(
                    f"{self.kind} validation failed: "
                    + "; ".join(diagnostics[:5])
                    + (f" (+{len(diagnostics) - 5} more)" if len(diagnostics) > 5 else "")
                )

            evidence = {
                "kind": self.kind,
                "assembly": assembly,
                "filename": filename,
                "checksum": checksum,
                "checksum_verified": checksum_verified,
                "rows_seen": rows_seen,
                "rows_inserted": inserted,
                "rows_skipped": skipped,
                "rows_duplicate": duplicates,
                "batch_size": self.batch_size,
                "on_conflict": "upsert",
                **self._reference_evidence(references),
            }
            session.execute(
                data_sets.update()
                .where(data_sets.c.id == context.data_set_id)
                .values(
                    status="ready",
                    validation_evidence=evidence,
                    manifest={
                        "kind": self.kind,
                        "assembly": assembly,
                        "filename": filename,
                        "checksum": checksum,
                        "checksum_verified": checksum_verified,
                        "rows_seen": rows_seen,
                        "rows_inserted": inserted,
                        "rows_skipped": skipped,
                        "rows_duplicate": duplicates,
                    },
                )
            )

        _progress(progress, processed=rows_seen, total=rows_seen, progress=100)
        return AdapterResult(rows_seen, inserted, skipped, evidence)


@dataclass(frozen=True)
class _ExpressionReferences:
    assembly: str
    assembly_id: int
    genes: dict[str, int]
    libraries: dict[int, int]


class ExpressionCsvAdapter(_CsvUpsertAdapter):
    """Durable writer for ``gene_id,library_id,fpkm,tpm,raw_count`` CSV."""

    kind = "expression_csv"
    required_headers = ("gene_id", "library_id")

    def _references(self, session: Any, assembly: str) -> _ExpressionReferences:
        from sqlalchemy import select

        from soymutdb_worker.tables import expression_libraries

        from .gene_resolution import resolve_assembly_id, resolve_gene_accessions

        assembly_id = resolve_assembly_id(session, assembly)
        genes, _ambiguous = resolve_gene_accessions(
            session, assembly=assembly, assembly_id=assembly_id
        )
        libraries = {
            int(library_id): int(library_assembly_id)
            for library_id, library_assembly_id in session.execute(
                select(expression_libraries.c.id, expression_libraries.c.assembly_id)
            ).all()
        }
        return _ExpressionReferences(assembly, assembly_id, genes, libraries)

    def _parse_row(
        self, raw: dict[Any, Any], references: _ExpressionReferences, row_number: int
    ) -> dict[str, Any]:
        accession = _required_text(raw, "gene_id", row_number, max_length=64)
        gene_pk = references.genes.get(accession)
        if gene_pk is None:
            raise _RowError(
                f"row {row_number}: unknown gene accession {accession!r} "
                f"in assembly {references.assembly!r}"
            )
        library_id = _required_int(raw, "library_id", row_number)
        library_assembly = references.libraries.get(library_id)
        if library_assembly is None:
            raise _RowError(
                f"row {row_number}: unknown expression library {library_id}"
            )
        if library_assembly != references.assembly_id:
            raise _RowError(
                f"row {row_number}: expression library {library_id} "
                "belongs to another assembly"
            )
        return {
            "gene_id": gene_pk,
            "library_id": library_id,
            "fpkm": _optional_float(raw, "fpkm", row_number),
            "tpm": _optional_float(raw, "tpm", row_number),
            "raw_count": _optional_int(raw, "raw_count", row_number, minimum=0),
        }

    def _row_key(self, payload: dict[str, Any]) -> tuple[Any, ...]:
        return (payload["gene_id"], payload["library_id"])

    def _upsert(self, session: Any, payloads: list[dict[str, Any]]) -> int:
        if not payloads:
            return 0
        from sqlalchemy import func
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from soymutdb_worker.tables import expression_data

        statement = pg_insert(expression_data)
        statement = statement.on_conflict_do_update(
            constraint="uq_expression_gene_library",
            set_={
                "fpkm": statement.excluded.fpkm,
                "tpm": statement.excluded.tpm,
                "raw_count": statement.excluded.raw_count,
                "updated_at": func.now(),
            },
        )
        session.execute(statement, payloads)
        return len(payloads)

    def _reference_evidence(self, references: _ExpressionReferences) -> dict[str, Any]:
        return {"assembly_id": references.assembly_id}


@dataclass(frozen=True)
class _HomologReferences:
    assembly: str
    assembly_id: int
    genes: dict[str, int]


class HomologCsvAdapter(_CsvUpsertAdapter):
    """Durable writer for homolog relationships (ortholog/paralog) CSV."""

    kind = "homolog_csv"
    required_headers = (
        "gene_id",
        "homolog_species",
        "homolog_gene_id",
        "homolog_type",
    )

    def _references(self, session: Any, assembly: str) -> _HomologReferences:
        from .gene_resolution import resolve_assembly_id, resolve_gene_accessions

        assembly_id = resolve_assembly_id(session, assembly)
        genes, _ambiguous = resolve_gene_accessions(
            session, assembly=assembly, assembly_id=assembly_id
        )
        return _HomologReferences(assembly, assembly_id, genes)

    def _parse_row(
        self, raw: dict[Any, Any], references: _HomologReferences, row_number: int
    ) -> dict[str, Any]:
        accession = _required_text(raw, "gene_id", row_number, max_length=64)
        gene_pk = references.genes.get(accession)
        if gene_pk is None:
            raise _RowError(
                f"row {row_number}: unknown gene accession {accession!r} "
                f"in assembly {references.assembly!r}"
            )
        homolog_type = _required_text(
            raw, "homolog_type", row_number, max_length=16
        ).lower()
        if homolog_type not in {"ortholog", "paralog"}:
            raise _RowError(
                f"row {row_number}: homolog_type must be ortholog or paralog"
            )
        return {
            "gene_id": gene_pk,
            "homolog_species": _required_text(
                raw, "homolog_species", row_number, max_length=128
            ),
            "homolog_gene_id": _required_text(
                raw, "homolog_gene_id", row_number, max_length=64
            ),
            "homolog_type": homolog_type,
            "source": _optional_text(raw, "source", row_number, max_length=128),
        }

    def _row_key(self, payload: dict[str, Any]) -> tuple[Any, ...]:
        return (
            payload["gene_id"],
            payload["homolog_species"],
            payload["homolog_gene_id"],
            payload["homolog_type"],
        )

    def _upsert(self, session: Any, payloads: list[dict[str, Any]]) -> int:
        if not payloads:
            return 0
        from sqlalchemy import func
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from soymutdb_worker.tables import gene_homologs

        statement = pg_insert(gene_homologs)
        statement = statement.on_conflict_do_update(
            constraint="uq_gene_homolog",
            set_={
                "source": statement.excluded.source,
                "updated_at": func.now(),
            },
        )
        session.execute(statement, payloads)
        return len(payloads)

    def _reference_evidence(self, references: _HomologReferences) -> dict[str, Any]:
        return {"assembly_id": references.assembly_id}


def _module_release_id(value: str) -> int:
    """Return a valid module release id before beginning a database write."""
    try:
        release_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("release_id must be a positive integer for module_tsv imports") from exc
    if release_id <= 0:
        raise ValueError("release_id must be a positive integer for module_tsv imports")
    return release_id


def _validate_module_data_object_key(context: ImportContext) -> None:
    """Fail closed for browser-upload keys carried by legacy queue messages.

    New commands are checked by the API. The worker repeats the narrow check
    because an already-enqueued task can outlive an API deployment or state
    transition. Explicit ``s3://`` and legacy bucket/key sources are not
    platform-owned browser keys and keep their existing advanced semantics.
    """
    if not context.file_key.startswith("data/"):
        return

    segments = context.file_key.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError("data object key must not contain traversal segments")
    if not context.file_key.startswith(f"data/{context.data_set_id}/"):
        raise ValueError("data object key does not belong to this data set")


class ModuleTsvAdapter(_TextAdapter):
    kind = "module_tsv"

    def validate(self, context: ImportContext) -> dict[str, Any]:
        _validate_module_data_object_key(context)
        filename = context.filename or str(Path(context.file_key).name)
        with _open_module_source(context) as source:
            hashing_source = _HashingReader(source)
            result = validate_module_file_streaming_from_stream(
                context.module_key or "",
                filename,
                hashing_source,
            )
        if not result.ok:
            raise ValueError(f"TSV validation failed: {result.first_error()}")
        checksum = hashing_source.checksum_sha256
        checksum_verified = _verify_source_checksum(context, checksum)
        return {
            "module_key": context.module_key,
            "rows": result.row_count,
            "checksum": checksum,
            "checksum_verified": checksum_verified,
        }

    def run(self, context: ImportContext, *, progress=None) -> AdapterResult:
        if not context.module_key:
            raise ValueError("module_key is required for module_tsv imports")
        release_id = _module_release_id(context.release_id)
        _validate_module_data_object_key(context)
        filename = context.filename or str(Path(context.file_key).name)
        batch_size = 10_000
        rows_seen = 0
        inserted = 0
        skipped = 0
        diagnostics: list[str] = []
        batch: list[dict[str, Any]] = []
        checksum = ""
        checksum_verified = False

        from sqlalchemy import delete, select

        from soymutdb_worker.tables import data_sets, module_data_rows, releases
        from soymutdb_worker.utils.db import get_db

        def flush_batch(session, values: list[dict[str, Any]]) -> int:
            if not values:
                return 0
            payload = []
            for row in values:
                key_parts = [
                    str(row.get(col, "")) for col in _module_unique_key(context.module_key)
                ]
                payload.append(
                    {
                        "id": uuid.uuid4(),
                        "module_key": context.module_key,
                        "release_id": release_id,
                        "row_key": "\x1f".join(key_parts),
                        "data": row,
                    }
                )
            session.execute(module_data_rows.insert(), payload)
            return len(payload)

        with get_db() as session:
            # A single transaction protects the public view: any validation
            # error raises below and rolls back deletes/inserts together.
            release_status = session.execute(
                select(releases.c.status)
                .where(releases.c.id == release_id)
                .with_for_update()
            ).scalar_one_or_none()
            if getattr(release_status, "value", release_status) != "draft":
                raise ValueError("module_tsv imports require a draft release")
            data_set_binding = session.execute(
                select(data_sets.c.type, data_sets.c.release_id)
                .where(data_sets.c.id == context.data_set_id)
                .with_for_update()
            ).one_or_none()
            if data_set_binding is None:
                raise ValueError("module_tsv import data set does not exist")
            data_set_type, data_set_release_id = data_set_binding
            if data_set_type != "module_tsv":
                raise ValueError("module_tsv import requires a module_tsv data set")
            if data_set_release_id != release_id:
                raise ValueError("module_tsv import data set is not bound to this release")
            session.execute(
                delete(module_data_rows).where(
                    module_data_rows.c.module_key == context.module_key,
                    module_data_rows.c.release_id == release_id,
                )
            )
            with _open_module_source(context) as source:
                hashing_source = _HashingReader(source)
                for typed, error in iter_module_rows_from_stream(
                    context.module_key,
                    filename,
                    hashing_source,
                ):
                    if error is not None:
                        skipped += 1
                        if len(diagnostics) < 200:
                            diagnostics.append(
                                f"row {error.row or '?'}: {error.code}: {error.message}"
                            )
                        continue
                    if typed is None:
                        continue
                    rows_seen += 1
                    batch.append(typed)
                    if len(batch) >= batch_size:
                        inserted += flush_batch(session, batch)
                        batch.clear()
                        _progress(progress, processed=rows_seen, total=rows_seen, progress=0)
            inserted += flush_batch(session, batch)
            checksum = hashing_source.checksum_sha256
            checksum_verified = _verify_source_checksum(context, checksum)

            if diagnostics:
                raise ValueError(
                    "module validation failed: "
                    + "; ".join(diagnostics[:5])
                    + (f" (+{len(diagnostics) - 5} more)" if len(diagnostics) > 5 else "")
                )

            # ADR-0004: promotion runs before the data set is marked ready, in
            # the same transaction, so "staged but not promoted" cannot be
            # committed. An unmapped module_key fails the import closed.
            from .module_promotion import promote_module_rows

            promotion = promote_module_rows(
                session, module_key=context.module_key, release_id=release_id
            )

            session.execute(
                data_sets.update()
                .where(data_sets.c.id == context.data_set_id)
                .values(
                    status="ready",
                    validation_evidence={
                        "module_key": context.module_key,
                        "filename": filename,
                        "checksum": checksum,
                        "checksum_verified": checksum_verified,
                        "row_count": rows_seen,
                        "rows_seen": rows_seen,
                        "rows_inserted": inserted,
                        "rows_skipped": skipped,
                        "promotion": promotion.as_evidence(),
                    },
                    manifest={
                        "module_key": context.module_key,
                        "release_id": release_id,
                        "filename": filename,
                        "checksum": checksum,
                        "checksum_verified": checksum_verified,
                        "row_count": rows_seen,
                        "promotion": promotion.as_evidence(),
                    },
                )
            )

        _progress(progress, processed=rows_seen, total=rows_seen, progress=100)
        return AdapterResult(
            rows_seen,
            inserted,
            skipped,
            {
                "module_key": context.module_key,
                "filename": filename,
                "checksum": checksum,
                "checksum_verified": checksum_verified,
                "rows_seen": rows_seen,
                "rows_inserted": inserted,
                "rows_skipped": skipped,
                "batch_size": batch_size,
                "on_conflict": "replace",
                "promotion": promotion.as_evidence(),
            },
        )


def _module_unique_key(module_key: str) -> tuple[str, ...]:
    from soymutdb_jobs.module_schema import get_schema

    schema = get_schema(module_key)
    if schema is None:
        raise ValueError(f"unknown module schema: {module_key}")
    return schema.unique_key


_ADAPTERS: dict[str, DataAdapter] = {
    "fasta": FastaAdapter(),
    "gff3": Gff3Adapter(),
    "vcf": VcfAdapter(),
    "blast_db": BlastDbAdapter(),
    "seed_data": UnsupportedCsvAdapter("seed_data"),
    "expression_csv": ExpressionCsvAdapter(),
    "homolog_csv": HomologCsvAdapter(),
    "module_tsv": ModuleTsvAdapter(),
}


def get_adapter(kind: str) -> DataAdapter:
    try:
        return _ADAPTERS[kind]
    except KeyError as exc:
        raise ValueError(f"unsupported import adapter: {kind}") from exc


def registered_kinds() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


__all__ = [
    "AdapterResult",
    "ImportContext",
    "UnsupportedImportError",
    "get_adapter",
    "registered_kinds",
]
