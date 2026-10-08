"""Import normalized GO/KEGG TSV snapshots into an immutable release scope."""

from __future__ import annotations

import csv
import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TextIO
from urllib.parse import urlsplit

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.content import Release, ReleaseStatus
from ..models.gene_annotation import GeneAnnotation, GeneAnnotationSet
from ..models.genomic import Assembly, Gene

ANNOTATION_IMPORTER_VERSION = "1"
ANNOTATION_BATCH_SIZE = 1_000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_COLUMNS = {"gene_id", "term_id", "term_name"}
_OPTIONAL_COLUMNS = {"ontology", "evidence_code", "reference", "qualifier"}


class GeneAnnotationImportError(ValueError):
    """Raised when an annotation snapshot is malformed or unsafe to import."""


@dataclass(frozen=True, slots=True)
class ParsedGeneAnnotation:
    """One normalized annotation row, retaining its source line for errors."""

    line_number: int
    gene_id: str
    term_id: str
    term_name: str
    evidence_code: str
    reference: str
    qualifier: str


@dataclass(frozen=True, slots=True)
class GeneAnnotationImportResult:
    """Summary of a successful or idempotently repeated import."""

    annotation_set_id: int
    row_count: int
    source_sha256: str
    already_imported: bool


def iter_gene_annotation_tsv(
    stream: TextIO,
    *,
    ontology: str,
) -> Iterator[ParsedGeneAnnotation]:
    """Parse the documented normalized TSV shape and reject ambiguous rows.

    Required headers are ``gene_id``, ``term_id``, and ``term_name``. Optional
    headers are ``ontology``, ``evidence_code``, ``reference``, and
    ``qualifier``. Exact duplicate evidence rows are collapsed; conflicting
    display names for the same term are rejected.
    """
    normalized_ontology = ontology.strip().lower()
    if normalized_ontology not in {"go", "kegg"}:
        raise GeneAnnotationImportError("ontology must be 'go' or 'kegg'")

    reader = csv.DictReader(stream, delimiter="\t", strict=True)
    if not reader.fieldnames:
        raise GeneAnnotationImportError("TSV header is missing")

    normalized_headers = [header.strip().lower() for header in reader.fieldnames]
    if len(set(normalized_headers)) != len(normalized_headers):
        raise GeneAnnotationImportError("TSV has duplicate column names")
    missing = sorted(_REQUIRED_COLUMNS - set(normalized_headers))
    if missing:
        raise GeneAnnotationImportError(
            f"TSV is missing required columns: {', '.join(missing)}"
        )
    unsupported = sorted(set(normalized_headers) - _REQUIRED_COLUMNS - _OPTIONAL_COLUMNS)
    if unsupported:
        raise GeneAnnotationImportError(
            f"TSV has unsupported columns: {', '.join(unsupported)}"
        )

    header_by_original = dict(zip(reader.fieldnames, normalized_headers))
    term_names: dict[str, str] = {}
    seen_rows: set[tuple[str, str, str, str, str]] = set()
    parsed_rows = 0

    for raw_row in reader:
        line_number = reader.line_num
        if None in raw_row:
            raise GeneAnnotationImportError(
                f"line {line_number}: row contains more values than the header"
            )
        row = {
            header_by_original[header]: (value or "").strip()
            for header, value in raw_row.items()
            if header is not None
        }
        if not any(row.values()):
            continue

        row_ontology = row.get("ontology", normalized_ontology).lower()
        if row_ontology != normalized_ontology:
            raise GeneAnnotationImportError(
                f"line {line_number}: ontology {row_ontology!r} does not match "
                f"the requested {normalized_ontology!r} import"
            )

        gene_id = row.get("gene_id", "")
        term_id = row.get("term_id", "")
        term_name = row.get("term_name", "") or term_id
        evidence_code = row.get("evidence_code", "")
        reference = row.get("reference", "")
        qualifier = row.get("qualifier", "")
        if not gene_id or not term_id:
            raise GeneAnnotationImportError(
                f"line {line_number}: gene_id and term_id must not be blank"
            )
        for field_name, value, max_length in (
            ("gene_id", gene_id, 64),
            ("term_id", term_id, 128),
            ("term_name", term_name, 512),
            ("evidence_code", evidence_code, 32),
            ("reference", reference, 512),
            ("qualifier", qualifier, 128),
        ):
            if len(value) > max_length:
                raise GeneAnnotationImportError(
                    f"line {line_number}: {field_name} exceeds {max_length} characters"
                )

        previous_name = term_names.setdefault(term_id, term_name)
        if previous_name != term_name:
            raise GeneAnnotationImportError(
                f"line {line_number}: term {term_id!r} has conflicting names"
            )

        row_key = (gene_id, term_id, evidence_code, reference, qualifier)
        if row_key in seen_rows:
            continue
        seen_rows.add(row_key)
        parsed_rows += 1
        yield ParsedGeneAnnotation(
            line_number=line_number,
            gene_id=gene_id,
            term_id=term_id,
            term_name=term_name,
            evidence_code=evidence_code,
            reference=reference,
            qualifier=qualifier,
        )

    if parsed_rows == 0:
        raise GeneAnnotationImportError("TSV contains no annotation rows")


def _validate_source(
    *,
    source_name: str,
    source_version: str,
    source_url: str,
    source_sha256: str,
) -> tuple[str, str, str, str]:
    name = source_name.strip()
    version = source_version.strip()
    url = source_url.strip()
    digest = source_sha256.strip().lower()
    if not name or len(name) > 256:
        raise GeneAnnotationImportError("source_name must contain 1-256 characters")
    if not version or len(version) > 128:
        raise GeneAnnotationImportError("source_version must contain 1-128 characters")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.netloc
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or len(url) > 2_048
    ):
        raise GeneAnnotationImportError(
            "source_url must be a public HTTPS URL without credentials, query, or fragment"
        )
    if not _SHA256_RE.fullmatch(digest):
        raise GeneAnnotationImportError("source_sha256 must be a 64-character SHA-256 hex digest")
    return name, version, url, digest


async def import_gene_annotation_tsv(
    db: AsyncSession,
    stream: TextIO,
    *,
    release_id: int,
    assembly_id: int,
    ontology: str,
    source_name: str,
    source_version: str,
    source_url: str,
    source_sha256: str,
) -> GeneAnnotationImportResult:
    """Import one immutable source snapshot for a draft release.

    The caller owns the outer transaction. The nested transaction ensures a
    malformed file or unknown assembly gene cannot leave a partial snapshot.
    A release/assembly/ontology tuple accepts only one snapshot; changed
    annotations require a new release so published results stay reproducible.
    """
    normalized_ontology = ontology.strip().lower()
    if normalized_ontology not in {"go", "kegg"}:
        raise GeneAnnotationImportError("ontology must be 'go' or 'kegg'")
    name, version, url, digest = _validate_source(
        source_name=source_name,
        source_version=source_version,
        source_url=source_url,
        source_sha256=source_sha256,
    )

    async with db.begin_nested():
        lock_identity = f"{release_id}:{assembly_id}:{normalized_ontology}"
        lock_key = int.from_bytes(
            hashlib.sha256(lock_identity.encode("utf-8")).digest()[:8],
            byteorder="big",
            signed=True,
        )
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key}
        )

        release = await db.scalar(
            select(Release).where(Release.id == release_id).with_for_update()
        )
        if release is None:
            raise GeneAnnotationImportError(f"release {release_id} does not exist")
        release_status = getattr(release.status, "value", release.status)
        if release_status != ReleaseStatus.DRAFT.value:
            raise GeneAnnotationImportError(
                "annotation imports are allowed only for draft releases"
            )

        assembly_exists = await db.scalar(
            select(Assembly.id).where(
                Assembly.id == assembly_id,
                Assembly.release_id == release_id,
            )
        )
        if assembly_exists is None:
            raise GeneAnnotationImportError(
                f"assembly {assembly_id} does not belong to release {release_id}"
            )

        existing = await db.scalar(
            select(GeneAnnotationSet)
            .where(
                GeneAnnotationSet.release_id == release_id,
                GeneAnnotationSet.assembly_id == assembly_id,
                GeneAnnotationSet.ontology == normalized_ontology,
            )
            .with_for_update()
        )
        if existing is not None:
            if (
                existing.source_sha256 == digest
                and existing.source_name == name
                and existing.source_version == version
                and existing.source_url == url
            ):
                actual_rows = await db.scalar(
                    select(func.count()).select_from(GeneAnnotation).where(
                        GeneAnnotation.annotation_set_id == existing.id
                    )
                )
                if actual_rows != existing.row_count:
                    raise GeneAnnotationImportError(
                        "existing annotation snapshot row_count does not match stored rows"
                    )
                return GeneAnnotationImportResult(
                    annotation_set_id=existing.id,
                    row_count=existing.row_count,
                    source_sha256=digest,
                    already_imported=True,
                )
            raise GeneAnnotationImportError(
                "this release/assembly/ontology already has a different annotation snapshot; "
                "create a new release to preserve provenance"
            )

        annotation_set = GeneAnnotationSet(
            release_id=release_id,
            assembly_id=assembly_id,
            ontology=normalized_ontology,
            source_name=name,
            source_version=version,
            source_url=url,
            source_sha256=digest,
            importer_version=ANNOTATION_IMPORTER_VERSION,
            # A nonzero staging value satisfies the table invariant. It is
            # replaced with the real count before the nested transaction exits.
            row_count=1,
        )
        db.add(annotation_set)
        await db.flush()

        parsed_rows = iter_gene_annotation_tsv(stream, ontology=normalized_ontology)
        batch: list[ParsedGeneAnnotation] = []
        row_count = 0
        for parsed in parsed_rows:
            batch.append(parsed)
            if len(batch) >= ANNOTATION_BATCH_SIZE:
                await _insert_batch(
                    db,
                    batch,
                    annotation_set=annotation_set,
                    assembly_id=assembly_id,
                    release_id=release_id,
                    ontology=normalized_ontology,
                )
                row_count += len(batch)
                batch.clear()
        if batch:
            await _insert_batch(
                db,
                batch,
                annotation_set=annotation_set,
                assembly_id=assembly_id,
                release_id=release_id,
                ontology=normalized_ontology,
            )
            row_count += len(batch)

        actual_rows = await db.scalar(
            select(func.count()).select_from(GeneAnnotation).where(
                GeneAnnotation.annotation_set_id == annotation_set.id
            )
        )
        if actual_rows != row_count:
            raise GeneAnnotationImportError("annotation row_count does not match stored rows")
        annotation_set.row_count = row_count
        await db.flush()
        return GeneAnnotationImportResult(
            annotation_set_id=annotation_set.id,
            row_count=row_count,
            source_sha256=digest,
            already_imported=False,
        )


async def _insert_batch(
    db: AsyncSession,
    rows: list[ParsedGeneAnnotation],
    *,
    annotation_set: GeneAnnotationSet,
    assembly_id: int,
    release_id: int,
    ontology: str,
) -> None:
    accessions = {row.gene_id for row in rows}
    known_result = await db.execute(
        select(Gene.accession).where(
            Gene.assembly_id == assembly_id,
            Gene.accession.in_(accessions),
        )
    )
    known_accessions = set(known_result.scalars().all())
    unknown = sorted(accessions - known_accessions)
    if unknown:
        raise GeneAnnotationImportError(
            "annotation contains gene IDs absent from the selected assembly: "
            + ", ".join(unknown[:10])
        )

    await db.execute(
        GeneAnnotation.__table__.insert(),
        [
            {
                "annotation_set_id": annotation_set.id,
                "assembly_id": assembly_id,
                "release_id": release_id,
                "ontology": ontology,
                "gene_id": row.gene_id,
                "term_id": row.term_id,
                "term_name": row.term_name,
                "evidence_code": row.evidence_code,
                "reference": row.reference,
                "qualifier": row.qualifier,
            }
            for row in rows
        ],
    )


__all__ = [
    "ANNOTATION_BATCH_SIZE",
    "ANNOTATION_IMPORTER_VERSION",
    "GeneAnnotationImportError",
    "GeneAnnotationImportResult",
    "ParsedGeneAnnotation",
    "import_gene_annotation_tsv",
    "iter_gene_annotation_tsv",
]
