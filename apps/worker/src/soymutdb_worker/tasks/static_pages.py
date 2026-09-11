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
import io
import json
import logging
from datetime import UTC, datetime
from typing import Any

from celery import Task
from dominate.tags import div, em, main
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.tables import (
    chromosomes,
    expression_data,
    expression_libraries,
    gene_data_cache,
    gene_homologs,
    genes,
)
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.html_report import HTMLReport
from soymutdb_worker.utils.s3 import get_s3_client

logger = logging.getLogger(__name__)

# Chunk size for processing genes in batches (for progress reporting)
_GENE_CHUNK = 1000

# Max expression rows shown in the static HTML page
_MAX_EXPRESSION_ROWS = 50


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


def _upload_gzipped(
    s3_client,
    bucket: str,
    key: str,
    data: bytes,
    content_type: str,
    content_encoding: str = "gzip",
) -> None:
    """Upload gzip-compressed data to S3."""
    gz_buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=gz_buffer, mode="wb") as gz_out:
        gz_out.write(data)
    gz_buffer.seek(0)
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=gz_buffer.getvalue(),
        ContentType=content_type,
        ContentEncoding=content_encoding,
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

    Object key layout (when ``release_id`` is provided):
      ``{release_id}/{assembly_id}/genes/{accession}.json.gz``
      ``{release_id}/{assembly_id}/genes/{accession}.html.gz``

    Fallback (backward compatibility when ``release_id`` is omitted):
      ``{assembly_id}/genes/{accession}.json.gz``

    Args:
        gene_ids: Specific gene IDs to process, or ``None`` for all genes.
        release_id: Optional release identifier for the object namespace.
        upload_s3: Whether to upload gzipped copies to S3 (default True).

    Returns:
        dict with build statistics.
    """
    logger.info(
        "Building static gene pages (gene_ids=%s, upload_s3=%s)",
        "ALL" if gene_ids is None else f"{len(gene_ids)} genes",
        upload_s3,
    )

    s3_client = get_s3_client() if upload_s3 else None

    # ── Resolve gene list ───────────────────────────────────────────────
    with get_db() as session:
        stmt = (
            select(
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
            )
            .outerjoin(chromosomes, genes.c.chromosome_id == chromosomes.c.id)
        )
        if gene_ids is not None:
            stmt = stmt.where(genes.c.accession.in_(gene_ids))
        gene_rows = session.execute(stmt).all()

    total = len(gene_rows)
    logger.info("Processing %d genes for cache build", total)

    if total == 0:
        return {"processed": 0, "total": 0}

    bucket = get_setting("S3_PUBLIC_BUCKET", "genomic-data")
    processed = 0
    failed = 0

    for idx in range(0, total, _GENE_CHUNK):
        chunk = gene_rows[idx : idx + _GENE_CHUNK]

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
                    prefix_parts: list[str] = []
                    if release_id is not None:
                        prefix_parts.append(str(release_id))
                    prefix_parts.append(str(row.assembly_id))
                    prefix_parts.append("genes")
                    key_prefix = "/".join(prefix_parts)

                    # --- JSON ---
                    json_bytes = json.dumps(cache_data, default=_serialize_value).encode(
                        "utf-8"
                    )
                    _upload_gzipped(
                        s3_client,
                        bucket,
                        f"{key_prefix}/{row.accession}.json.gz",
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
                        f"{key_prefix}/{row.accession}.html.gz",
                        html_str.encode("utf-8"),
                        content_type="text/html",
                    )

                processed += 1

            except Exception as e:
                logger.error("Failed to build cache for gene %s: %s", row.accession, e)
                failed += 1

        # Report progress for this chunk
        pct = int((idx + len(chunk)) * 100 / total) if total else 0
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
