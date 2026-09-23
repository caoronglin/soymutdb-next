"""Import adapters for published data-set kinds.

Adapters without a persistence writer remain registered so queued work fails
with an explicit, auditable error instead of being reported as successfully
inserted.
"""

from __future__ import annotations

import hashlib
import hmac
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
    """Record a SHA-256 while the existing bounded parser consumes a source."""

    def __init__(self, source: Any) -> None:
        self._source = source
        self._digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            raise ValueError("module checksum calculation requires bounded reads")
        chunk = self._source.read(size)
        if not isinstance(chunk, bytes):
            raise ValueError("module stream must yield bytes")
        self._digest.update(chunk)
        return chunk

    @property
    def checksum_sha256(self) -> str:
        return self._digest.hexdigest()


def _verify_module_checksum(context: ImportContext, actual: str) -> bool:
    """Verify an optional caller declaration against the streamed object bytes."""
    if context.checksum is None:
        return False
    expected = context.checksum.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("module checksum must be a SHA-256 hex digest")
    if not hmac.compare_digest(expected, actual):
        raise ValueError("module source checksum mismatch")
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
    """Open a module source without downloading or reading it all at once."""
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
        checksum_verified = _verify_module_checksum(context, checksum)
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
            checksum_verified = _verify_module_checksum(context, checksum)

            if diagnostics:
                raise ValueError(
                    "module validation failed: "
                    + "; ".join(diagnostics[:5])
                    + (f" (+{len(diagnostics) - 5} more)" if len(diagnostics) > 5 else "")
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
                    },
                    manifest={
                        "module_key": context.module_key,
                        "release_id": release_id,
                        "filename": filename,
                        "checksum": checksum,
                        "checksum_verified": checksum_verified,
                        "row_count": rows_seen,
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
    "expression_csv": UnsupportedCsvAdapter("expression_csv"),
    "homolog_csv": UnsupportedCsvAdapter("homolog_csv"),
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
