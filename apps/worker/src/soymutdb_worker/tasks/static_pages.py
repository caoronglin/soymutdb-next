"""Pre-computed gene-data cache builder.

Builds a JSON blob and a prerendered HTML page for each gene (expression
summary, homologs, variant stats).  Stores the JSON in ``gene_data_cache``
and optionally uploads both ``.json.gz`` and ``.html.gz`` to S3 for CDN.

The worker never imports API models: all reads/writes use the narrow
SQLAlchemy Core tables from :mod:`soymutdb_worker.tables`.

The HTML page is rendered with the shared dominate-based builder from
:mod:`soymutdb_worker.utils.html_report` (previously a Jinja2 template).
"""

from __future__ import annotations

import gzip
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from celery import Task
from dominate.tags import div, em, main
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.tables import (
    assemblies,
    chromosomes,
    expression_data,
    expression_libraries,
    gene_data_cache,
    gene_homologs,
    genes,
    releases,
)
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.html_report import HTMLReport
from soymutdb_worker.utils.s3 import get_s3_client

logger = logging.getLogger(__name__)

# Chunk size for processing genes in batches (for progress reporting)
_GENE_CHUNK = 1000

# Max expression rows shown in the static HTML page
_MAX_EXPRESSION_ROWS = 50

#: Isolation used for the per-batch gene metadata reads.  ``READ ONLY`` keeps
#: the transaction from taking row locks, so a long build never blocks
#: independent writes; ``REPEATABLE READ`` makes every row inside a single
#: batch see one consistent snapshot.  It must be the first statement issued on
#: the connection, before any read.
_SNAPSHOT_ISOLATION_SQL = "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"

#: The only release status whose artifacts may reach the public bucket.
_PUBLIC_RELEASE_STATUS = "published"


def _comma_or_none(value: Any) -> str:
    """Format an integer with commas, or return '—' if None."""
    if value is None:
        return "—"
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return str(value)


def _fmt_number(value: Any) -> str:
    """Format a float to 2 decimal places, or return '—' if None."""
    if value is None:
        return "—"
    try:
        v = float(value)
        if v == int(v):
            return f"{int(v)}"
        return f"{v:.2f}"
    except (ValueError, TypeError):
        return str(value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_value(val: Any) -> Any:
    """Convert non-serializable types to plain Python types."""
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, set):
        return list(val)
    return val


def _build_gene_data(
    gene_id: str,
    gene_name: str | None,
    biotype: str | None,
    chromosome_name: str | None,
    start: int | None,
    end: int | None,
    strand: str | None,
    description: str | None,
) -> dict[str, Any]:
    """Build a structured data dict for a single gene."""
    return {
        "gene_id": gene_id,
        "gene_name": gene_name,
        "biotype": biotype,
        "chromosome": chromosome_name,
        "start": start,
        "end": end,
        "strand": strand,
        "description": description,
    }


def _build_expression_summary(session, gene_id: int) -> tuple[list[dict[str, Any]], int]:
    """Query expression data for a gene.

    Returns (top_N_list, total_count).
    """
    # First get total count
    total_count = session.execute(
        select(func.count())
        .select_from(expression_data)
        .where(expression_data.c.gene_id == gene_id)
    ).scalar_one()

    # Get top N ordered by fpkm desc
    rows = session.execute(
        select(
            expression_libraries.c.library_name,
            expression_libraries.c.tissue,
            expression_libraries.c.treatment,
            expression_data.c.fpkm,
            expression_data.c.tpm,
            expression_data.c.raw_count,
        )
        .join(expression_data, expression_data.c.library_id == expression_libraries.c.id)
        .where(expression_data.c.gene_id == gene_id)
        .order_by(expression_data.c.fpkm.desc().nullslast())
        .limit(_MAX_EXPRESSION_ROWS)
    ).all()
    return [
        {
            "library_name": r.library_name,
            "tissue": r.tissue,
            "treatment": r.treatment,
            "fpkm": _serialize_value(r.fpkm),
            "tpm": _serialize_value(r.tpm),
            "raw_count": _serialize_value(r.raw_count),
        }
        for r in rows
    ], total_count


def _build_homolog_summary(session, gene_id: int) -> list[dict[str, Any]]:
    """Query homolog data for a gene."""
    rows = session.execute(
        select(
            gene_homologs.c.homolog_species,
            gene_homologs.c.homolog_gene_id,
            gene_homologs.c.homolog_type,
            gene_homologs.c.source,
        )
        .where(gene_homologs.c.gene_id == gene_id)
    ).all()
    return [
        {
            "homolog_species": r.homolog_species,
            "homolog_gene_id": r.homolog_gene_id,
            "homolog_type": r.homolog_type,
            "source": r.source,
        }
        for r in rows
    ]


def _position_text(gene_info: dict[str, Any]) -> str:
    """Format the genomic position line, or '—' when the chromosome is absent."""
    chromosome = gene_info.get("chromosome")
    if not chromosome:
        return "—"
    return (
        f"{chromosome}:{_comma_or_none(gene_info.get('start'))}"
        f"-{_comma_or_none(gene_info.get('end'))} ({gene_info.get('strand')})"
    )


def _render_gene_html(
    gene_info: dict[str, Any],
    expressions: list[dict[str, Any]],
    total_expression_count: int,
    homologs: list[dict[str, Any]],
    generated_at: str,
) -> str:
    """Render the gene detail page HTML via the shared dominate builder."""
    gene_id = gene_info["gene_id"]
    gene_name = gene_info.get("gene_name")
    report = HTMLReport(title=f"{gene_id} — {gene_name or 'No name'} — SoyMutDB")
    report.add_header()

    with report.container(main()):
        with report.container(div(cls="container")):
            # ── Gene Header Card ─────────────────────────────────────────
            with report.container(div(cls="card")):
                report.add_heading(gene_id)
                report.add_table(
                    ["Field", "Value"],
                    [
                        ["Name", gene_name or "—"],
                        ["Biotype", gene_info.get("biotype")],
                        ["Position", _position_text(gene_info)],
                        ["Description", gene_info.get("description") or "—"],
                    ],
                )

            # ── Expression Summary ───────────────────────────────────────
            with report.container(div(cls="card")):
                report.add_heading(
                    f"Expression Data (top {len(expressions)} of "
                    f"{total_expression_count})"
                )
                report.add_table(
                    ["Library", "Tissue", "Treatment", "FPKM", "TPM", "Raw Count"],
                    [
                        [
                            exp["library_name"],
                            exp.get("tissue"),
                            exp.get("treatment"),
                            _fmt_number(exp.get("fpkm")),
                            _fmt_number(exp.get("tpm")),
                            exp.get("raw_count"),
                        ]
                        for exp in expressions
                    ],
                    empty_text="No expression data available for this gene.",
                )

            # ── Homologs ─────────────────────────────────────────────────
            with report.container(div(cls="card")):
                report.add_heading("Homologs")
                report.add_table(
                    ["Species", "Gene ID", "Type", "Source"],
                    [
                        [
                            em(hom["homolog_species"]),
                            hom["homolog_gene_id"],
                            hom["homolog_type"],
                            hom.get("source"),
                        ]
                        for hom in homologs
                    ],
                    empty_text="No homolog data available for this gene.",
                )

            # ── Variant Summary ──────────────────────────────────────────
            with report.container(div(cls="card")):
                report.add_heading("Variant Summary")
                report.add_table(
                    ["Type", "Count", "High Impact", "Moderate Impact"],
                    [],
                    empty_text="No variant data included in this pre-generated page.",
                )

            # ── Footer Note ──────────────────────────────────────────────
            report.add_paragraph(
                f"This page was pre-generated on {generated_at}. "
                "For real-time data, visit the live gene detail page.",
                cls="note",
            )

    report.add_footer()
    return report.render()


def gene_object_key(
    accession: str,
    *,
    assembly_id: int | str,
    release_id: int | str | None,
    extension: str,
) -> str:
    """Build the object-storage key for a pre-rendered gene artifact.

    The key namespace is ``{release_id}/{assembly_id}/genes/{accession}``.

    Both the release and the assembly are part of the namespace: an accession
    is only unique *within* an assembly (v4 and v5 are distinct coordinate
    namespaces), and the same assembly is republished under each release.
    Omitting either would let one artifact silently overwrite another.

    ``release_id`` is optional for backward compatibility with archives written
    before release-scoped publishing; when omitted the namespace degrades to
    ``{assembly_id}/genes/{accession}``.
    """
    accession = accession.strip()
    if not accession:
        raise ValueError("accession must be a non-empty string")
    if "/" in accession or "\\" in accession:
        raise ValueError(f"accession must not contain a path separator: {accession!r}")
    if extension not in {"json.gz", "html.gz"}:
        raise ValueError(f"unsupported artifact extension: {extension!r}")

    parts: list[str] = []
    if release_id is not None:
        parts.append(str(release_id))
    parts.extend([str(assembly_id), "genes", f"{accession}.{extension}"])
    return "/".join(parts)


def _upload_gzipped(
    s3_client,
    bucket: str,
    key: str,
    data: bytes,
    content_type: str,
    content_encoding: str = "gzip",
) -> None:
    """Upload gzip-compressed data to S3 with reproducible bytes.

    ``mtime=0`` keeps the gzip header timestamp fixed, so identical input
    bytes always produce an identical object body.  That lets content digests
    stay stable across rebuilds and lets unchanged artifacts keep their cache
    entry instead of being re-uploaded under a fresh digest.
    """
    body = gzip.compress(data, mtime=0)
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
        ContentEncoding=content_encoding,
    )


# ---------------------------------------------------------------------------
# Release scope + bounded batch iteration
# ---------------------------------------------------------------------------


@contextmanager
def _read_only_snapshot() -> Iterator[Any]:
    """Open a short-lived read-only snapshot for one batch of gene metadata.

    One snapshot per batch, deliberately never one for the whole build.  The
    worker engine defaults to a single connection (``WORKER_DB_POOL_SIZE``
    defaults to 1), so holding a session open across the per-gene cache
    upserts would starve the very writes the batch is feeding.  ``READ ONLY``
    additionally guarantees the read transaction never takes the row locks a
    write needs, so the batch walk cannot block independent writes.

    What the snapshot guarantees is narrow: the rows of *one* batch are read
    from a single consistent PostgreSQL snapshot.  It is not a build-wide or
    database-wide snapshot.  Each batch opens a new transaction, and the
    per-gene expression and homolog reads run on their own separate sessions
    (see :func:`build_static_pages`), so a gene's ancillary rows may reflect a
    slightly later database state than its metadata row.  Nothing here claims
    the published set of artifacts is an atomic snapshot of the database.
    """
    with get_db() as session:
        session.execute(text(_SNAPSHOT_ISOLATION_SQL))
        yield session


def _apply_gene_scope(stmt, *, gene_ids, release_id):
    """Attach the accession filter and the release filter to a gene statement.

    Release scoping joins ``assemblies`` and filters on its API-owned
    ``release_id``: a gene belongs to exactly one assembly, and the assembly is
    the unit that carries release identity, so this is the narrowest correct
    join.  Without ``release_id`` the statement keeps the historical unscoped
    behaviour used for internal (non-published) cache rebuilds.
    """
    if release_id is not None:
        stmt = stmt.join(assemblies, genes.c.assembly_id == assemblies.c.id).where(
            assemblies.c.release_id == release_id
        )
    if gene_ids is not None:
        stmt = stmt.where(genes.c.accession.in_(gene_ids))
    return stmt


def gene_metadata_statement(*, gene_ids=None, release_id=None, after_gene_pk=None):
    """Build one bounded keyset page of gene metadata, ordered by ``gene_pk``.

    ``after_gene_pk`` is the keyset cursor: only genes with a strictly greater
    primary key are returned, and the page is hard-capped at ``_GENE_CHUNK``
    rows.  The statement therefore cannot degrade into an unbounded read of
    the whole gene table, whatever the result size.
    """
    stmt = select(
        genes.c.gene_pk,
        genes.c.accession,
        genes.c.assembly_id,
        genes.c.name,
        genes.c.biotype,
        genes.c.start,
        genes.c.end,
        genes.c.strand,
        genes.c.description,
        chromosomes.c.name.label("chromosome_name"),
    ).outerjoin(chromosomes, genes.c.chromosome_id == chromosomes.c.id)
    stmt = _apply_gene_scope(stmt, gene_ids=gene_ids, release_id=release_id)
    if after_gene_pk is not None:
        stmt = stmt.where(genes.c.gene_pk > after_gene_pk)
    return stmt.order_by(genes.c.gene_pk).limit(_GENE_CHUNK)


def gene_scope_count_statement(*, gene_ids=None, release_id=None):
    """Count the genes in exactly the scope the keyset walk will visit.

    The count uses the same predicates as the page statement. Concurrent
    mutations between batch snapshots can still change the eventual total.
    """
    return _apply_gene_scope(
        select(func.count()).select_from(genes),
        gene_ids=gene_ids,
        release_id=release_id,
    )


def iter_gene_batches(*, gene_ids=None, release_id=None):
    """Walk the selected genes in ``gene_pk`` order, one bounded batch at a time.

    Each batch is read inside its own read-only snapshot, so peak memory stays
    at ``_GENE_CHUNK`` rows no matter how many genes match.  The snapshots are
    per batch and therefore not consistent with each other: a gene inserted
    above the cursor by a concurrent ingest may or may not appear, depending on
    when its batch is read.
    """
    after_gene_pk = None
    while True:
        with _read_only_snapshot() as session:
            batch = session.execute(
                gene_metadata_statement(
                    gene_ids=gene_ids,
                    release_id=release_id,
                    after_gene_pk=after_gene_pk,
                )
            ).all()
        if not batch:
            return
        # Advance the cursor before yielding: the caller catches per-row
        # failures, so a row that blows up must not stall or rewind the walk.
        after_gene_pk = batch[-1].gene_pk
        yield batch


def require_published_release(session, release_id) -> None:
    """Fail closed unless ``release_id`` names an existing, published release.

    Publishing artifacts for a draft, rolled-back, or unknown release would put
    unreleased content behind a public URL, and falling back to an unscoped
    namespace would publish something anyway.  Every non-published state raises.
    """
    status = session.execute(
        select(releases.c.status).where(releases.c.id == release_id)
    ).scalar_one_or_none()
    if status is None:
        raise ValueError(f"release {release_id!r} does not exist; refusing to publish")
    if str(status) != _PUBLIC_RELEASE_STATUS:
        raise ValueError(
            f"release {release_id!r} is {str(status)!r}, not {_PUBLIC_RELEASE_STATUS!r}; "
            "refusing to publish"
        )


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="soymutdb_worker.tasks.static_pages.build_static_pages",
    queue="stats",
)
def build_static_pages(
    self: Task,
    gene_ids: list[str] | None = None,
    *,
    release_id: int | None = None,
    upload_s3: bool = True,
) -> dict[str, Any]:
    """Build pre-computed gene data cache for one, many, or all genes.

    For each gene, queries:
      - Gene metadata (from the ``genes`` table)
      - Expression summary (tissue / treatment / fpkm / tpm) — top 50 rows
      - Homologs (orthologs / paralogs)

    Stores the result as JSON in ``gene_data_cache`` (upsert).  Optionally
    also writes a gzipped JSON file and a prerendered HTML page to S3 under
    a release/assembly-scoped prefix so the same accession in v4 and v5
    does not overwrite each other.

    With ``upload_s3=True`` the task fails closed unless ``release_id`` names
    an existing release whose ``releases.status`` is ``published``: publishing
    a draft/unknown release, or falling back to an unscoped namespace, would
    put unreleased content behind a public URL.  With ``upload_s3=False`` the
    historical unscoped internal-cache mode stays available.  The published
    status is re-checked before every batch of public uploads, so a release
    that is rolled back mid-build stops further publishing; artifacts already
    written before the rollback stay in the bucket (withdrawing them is out of
    scope for this task).

    Genes are walked with a keyset cursor over ``gene_pk`` in bounded batches
    of ``_GENE_CHUNK`` rows, each read inside its own short read-only
    repeatable-read snapshot.  The row count for progress reporting comes from
    a count over the same scope, and no statement reads the full gene table.
    Those snapshots are per batch, not per build: each batch opens its own
    transaction, and the expression/homolog reads and the cache upserts run on
    their own short sessions.  A build is therefore not an atomic view of the
    database, and the published artifacts are not claimed to be one.

    Object key layout (when ``release_id`` is provided):
      ``{release_id}/{assembly_id}/genes/{accession}.json.gz``
      ``{release_id}/{assembly_id}/genes/{accession}.html.gz``

    Fallback (backward compatibility when ``release_id`` is omitted):
      ``{assembly_id}/genes/{accession}.json.gz``

    Args:
        gene_ids: Specific gene IDs to process, or ``None`` for all genes.
        release_id: Release identifier.  Scopes the gene query to assemblies
            of that release and namespaces the object keys.  Required when
            ``upload_s3`` is true.
        upload_s3: Whether to upload gzipped copies to S3 (default True).

    Returns:
        dict with build statistics.
    """
    logger.info(
        "Building static gene pages (gene_ids=%s, release_id=%s, upload_s3=%s)",
        "ALL" if gene_ids is None else f"{len(gene_ids)} genes",
        release_id,
        upload_s3,
    )

    if upload_s3 and release_id is None:
        raise ValueError(
            "upload_s3=True requires an explicit release_id; a release-less "
            "namespace must never be published"
        )

    # ── Validate release, then size the scope ────────────────────────────
    with _read_only_snapshot() as session:
        if upload_s3:
            require_published_release(session, release_id)
        total = session.execute(
            gene_scope_count_statement(gene_ids=gene_ids, release_id=release_id)
        ).scalar_one()

    # Only after the scope validates: an invalid scope must not touch storage.
    s3_client = get_s3_client() if upload_s3 else None

    logger.info("Processing %d genes for cache build", total)

    if total == 0:
        return {"processed": 0, "total": 0}

    bucket = get_setting("S3_PUBLIC_BUCKET", "genomic-data")
    processed = 0
    failed = 0

    batches = 0
    for chunk in iter_gene_batches(gene_ids=gene_ids, release_id=release_id):
        # Re-confirm the release before every batch of public uploads.  A
        # release can be rolled back while a long build is running, and a
        # start-of-run check alone would keep publishing it to the bucket.
        if s3_client is not None:
            with get_db() as session:
                require_published_release(session, release_id)

        for row in chunk:
            try:
                now = datetime.now(UTC)
                generated_at = now.isoformat()

                gene_info = _build_gene_data(
                    gene_id=row.accession,
                    gene_name=row.name,
                    biotype=row.biotype,
                    chromosome_name=row.chromosome_name,
                    start=row.start,
                    end=row.end,
                    strand=row.strand,
                    description=row.description,
                )

                with get_db() as session:
                    expression_data_rows, total_expression_count = _build_expression_summary(
                        session, row.gene_pk
                    )
                    homolog_data = _build_homolog_summary(session, row.gene_pk)

                cache_data: dict[str, Any] = {
                    "gene": gene_info,
                    "expression": expression_data_rows,
                    "homologs": homolog_data,
                    "built_at": generated_at,
                }

                # ── Upsert into GeneDataCache ──────────────────────────────
                with get_db() as session:
                    upsert_stmt = pg_insert(gene_data_cache).values(
                        gene_id=row.gene_pk,
                        data=cache_data,
                        updated_at=now,
                    )
                    upsert_stmt = upsert_stmt.on_conflict_do_update(
                        index_elements=[gene_data_cache.c.gene_id],
                        set_={"data": cache_data, "updated_at": now},
                    )
                    session.execute(upsert_stmt)
                    session.commit()

                # ── Upload to S3 (if enabled) ──────────────────────────────
                if s3_client is not None:
                    # Namespace keys by release/assembly so v4 and v5 genes
                    # with the same accession never overwrite each other.
                    # --- JSON ---
                    json_bytes = json.dumps(cache_data, default=_serialize_value).encode(
                        "utf-8"
                    )
                    _upload_gzipped(
                        s3_client,
                        bucket,
                        gene_object_key(
                            row.accession,
                            assembly_id=row.assembly_id,
                            release_id=release_id,
                            extension="json.gz",
                        ),
                        json_bytes,
                        content_type="application/json",
                    )

                    # --- HTML ---
                    html_str = _render_gene_html(
                        gene_info=gene_info,
                        expressions=expression_data_rows,
                        total_expression_count=total_expression_count,
                        homologs=homolog_data,
                        generated_at=generated_at,
                    )
                    _upload_gzipped(
                        s3_client,
                        bucket,
                        gene_object_key(
                            row.accession,
                            assembly_id=row.assembly_id,
                            release_id=release_id,
                            extension="html.gz",
                        ),
                        html_str.encode("utf-8"),
                        content_type="text/html",
                    )

                processed += 1

            except Exception as e:
                logger.error("Failed to build cache for gene %s: %s", row.accession, e)
                failed += 1

        # Report progress for this chunk.  Rows seen are derived from the batch
        # walk, never from a full in-memory list of every selected gene.
        batches += 1
        seen = min(batches * _GENE_CHUNK, total)
        pct = int(seen * 100 / total) if total else 0
        self.update_state(
            state="PROGRESS",
            meta={
                "progress": pct,
                "processed": processed,
                "failed": failed,
                "total": total,
            },
        )
        logger.info(
            "Progress: %d / %d genes processed (%d failed)",
            processed,
            total,
            failed,
        )

    result = {
        "processed": processed,
        "failed": failed,
        "total": total,
    }
    logger.info("Static page build complete: %s", result)
    return result
