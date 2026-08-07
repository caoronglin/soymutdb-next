"""Pre-computed gene-data cache builder.

Builds a JSON blob and a prerendered HTML page for each gene (expression
summary, homologs, variant stats).  Stores the JSON in ``gene_data_cache``
and optionally uploads both ``.json.gz`` and ``.html.gz`` to S3 for CDN.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from celery import Task
from jinja2 import Environment, FileSystemLoader, filters

from app.models.expression import ExpressionData, ExpressionLibrary
from app.models.gene_data_cache import GeneDataCache
from app.models.genomic import Chromosome, Gene
from app.models.homolog import GeneHomolog
from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.s3 import get_s3_client

logger = logging.getLogger(__name__)

# Chunk size for processing genes in batches (for progress reporting)
_GENE_CHUNK = 1000

# Max expression rows shown in the static HTML page
_MAX_EXPRESSION_ROWS = 50

# ---------------------------------------------------------------------------
# Jinja2 environment
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
)


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


_jinja_env.filters.setdefault("comma_or_none", _comma_or_none)
_jinja_env.filters.setdefault("fmt_number", _fmt_number)

# Pre-load templates once
_gene_detail_template = _jinja_env.get_template("gene_detail.html.j2")


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


def _build_expression_summary(session, gene_id: str) -> tuple[list[dict[str, Any]], int]:
    """Query expression data for a gene.

    Returns (top_N_list, total_count).
    """
    # First get total count
    total_count = (
        session.query(ExpressionData.id)
        .filter(ExpressionData.gene_id == gene_id)
        .count()
    )

    # Get top N ordered by fpkm desc
    rows = (
        session.query(
            ExpressionLibrary.library_name,
            ExpressionLibrary.tissue,
            ExpressionLibrary.treatment,
            ExpressionData.fpkm,
            ExpressionData.tpm,
            ExpressionData.raw_count,
        )
        .join(ExpressionData, ExpressionData.library_id == ExpressionLibrary.id)
        .filter(ExpressionData.gene_id == gene_id)
        .order_by(ExpressionData.fpkm.desc().nullslast())
        .limit(_MAX_EXPRESSION_ROWS)
        .all()
    )
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


def _build_homolog_summary(session, gene_id: str) -> list[dict[str, Any]]:
    """Query homolog data for a gene."""
    rows = (
        session.query(GeneHomolog)
        .filter(GeneHomolog.gene_id == gene_id)
        .all()
    )
    return [
        {
            "homolog_species": r.homolog_species,
            "homolog_gene_id": r.homolog_gene_id,
            "homolog_type": r.homolog_type,
            "source": r.source,
        }
        for r in rows
    ]


def _render_gene_html(
    gene_info: dict[str, Any],
    expressions: list[dict[str, Any]],
    total_expression_count: int,
    homologs: list[dict[str, Any]],
    generated_at: str,
) -> str:
    """Render the gene detail page HTML from the Jinja2 template."""
    return _gene_detail_template.render(
        gene=gene_info,
        expressions=expressions,
        total_expression_count=total_expression_count,
        homologs=homologs,
        variants=None,
        generated_at=generated_at,
    )


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
    upload_s3: bool = True,
) -> dict[str, Any]:
    """Build pre-computed gene data cache for one, many, or all genes.

    For each gene, queries:
      - Gene metadata (from the ``genes`` table)
      - Expression summary (tissue / treatment / fpkm / tpm) — top 50 rows
      - Homologs (orthologs / paralogs)

    Stores the result as JSON in ``gene_data_cache`` (upsert).  Optionally
    also writes a gzipped JSON file and a prerendered HTML page to S3 under
    ``genes/{gene_id}.json.gz`` and ``genes/{gene_id}.html.gz``.

    Args:
        gene_ids: Specific gene IDs to process, or ``None`` for all genes.
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
        if gene_ids is not None:
            genes = (
                session.query(Gene, Chromosome.name.label("chromosome_name"))
                .outerjoin(Chromosome, Gene.chromosome_id == Chromosome.id)
                .filter(Gene.id.in_(gene_ids))
                .all()
            )
        else:
            genes = (
                session.query(Gene, Chromosome.name.label("chromosome_name"))
                .outerjoin(Chromosome, Gene.chromosome_id == Chromosome.id)
                .all()
            )

    total = len(genes)
    logger.info("Processing %d genes for cache build", total)

    if total == 0:
        return {"processed": 0, "total": 0}

    bucket = get_setting("S3_PUBLIC_BUCKET", "genomic-data")
    processed = 0
    failed = 0

    for idx in range(0, total, _GENE_CHUNK):
        chunk = genes[idx : idx + _GENE_CHUNK]

        for gene, chromosome_name in chunk:
            try:
                now = datetime.now(timezone.utc)
                generated_at = now.isoformat()

                gene_info = _build_gene_data(
                    gene_id=gene.id,
                    gene_name=gene.name,
                    biotype=gene.biotype,
                    chromosome_name=chromosome_name,
                    start=gene.start,
                    end=gene.end,
                    strand=gene.strand,
                    description=gene.description,
                )

                with get_db() as session:
                    expression_data, total_expression_count = _build_expression_summary(
                        session, gene.id
                    )
                    homolog_data = _build_homolog_summary(session, gene.id)

                cache_data: dict[str, Any] = {
                    "gene": gene_info,
                    "expression": expression_data,
                    "homologs": homolog_data,
                    "built_at": generated_at,
                }

                # ── Upsert into GeneDataCache ──────────────────────────────
                with get_db() as session:
                    existing = session.get(GeneDataCache, gene.id)
                    if existing:
                        existing.data = cache_data
                        existing.updated_at = now
                    else:
                        session.add(
                            GeneDataCache(
                                gene_id=gene.id,
                                data=cache_data,
                            )
                        )
                    session.commit()

                # ── Upload to S3 (if enabled) ──────────────────────────────
                if s3_client is not None:
                    # --- JSON ---
                    json_bytes = json.dumps(cache_data, default=_serialize_value).encode(
                        "utf-8"
                    )
                    _upload_gzipped(
                        s3_client,
                        bucket,
                        f"genes/{gene.id}.json.gz",
                        json_bytes,
                        content_type="application/json",
                    )

                    # --- HTML ---
                    html_str = _render_gene_html(
                        gene_info=gene_info,
                        expressions=expression_data,
                        total_expression_count=total_expression_count,
                        homologs=homolog_data,
                        generated_at=generated_at,
                    )
                    _upload_gzipped(
                        s3_client,
                        bucket,
                        f"genes/{gene.id}.html.gz",
                        html_str.encode("utf-8"),
                        content_type="text/html",
                    )

                processed += 1

            except Exception as e:
                logger.error("Failed to build cache for gene %s: %s", gene.id, e)
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
