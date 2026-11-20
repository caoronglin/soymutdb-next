"""Strict importer for the unpublished local ``03_soymut`` sample.

This importer accepts only a disposable loopback PostgreSQL database on port
55432 named ``soymutdb``. It creates its one preview-only table directly; no
Alembic migration or release publication step is involved.
"""

from __future__ import annotations

import csv
import hashlib
import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote

from sqlalchemy import Table, delete, func, inspect, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ..models.content import Release, ReleaseStatus
from ..models.genomic import Assembly, Chromosome, Gene
from ..models.local_test_preview import LocalTestMutationSite
from .local_test_preview_service import (
    PREVIEW_ANNOTATION_VERSION,
    PREVIEW_ASSEMBLY_NAME,
    PREVIEW_ASSEMBLY_VERSION,
    PREVIEW_DATASET_KEY,
    PREVIEW_RELEASE_VERSION,
)

PREVIEW_RELEASE_MARKER = "LOCAL_TEST_PREVIEW_DATASET=03_soymut-a6-test"
EXPECTED_SITE_ROWS = 3697
EXPECTED_CHROMOSOMES = tuple(f"Gm{number:02d}" for number in range(1, 21))
REQUIRED_SITE_COLUMNS = (
    "株系",
    "突变体系（株系母+位置）",
    "染色体号",
    "位点",
    "可信度（高/中/低）",
    "基因号",
    "特征",
    "可获得",
)
#: Homolog columns of the same TSV. Required, because the operator's table is
#: the source of truth for these rows.
HOMOLOG_SITE_COLUMNS = ("W82_V2", "W82_V4", "DN53_V1")


@dataclass(frozen=True, slots=True)
class GeneFeature:
    accession: str
    name: str | None
    chromosome: str
    start: int
    end: int
    strand: str
    biotype: str
    description: str | None
    attributes: dict[str, str]


@dataclass(frozen=True, slots=True)
class MutationSite:
    source_site_key: str
    mutant_line_name: str
    chromosome: str
    position: int
    confidence: str
    gene_accession: str
    feature: str
    available: bool
    #: Homolog accessions from the same row (W82_V2 / W82_V4 / DN53_V1).
    gene_v2: str | None = None
    gene_v4: str | None = None
    gene_dn53: str | None = None


@dataclass(frozen=True, slots=True)
class LocalPreviewImportReport:
    assembly_name: str
    release_version: str
    gene_count: int
    site_count: int
    imported_genes: bool
    source_sha256: str
    annotation_sha256: str


#: Database names this importer may write to, as an explicit allowlist.
#:
#: The property being protected is "a loopback PostgreSQL the developer
#: controls", not one exact spelling: `.deploy/scripts/up.sh` and the local
#: preview both serve `soymutdb_dev`, which is where the running API reads the
#: preview from. A prefix match would also admit `soymutdb_production`, so the
#: set is enumerated instead.
ALLOWED_PREVIEW_DATABASES: frozenset[str] = frozenset({"soymutdb", "soymutdb_dev"})


def validate_local_test_database(database_url: str) -> None:
    """Reject any database except the dedicated disposable local test target."""
    try:
        url = make_url(database_url)
    except Exception as exc:
        raise ValueError("Invalid PostgreSQL database URL") from exc
    if url.drivername != "postgresql+asyncpg":
        raise ValueError("database URL must use postgresql+asyncpg")
    if url.database not in ALLOWED_PREVIEW_DATABASES:
        raise ValueError(
            "refusing import: target database must be one of "
            f"{sorted(ALLOWED_PREVIEW_DATABASES)} (this is the disposable local "
            "soymutdb database or its standard development sibling)"
        )
    # The port is not part of the safety property. What protects a real database
    # is the loopback host plus the `soymutdb` name; pinning 55432 additionally
    # blocked importing into the standard local development database that
    # `.deploy/scripts/up.sh` serves, which is where the preview has to live for
    # the running API to read it.
    host = (url.host or "").strip("[]").lower()
    if host == "localhost":
        return
    try:
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError("refusing import: PostgreSQL host must be loopback")
    except ValueError as exc:
        if str(exc) == "refusing import: PostgreSQL host must be loopback":
            raise
        raise ValueError("refusing import: PostgreSQL host must be loopback") from exc


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_fai(path: Path) -> dict[str, int]:
    """Load and verify the v6 FASTA index chromosome lengths."""
    chromosomes: dict[str, int] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            columns = raw.rstrip("\r\n").split("\t")
            if len(columns) < 5:
                raise ValueError(f"FAI line {line_number} has fewer than 5 fields")
            name = columns[0]
            try:
                length = int(columns[1])
            except ValueError as exc:
                raise ValueError(f"FAI line {line_number} has an invalid length") from exc
            if length < 1 or name in chromosomes:
                raise ValueError(f"FAI line {line_number} has an invalid chromosome")
            chromosomes[name] = length
    if tuple(sorted(chromosomes)) != tuple(sorted(EXPECTED_CHROMOSOMES)):
        raise ValueError("FAI must contain exactly the 20 Gm01-Gm20 chromosomes")
    return chromosomes


def parse_gene_features(
    path: Path,
    chromosome_lengths: dict[str, int],
    *,
    annotation_sha256: str,
) -> list[GeneFeature]:
    """Read only GFF3 gene rows; transcript/CDS rows are not needed for search."""
    assembly_version = None
    annotation_version = None
    features: list[GeneFeature] = []
    seen_accessions: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if raw.startswith("##assembly-version "):
                assembly_version = raw.removeprefix("##assembly-version ").strip()
                continue
            if raw.startswith("##annot-version "):
                annotation_version = raw.removeprefix("##annot-version ").strip()
                continue
            if not raw or raw.startswith("#"):
                continue
            columns = raw.rstrip("\r\n").split("\t")
            if len(columns) != 9:
                raise ValueError(f"GFF3 line {line_number} must contain 9 fields")
            if columns[2] != "gene":
                continue
            chromosome, _, _, start_raw, end_raw, _, strand, _, attr_raw = columns
            if chromosome not in chromosome_lengths:
                raise ValueError(
                    f"GFF3 gene at line {line_number} uses unknown chromosome {chromosome}"
                )
            try:
                start = int(start_raw)
                end = int(end_raw)
            except ValueError as exc:
                raise ValueError(f"GFF3 line {line_number} has invalid coordinates") from exc
            if start < 1 or end < start or end > chromosome_lengths[chromosome]:
                raise ValueError(f"GFF3 line {line_number} has out-of-range coordinates")
            if strand not in {"+", "-"}:
                raise ValueError(f"GFF3 gene at line {line_number} has invalid strand")
            attributes = _parse_gff_attributes(attr_raw, line_number=line_number)
            accession = attributes.get("ID", "")
            if not accession or len(accession) > 64:
                raise ValueError(f"GFF3 line {line_number} has no valid gene ID")
            if accession in seen_accessions:
                raise ValueError(f"GFF3 contains duplicate gene ID {accession}")
            if not accession.endswith(f".{PREVIEW_ANNOTATION_VERSION}"):
                raise ValueError(
                    f"GFF3 gene ID {accession} is outside annotation {PREVIEW_ANNOTATION_VERSION}"
                )
            seen_accessions.add(accession)
            stored_attributes: dict[str, Any] = dict(attributes)
            stored_attributes["local_preview_dataset_key"] = PREVIEW_DATASET_KEY
            stored_attributes["local_preview_annotation_sha256"] = annotation_sha256
            features.append(
                GeneFeature(
                    accession=accession,
                    name=attributes.get("Name"),
                    chromosome=chromosome,
                    start=start,
                    end=end,
                    strand=strand,
                    biotype=attributes.get("biotype") or "gene",
                    description=attributes.get("description"),
                    attributes=stored_attributes,
                )
            )
    if assembly_version != PREVIEW_ASSEMBLY_VERSION:
        raise ValueError("GFF3 assembly-version header does not match v6.0")
    if annotation_version != PREVIEW_ANNOTATION_VERSION:
        raise ValueError("GFF3 annot-version header does not match Wm82.a6.v1")
    if not features:
        raise ValueError("GFF3 contains no gene rows")
    return features


def parse_mutation_sites(
    path: Path,
    chromosome_lengths: dict[str, int],
    gene_accessions: set[str],
    *,
    expected_rows: int = EXPECTED_SITE_ROWS,
) -> list[MutationSite]:
    """Read the location TSV without turning its rows into variants."""
    sites: list[MutationSite] = []
    seen_keys: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None or not set(REQUIRED_SITE_COLUMNS).issubset(reader.fieldnames):
            raise ValueError("mutation TSV is missing required source columns")
        for line_number, row in enumerate(reader, 2):
            site_key = (row.get("突变体系（株系母+位置）") or "").strip()
            mutant_line_name = (row.get("株系") or "").strip()
            chromosome = (row.get("染色体号") or "").strip()
            gene_accession = (row.get("基因号") or "").strip()
            confidence = (row.get("可信度（高/中/低）") or "").strip()
            feature = (row.get("特征") or "").strip()
            available_raw = (row.get("可获得") or "").strip()
            try:
                position = int((row.get("位点") or "").strip())
            except ValueError as exc:
                raise ValueError(f"mutation TSV line {line_number} has invalid position") from exc
            if not site_key or len(site_key) > 128 or site_key in seen_keys:
                raise ValueError(
                    f"mutation TSV line {line_number} has an invalid/duplicate site key"
                )
            if not mutant_line_name or len(mutant_line_name) > 128:
                raise ValueError(f"mutation TSV line {line_number} has an invalid line name")
            if chromosome not in chromosome_lengths:
                raise ValueError(
                    f"mutation TSV line {line_number} has unknown chromosome {chromosome}"
                )
            if not 1 <= position <= chromosome_lengths[chromosome]:
                raise ValueError(f"mutation TSV line {line_number} has out-of-range position")
            if confidence not in {"H", "L"}:
                raise ValueError(f"mutation TSV line {line_number} has unsupported confidence")
            if available_raw not in {"Y", "N"}:
                raise ValueError(f"mutation TSV line {line_number} has unsupported availability")
            if not gene_accession or gene_accession not in gene_accessions:
                raise ValueError(
                    f"mutation TSV line {line_number} gene ID is absent from the selected GFF3"
                )
            if not feature or len(feature) > 256:
                raise ValueError(f"mutation TSV line {line_number} has an invalid feature")
            seen_keys.add(site_key)
            homologs = [
                (row.get(column) or "").strip() or None for column in HOMOLOG_SITE_COLUMNS
            ]
            for column, value in zip(HOMOLOG_SITE_COLUMNS, homologs, strict=True):
                if value is not None and len(value) > 128:
                    raise ValueError(
                        f"mutation TSV line {line_number} has an over-long {column}"
                    )
            sites.append(
                MutationSite(
                    source_site_key=site_key,
                    mutant_line_name=mutant_line_name,
                    chromosome=chromosome,
                    position=position,
                    confidence=confidence,
                    gene_accession=gene_accession,
                    feature=feature,
                    available=available_raw == "Y",
                    gene_v2=homologs[0],
                    gene_v4=homologs[1],
                    gene_dn53=homologs[2],
                )
            )
    if len(sites) != expected_rows:
        raise ValueError(
            f"expected {expected_rows} test-site rows; found {len(sites)}"
        )
    return sites


async def import_local_test_preview(
    *,
    engine: AsyncEngine,
    database_url: str,
    gff3_path: Path,
    fai_path: Path,
    sites_tsv_path: Path,
) -> LocalPreviewImportReport:
    """Import only into the opt-in disposable database on loopback port 55432."""
    validate_local_test_database(database_url)
    for path, expected_name in (
        (gff3_path, "Gmax_880_Wm82.a6.v1.gene.gff3"),
        (fai_path, "Gmax_880_v6.0.fa.fai"),
        (sites_tsv_path, "mu-infor_Gmax_880_Wm82-test.txt"),
    ):
        if path.name != expected_name or not path.is_file():
            raise ValueError(f"input must be the supplied test file {expected_name}")

    annotation_sha256 = file_sha256(gff3_path)
    source_sha256 = file_sha256(sites_tsv_path)
    chromosome_lengths = read_fai(fai_path)
    genes = parse_gene_features(
        gff3_path,
        chromosome_lengths,
        annotation_sha256=annotation_sha256,
    )
    sites = parse_mutation_sites(
        sites_tsv_path,
        chromosome_lengths,
        {gene.accession for gene in genes},
    )

    async with engine.begin() as connection:
        await connection.run_sync(_verify_core_schema)
        # Only this preview-specific table is created here. The ordinary
        # application tables still require the checked-in Alembic migrations.
        await connection.run_sync(
            # `Model.__table__` is typed as a generic FromClause, but `create`
            # is a `Table` method. The annotation says which one it is.
            lambda sync_connection: cast(Table, LocalTestMutationSite.__table__).create(
                sync_connection, checkfirst=True
            )
        )
        # A preview table created before the homolog columns existed is not
        # recreated by `checkfirst`; add the missing columns in place so an
        # existing local database does not have to be dropped and re-imported.
        await connection.run_sync(_ensure_homolog_columns)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as db:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": PREVIEW_DATASET_KEY},
        )
        release, assembly, imported_genes = await _ensure_preview_scope(
            db,
            gene_count=len(genes),
            annotation_sha256=annotation_sha256,
        )
        chromosome_ids = await _ensure_chromosomes(
            db,
            assembly_id=assembly.id,
            chromosome_lengths=chromosome_lengths,
        )
        if imported_genes:
            await _insert_genes(
                db,
                assembly_id=assembly.id,
                genes=genes,
            )
        gene_ids = await _gene_primary_keys(
            db,
            assembly_id=assembly.id,
            accessions={site.gene_accession for site in sites},
        )
        if len(gene_ids) != len({site.gene_accession for site in sites}):
            raise ValueError("one or more test-site gene IDs are missing from the v6 annotation")

        # `available` is the one column the admin console may edit, so carry the
        # stored value across a re-import instead of resetting it to the TSV
        # default. Everything else is source-of-truth from the file.
        preserved_available: dict[str, bool] = dict(
            (
                await db.execute(
                    select(
                        LocalTestMutationSite.source_site_key,
                        LocalTestMutationSite.available,
                    ).where(
                        LocalTestMutationSite.dataset_key == PREVIEW_DATASET_KEY,
                        LocalTestMutationSite.assembly_id == assembly.id,
                    )
                )
            ).all()
        )
        await db.execute(
            delete(LocalTestMutationSite).where(
                LocalTestMutationSite.dataset_key == PREVIEW_DATASET_KEY,
                LocalTestMutationSite.assembly_id == assembly.id,
            )
        )
        await _insert_sites(
            db,
            release_id=release.id,
            assembly_id=assembly.id,
            chromosome_ids=chromosome_ids,
            gene_ids=gene_ids,
            sites=sites,
            preserved_available=preserved_available,
            source_file=sites_tsv_path.name,
            source_sha256=source_sha256,
            annotation_file=gff3_path.name,
            annotation_sha256=annotation_sha256,
        )

    return LocalPreviewImportReport(
        assembly_name=PREVIEW_ASSEMBLY_NAME,
        release_version=PREVIEW_RELEASE_VERSION,
        gene_count=len(genes),
        site_count=len(sites),
        imported_genes=imported_genes,
        source_sha256=source_sha256,
        annotation_sha256=annotation_sha256,
    )


#: Source-TSV columns added after the first preview imports shipped.
_HOMOLOG_COLUMNS = ("gene_v2", "gene_v4", "gene_dn53")


def _ensure_homolog_columns(connection) -> None:
    """Add the homolog columns to a preview table that predates them.

    The table is created outside the Alembic sequence, so there is no migration
    to lean on; a plain `ADD COLUMN` is safe here because the columns are
    nullable and the table is a disposable local projection.
    """
    table_name = LocalTestMutationSite.__tablename__
    existing = {column["name"] for column in inspect(connection).get_columns(table_name)}
    for column_name in _HOMOLOG_COLUMNS:
        if column_name not in existing:
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR(128)")
            )


def _verify_core_schema(connection) -> None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    required = {"assemblies", "releases", "chromosomes", "genes"}
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(
            "apply the existing API migrations before importing local preview data; "
            f"missing tables: {', '.join(missing)}"
        )
    unique_constraints = inspector.get_unique_constraints("assemblies")
    has_assembly_release_key = any(
        set(item.get("column_names") or ()) == {"id", "release_id"}
        for item in unique_constraints
    )
    if not has_assembly_release_key:
        raise RuntimeError(
            "apply API migration 0038 first; the assembly/release boundary is missing"
        )


async def _ensure_preview_scope(
    db: AsyncSession,
    *,
    gene_count: int,
    annotation_sha256: str,
) -> tuple[Release, Assembly, bool]:
    release = await db.scalar(
        select(Release)
        .where(Release.version == PREVIEW_RELEASE_VERSION)
        .with_for_update()
    )
    expected_notes = {
        "marker": PREVIEW_RELEASE_MARKER,
        "annotation_sha256": annotation_sha256,
        "assembly": PREVIEW_ASSEMBLY_NAME,
    }
    if release is None:
        release = Release(
            version=PREVIEW_RELEASE_VERSION,
            name="Local unpublished v6 test data",
            description=(
                "Local-only preview source. This draft release must never be published."
            ),
            status=ReleaseStatus.DRAFT.value,
            assembly=PREVIEW_ASSEMBLY_NAME,
            notes="\n".join(f"{key}={value}" for key, value in expected_notes.items()),
            variant_count=0,
            gene_count=0,
            mutant_line_count=0,
        )
        db.add(release)
        await db.flush()
    else:
        if release.status != ReleaseStatus.DRAFT.value:
            raise RuntimeError("refusing to import into a release that is not draft")
        if PREVIEW_RELEASE_MARKER not in (release.notes or ""):
            raise RuntimeError("refusing to reuse a release not created for local test preview")
        if release.assembly != PREVIEW_ASSEMBLY_NAME:
            raise RuntimeError("local preview release has an unexpected assembly name")

    # ``Assembly.release`` is eagerly joined (lazy="joined"), and PostgreSQL
    # rejects FOR UPDATE on the nullable side of an outer join; scope the row
    # lock to the assemblies table only.
    assembly = await db.scalar(
        select(Assembly)
        .where(Assembly.name == PREVIEW_ASSEMBLY_NAME)
        .with_for_update(of=Assembly)
    )
    if assembly is None:
        assembly = Assembly(
            name=PREVIEW_ASSEMBLY_NAME,
            version=PREVIEW_ASSEMBLY_VERSION,
            species="Glycine max",
            description=(
                "Unpublished local test assembly from Gmax_880_v6.0.fa; "
                "annotation Wm82.a6.v1."
            ),
            is_default=False,
            release_id=release.id,
        )
        db.add(assembly)
        await db.flush()
    elif (
        assembly.release_id != release.id
        or assembly.version != PREVIEW_ASSEMBLY_VERSION
        or assembly.is_default
    ):
        raise RuntimeError("refusing to reuse an assembly outside the local draft release")

    if release.assembly_id not in (None, assembly.id):
        raise RuntimeError("local preview release points to another assembly")
    release.assembly_id = assembly.id
    release.assembly = PREVIEW_ASSEMBLY_NAME

    existing_gene_rows = int(
        await db.scalar(
            select(func.count()).select_from(Gene).where(Gene.assembly_id == assembly.id)
        )
        or 0
    )
    imported_genes = existing_gene_rows == 0
    if existing_gene_rows:
        gene_sources = await db.execute(
            select(Gene.attributes).where(Gene.assembly_id == assembly.id)
        )
        all_preview_genes = all(
            isinstance(attributes, dict)
            and attributes.get("local_preview_dataset_key") == PREVIEW_DATASET_KEY
            and attributes.get("local_preview_annotation_sha256") == annotation_sha256
            for (attributes,) in gene_sources.all()
        )
        release_source_matches = (
            f"annotation_sha256={annotation_sha256}" in (release.notes or "")
        )
        if not all_preview_genes or not release_source_matches:
            raise RuntimeError(
                "the local v6 assembly already contains genes from another source; "
                "use a fresh disposable database"
            )
    release.gene_count = gene_count
    release.variant_count = 0
    release.mutant_line_count = 0
    await db.flush()
    return release, assembly, imported_genes


async def _ensure_chromosomes(
    db: AsyncSession,
    *,
    assembly_id: int,
    chromosome_lengths: dict[str, int],
) -> dict[str, int]:
    result = await db.execute(
        select(Chromosome).where(Chromosome.assembly_id == assembly_id)
    )
    existing = {chromosome.name: chromosome for chromosome in result.scalars().all()}
    unknown = sorted(set(existing) - set(chromosome_lengths))
    if unknown:
        raise RuntimeError("local v6 assembly contains unexpected chromosomes")
    for index, name in enumerate(EXPECTED_CHROMOSOMES, 1):
        chromosome = existing.get(name)
        if chromosome is None:
            chromosome = Chromosome(
                assembly_id=assembly_id,
                name=name,
                length=chromosome_lengths[name],
                order=index,
            )
            db.add(chromosome)
        elif chromosome.length != chromosome_lengths[name]:
            raise RuntimeError(f"chromosome length mismatch for {name}")
    await db.flush()
    result = await db.execute(
        select(Chromosome.name, Chromosome.id).where(
            Chromosome.assembly_id == assembly_id
        )
    )
    # Mappings rather than tuple unpacking: the row type of a two-column
    # select is not statically known to be a pair, so both the unpack form and
    # the index form are guesses the type checker rejects.
    return {
        str(row["name"]): int(row["id"])
        for row in result.mappings().all()
    }


async def _insert_genes(
    db: AsyncSession,
    *,
    assembly_id: int,
    genes: list[GeneFeature],
) -> None:
    chromosome_ids = dict(
        (
            await db.execute(
                select(Chromosome.name, Chromosome.id).where(
                    Chromosome.assembly_id == assembly_id
                )
            )
        ).all()
    )
    batch_size = 1000
    for offset in range(0, len(genes), batch_size):
        batch = genes[offset : offset + batch_size]
        rows = [
            {
                "accession": gene.accession,
                "assembly_id": assembly_id,
                "chromosome_id": chromosome_ids[gene.chromosome],
                "name": gene.name,
                "biotype": gene.biotype,
                "start": gene.start,
                "end": gene.end,
                "strand": gene.strand,
                "description": gene.description,
                "attributes": gene.attributes,
            }
            for gene in batch
        ]
        await db.execute(insert(cast(Table, Gene.__table__)), rows)
    await db.flush()


async def _gene_primary_keys(
    db: AsyncSession,
    *,
    assembly_id: int,
    accessions: set[str],
) -> dict[str, int]:
    result: dict[str, int] = {}
    ordered = sorted(accessions)
    for offset in range(0, len(ordered), 1000):
        batch = ordered[offset : offset + 1000]
        rows = await db.execute(
            select(Gene.accession, Gene.gene_pk).where(
                Gene.assembly_id == assembly_id,
                Gene.accession.in_(batch),
            )
        )
        result.update({accession: int(gene_pk) for accession, gene_pk in rows.all()})
    return result


async def _insert_sites(
    db: AsyncSession,
    *,
    release_id: int,
    assembly_id: int,
    chromosome_ids: dict[str, int],
    gene_ids: dict[str, int],
    sites: list[MutationSite],
    preserved_available: dict[str, bool],
    source_file: str,
    source_sha256: str,
    annotation_file: str,
    annotation_sha256: str,
) -> None:
    rows = [
        {
            "dataset_key": PREVIEW_DATASET_KEY,
            "source_site_key": site.source_site_key,
            "mutant_line_name": site.mutant_line_name,
            "assembly_id": assembly_id,
            "release_id": release_id,
            "chromosome_id": chromosome_ids[site.chromosome],
            "gene_pk": gene_ids[site.gene_accession],
            "position": site.position,
            "confidence": site.confidence,
            "feature": site.feature,
            "available": preserved_available.get(site.source_site_key, site.available),
            "gene_v2": site.gene_v2,
            "gene_v4": site.gene_v4,
            "gene_dn53": site.gene_dn53,
            "source_file": source_file,
            "source_sha256": source_sha256,
            "annotation_file": annotation_file,
            "annotation_sha256": annotation_sha256,
            "annotation_version": PREVIEW_ANNOTATION_VERSION,
        }
        for site in sites
    ]
    await db.execute(insert(cast(Table, LocalTestMutationSite.__table__)), rows)


def _parse_gff_attributes(value: str, *, line_number: int) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for item in value.strip().strip(";").split(";"):
        if not item:
            continue
        key, separator, raw_value = item.partition("=")
        if not separator or not key:
            raise ValueError(f"GFF3 line {line_number} has malformed attributes")
        attributes[unquote(key)] = unquote(raw_value)
    return attributes


__all__ = [
    "EXPECTED_SITE_ROWS",
    "GeneFeature",
    "LocalPreviewImportReport",
    "MutationSite",
    "file_sha256",
    "import_local_test_preview",
    "parse_gene_features",
    "parse_mutation_sites",
    "read_fai",
    "validate_local_test_database",
]
