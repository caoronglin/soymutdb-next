"""Statistics computation tasks.

All ClickHouse queries use parameterised bindings — user input is never
interpolated into SQL strings.
"""

from __future__ import annotations

import logging

from celery import Task

from soymutdb_worker.main import celery_app
from soymutdb_worker.tasks.ingest import get_clickhouse_client

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="soymutdb_worker.tasks.stats.update_release_stats",
    queue="stats",
)
def update_release_stats(self: Task, release_id: str = "") -> dict:
    """Update release-level statistics from ClickHouse.

    If *release_id* is empty, statistics are computed for all releases.
    Runs periodically (hourly) and after ingestion completes.
    """
    logger.info("Updating release statistics (release_id=%s)", release_id or "ALL")

    ch = get_clickhouse_client()

    # Get list of releases to process
    if release_id:
        releases_result = ch.query(
            "SELECT DISTINCT release_key FROM variant_facts "
            "WHERE release_key = %(release_id)s ORDER BY release_key",
            parameters={"release_id": release_id},
        )
    else:
        releases_result = ch.query(
            "SELECT DISTINCT release_key FROM variant_facts ORDER BY release_key"
        )

    releases = [row[0] for row in releases_result.result_rows]
    results: dict = {}

    for rel_key in releases:
        # Variant counts by type
        type_result = ch.query(
            """
            SELECT variant_type, count() AS cnt
            FROM variant_facts
            WHERE release_key = %(release)s
            GROUP BY variant_type
            """,
            parameters={"release": rel_key},
        )
        type_counts = {row[0]: int(row[1]) for row in type_result.result_rows}

        # Gene count
        gene_result = ch.query(
            """
            SELECT uniqExact(gene_surrogate_id)
            FROM variant_facts
            WHERE release_key = %(release)s AND gene_surrogate_id > 0
            """,
            parameters={"release": rel_key},
        )
        gene_count = int(gene_result.result_rows[0][0]) if gene_result.result_rows else 0

        # Mutant line count
        ml_result = ch.query(
            """
            SELECT uniqExact(mutant_line_surrogate_id)
            FROM variant_facts
            WHERE release_key = %(release)s AND mutant_line_surrogate_id > 0
            """,
            parameters={"release": rel_key},
        )
        ml_count = int(ml_result.result_rows[0][0]) if ml_result.result_rows else 0

        # Impact breakdown
        impact_result = ch.query(
            """
            SELECT impact, count() AS cnt
            FROM variant_facts
            WHERE release_key = %(release)s
            GROUP BY impact
            """,
            parameters={"release": rel_key},
        )
        impact_counts = {row[0]: int(row[1]) for row in impact_result.result_rows}

        total = sum(type_counts.values())

        results[rel_key] = {
            "variant_count": total,
            "snp_count": type_counts.get("SNP", 0),
            "indel_count": type_counts.get("InDel", 0),
            "sv_count": type_counts.get("SV", 0),
            "gene_count": gene_count,
            "mutant_line_count": ml_count,
            "impact_counts": impact_counts,
        }

        logger.info(
            "Release %s: %d variants, %d genes, %d mutant lines",
            rel_key,
            total,
            gene_count,
            ml_count,
        )

    return {"releases_processed": len(releases), "results": results}


@celery_app.task(
    bind=True,
    name="soymutdb_worker.tasks.stats.compute_chromosome_density",
    queue="stats",
)
def compute_chromosome_density(
    self: Task,
    release_id: str,
    chromosome: str = "",
    resolution: str = "10kb",
) -> dict:
    """Compute variant density for a chromosome at a given resolution.

    All parameters are bound via ``%(name)s`` placeholders.
    """
    logger.info("Computing density for %s %s at %s", release_id, chromosome, resolution)

    ch = get_clickhouse_client()

    bin_sizes = {"10kb": 10000, "100kb": 100000, "1mb": 1000000}
    bin_size = bin_sizes.get(resolution, 100000)

    if chromosome:
        result = ch.query(
            """
            SELECT
                intDiv(position - 1, %(bin_size)s) * %(bin_size)s + 1 AS bin_start,
                count() AS variant_count,
                sum(if(variant_type = 'SNP', 1, 0)) AS snp_count,
                sum(if(variant_type = 'InDel', 1, 0)) AS indel_count,
                sum(if(variant_type = 'SV', 1, 0)) AS sv_count,
                sum(if(impact = 'HIGH', 1, 0)) AS high_impact_count
            FROM variant_facts
            WHERE release_key = %(release)s
              AND chromosome = %(chrom)s
            GROUP BY bin_start
            ORDER BY bin_start
            """,
            parameters={
                "release": release_id,
                "chrom": chromosome,
                "bin_size": bin_size,
            },
        )
    else:
        result = ch.query(
            """
            SELECT
                chromosome,
                intDiv(position - 1, %(bin_size)s) * %(bin_size)s + 1 AS bin_start,
                count() AS variant_count,
                sum(if(variant_type = 'SNP', 1, 0)) AS snp_count,
                sum(if(variant_type = 'InDel', 1, 0)) AS indel_count,
                sum(if(variant_type = 'SV', 1, 0)) AS sv_count,
                sum(if(impact = 'HIGH', 1, 0)) AS high_impact_count
            FROM variant_facts
            WHERE release_key = %(release)s
            GROUP BY chromosome, bin_start
            ORDER BY chromosome, bin_start
            """,
            parameters={"release": release_id, "bin_size": bin_size},
        )

    bins = [
        {
            "chromosome": row[0] if not chromosome else chromosome,
            "bin_start": row[1] if not chromosome else row[0],
            "variant_count": int(row[2] if not chromosome else row[1]),
            "snp_count": int(row[3] if not chromosome else row[2]),
            "indel_count": int(row[4] if not chromosome else row[3]),
            "sv_count": int(row[5] if not chromosome else row[4]),
            "high_impact_count": int(row[6] if not chromosome else row[5]),
        }
        for row in result.result_rows
    ]

    return {
        "release_id": release_id,
        "chromosome": chromosome,
        "resolution": resolution,
        "bin_count": len(bins),
        "total_variants": sum(b["variant_count"] for b in bins),
        "bins": bins[:100],
    }


@celery_app.task(
    bind=True,
    name="soymutdb_worker.tasks.stats.compute_gene_burden",
    queue="stats",
)
def compute_gene_burden(
    self: Task,
    release_id: str,
    top_n: int = 100,
) -> dict:
    """Compute gene burden statistics — genes with the most variants."""
    logger.info("Computing gene burden for %s, top %d", release_id, top_n)

    ch = get_clickhouse_client()

    result = ch.query(
        """
        SELECT
            v.gene_surrogate_id,
            g.gene_id,
            g.gene_name,
            count() AS variant_count,
            sum(if(impact = 'HIGH', 1, 0)) AS high_impact_count,
            sum(if(impact = 'MODERATE', 1, 0)) AS moderate_impact_count
        FROM variant_facts v
        LEFT JOIN gene_dim g ON v.gene_surrogate_id = g.gene_surrogate_id
            AND v.release_key = g.release_key
        WHERE v.release_key = %(release)s
          AND v.gene_surrogate_id > 0
        GROUP BY v.gene_surrogate_id, g.gene_id, g.gene_name
        ORDER BY high_impact_count DESC, variant_count DESC
        LIMIT %(top_n)s
        """,
        parameters={"release": release_id, "top_n": top_n},
    )

    genes = [
        {
            "gene_surrogate_id": row[0],
            "gene_id": row[1],
            "gene_name": row[2],
            "variant_count": int(row[3]),
            "high_impact_count": int(row[4]),
            "moderate_impact_count": int(row[5]),
        }
        for row in result.result_rows
    ]

    return {"release_id": release_id, "top_n": top_n, "genes": genes}


@celery_app.task(
    bind=True,
    name="soymutdb_worker.tasks.stats.compute_mutant_line_comparison",
    queue="stats",
)
def compute_mutant_line_comparison(
    self: Task,
    release_id: str,
    mutant_line_ids: list[int],
) -> dict:
    """Compare variant profiles across multiple mutant lines.

    Returns overlap and unique variants for UpSet plot generation.
    """
    logger.info(
        "Computing mutant line comparison for %d lines", len(mutant_line_ids)
    )

    ch = get_clickhouse_client()

    result = ch.query(
        """
        SELECT
            mutant_line_surrogate_id,
            count() AS variant_count,
            sum(if(impact = 'HIGH', 1, 0)) AS high_impact_count,
            uniqExact(concat(chromosome, ':', toString(position), ':',
                ref_allele, '>', alt_allele)) AS unique_variants
        FROM variant_facts
        WHERE release_key = %(release)s
          AND mutant_line_surrogate_id IN %(ml_ids)s
        GROUP BY mutant_line_surrogate_id
        """,
        parameters={"release": release_id, "ml_ids": tuple(mutant_line_ids)},
    )

    lines = [
        {
            "mutant_line_surrogate_id": row[0],
            "variant_count": int(row[1]),
            "high_impact_count": int(row[2]),
            "unique_variants": int(row[3]),
        }
        for row in result.result_rows
    ]

    return {"release_id": release_id, "mutant_lines": lines}
