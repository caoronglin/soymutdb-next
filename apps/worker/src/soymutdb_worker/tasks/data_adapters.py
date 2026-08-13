"""Small, idempotent adapters for the seven published data-set kinds."""

from __future__ import annotations

import csv
import hashlib
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ProgressCallback = Callable[..., Any]


@dataclass(frozen=True)
class ImportContext:
    import_task_id: int
    data_set_id: int
    release_id: str
    file_key: str
    assembly: str | None = None


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
        records = 0
        lengths: dict[str, int] = {}
        current = None
        for line in _path(context).read_text().splitlines():
            if line.startswith(">"):
                current = line[1:].split()[0]
                records += 1
                lengths[current] = 0
            elif current:
                lengths[current] += len(line.strip())
        index = str(_path(context)) + ".fai"
        Path(index).write_text(
            "\n".join(f"{name}\t{length}" for name, length in lengths.items()) + "\n"
        )
        _progress(progress, processed=records, progress=100)
        return AdapterResult(
            records, records, 0,
            {"assembly": context.assembly, "chromosomes": lengths, "index": index},
        )


class Gff3Adapter(_TextAdapter):
    kind = "gff3"

    def run(self, context: ImportContext, *, progress=None) -> AdapterResult:
        counts = {"genes": 0, "transcripts": 0, "exons": 0, "aliases": 0}
        with _path(context).open() as handle:
            for row in csv.reader(handle, delimiter="\t"):
                if len(row) < 9 or not row or row[0].startswith("#"):
                    continue
                feature = row[2].lower()
                if feature == "gene":
                    counts["genes"] += 1
                elif feature in {"mrna", "transcript"}:
                    counts["transcripts"] += 1
                elif feature == "exon":
                    counts["exons"] += 1
                if "alias=" in row[8].lower():
                    counts["aliases"] += 1
        total = sum(counts.values())
        _progress(progress, processed=total, progress=100)
        return AdapterResult(total, total, 0, {"assembly": context.assembly, **counts})


class VcfAdapter:
    kind = "vcf"

    def validate(self, context):
        return {"file": context.file_key}

    def run(self, context, *, progress=None):
        from . import ingest

        value = ingest.import_vcf.run(
            context.release_id, context.file_key, context.assembly or ""
        )
        result = AdapterResult(
            value.get("total_variants", 0), value.get("total_inserted", 0),
            value.get("skipped", 0), value,
        )
        _progress(progress, processed=result.records, progress=100)
        return result


class BlastDbAdapter(_TextAdapter):
    kind = "blast_db"

    def run(self, context, *, progress=None):
        executable = shutil.which("makeblastdb")
        if not executable:
            raise RuntimeError("makeblastdb is required for blast_db imports")
        output = str(_path(context).with_suffix(""))
        subprocess.run(
            [executable, "-in", context.file_key, "-dbtype", "nucl", "-out", output],
            check=True,
        )
        evidence = {"database": output, "tool": "makeblastdb"}
        _progress(progress, processed=1, progress=100)
        return AdapterResult(1, 1, 0, evidence)


class CsvUpsertAdapter(_TextAdapter):
    def __init__(self, kind: str): self.kind = kind

    def run(self, context, *, progress=None):
        with _path(context).open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        _progress(progress, processed=len(rows), progress=100)
        return AdapterResult(
            len(rows), len(rows), 0,
            {"identity": "business-key", "rows": len(rows), "on_conflict": "update"},
        )


_ADAPTERS: dict[str, DataAdapter] = {
    "fasta": FastaAdapter(), "gff3": Gff3Adapter(), "vcf": VcfAdapter(),
    "blast_db": BlastDbAdapter(), "seed_data": CsvUpsertAdapter("seed_data"),
    "expression_csv": CsvUpsertAdapter("expression_csv"),
    "homolog_csv": CsvUpsertAdapter("homolog_csv"),
}


def get_adapter(kind: str) -> DataAdapter:
    try:
        return _ADAPTERS[kind]
    except KeyError as exc:
        raise ValueError(f"unsupported import adapter: {kind}") from exc


def registered_kinds() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


__all__ = ["AdapterResult", "ImportContext", "get_adapter", "registered_kinds"]
