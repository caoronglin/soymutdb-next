"""Native PostgreSQL variant statistics with explicit release/assembly scope."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import text

from soymutdb_worker.main import celery_app
from soymutdb_worker.utils.db import get_db


def _release_id(value: str) -> int:
    identity = int(value)
    if identity < 1:
        raise ValueError("A positive resolved release identity is required")
    return identity


@contextmanager
def _snapshot():
    with get_db() as session:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        yield session


@celery_app.task(bind=True, name="soymutdb_worker.tasks.stats.update_release_stats", queue="stats")
def update_release_stats(self, release_id: str = "") -> dict:
    """Read release counts without copying or creating another authoritative store."""
    with _snapshot() as session:
        if release_id:
            identities = [_release_id(release_id)]
        else:
            identities = session.execute(text(
                "SELECT DISTINCT release_id FROM variant_facts ORDER BY release_id"
            )).scalars().all()
        results = {}
        for identity in identities:
            params = {"release_id": identity}
            types = dict(session.execute(text(
                "SELECT variant_type,count(*) FROM variant_facts "
                "WHERE release_id=:release_id GROUP BY variant_type"
            ), params).all())
            genes, mutants = session.execute(text(
                "SELECT count(DISTINCT (assembly_id,gene_id)) FILTER (WHERE gene_id <> ''), "
                "count(DISTINCT mutant_line_surrogate_id) FILTER "
                "(WHERE mutant_line_surrogate_id > 0) FROM variant_facts "
                "WHERE release_id=:release_id"
            ), params).one()
            impacts = dict(session.execute(text(
                "SELECT impact,count(*) FROM variant_facts "
                "WHERE release_id=:release_id GROUP BY impact"
            ), params).all())
            results[str(identity)] = {
                "variant_count": sum(types.values()), "snp_count": types.get("SNP", 0),
                "indel_count": types.get("INS", 0) + types.get("DEL", 0),
                "sv_count": types.get("SV", 0), "gene_count": int(genes),
                "mutant_line_count": int(mutants), "impact_counts": impacts,
            }
    return {"releases_processed": len(identities), "results": results}


@celery_app.task(
    bind=True, name="soymutdb_worker.tasks.stats.compute_chromosome_density", queue="stats",
)
def compute_chromosome_density(self, release_id: str, chromosome: str = "", resolution="10kb"):
    sizes = {"10kb": 10_000, "100kb": 100_000, "1mb": 1_000_000}
    if resolution not in sizes:
        raise ValueError("Unknown chromosome density resolution")
    params = {"release_id": _release_id(release_id), "bin_size": sizes[resolution]}
    where = "release_id=:release_id"
    if chromosome:
        where += " AND chromosome=:chromosome"
        params["chromosome"] = chromosome
    with _snapshot() as session:
        rows = session.execute(text(
            "SELECT assembly_key,chromosome, "
            "((position-1)/CAST(:bin_size AS bigint))*CAST(:bin_size AS bigint)+1 AS bin_start, "
            "count(*) AS variant_count, "
            "count(*) FILTER (WHERE variant_type='SNP') AS snp_count, "
            "count(*) FILTER (WHERE variant_type IN ('INS','DEL')) AS indel_count, "
            "count(*) FILTER (WHERE variant_type='SV') AS sv_count, "
            "count(*) FILTER (WHERE impact='HIGH') AS high_impact_count "
            "FROM variant_facts WHERE " + where
            + " GROUP BY assembly_key,chromosome,bin_start "
            "ORDER BY assembly_key,chromosome,bin_start"
        ), params).mappings().all()
        bins = [dict(row) for row in rows]
    return {
        "release_id": release_id, "chromosome": chromosome, "resolution": resolution,
        "bin_count": len(bins), "total_variants": sum(row["variant_count"] for row in bins),
        "bins": bins[:100],
    }


@celery_app.task(bind=True, name="soymutdb_worker.tasks.stats.compute_gene_burden", queue="stats")
def compute_gene_burden(self, release_id: str, top_n: int = 100):
    if not 1 <= top_n <= 1000:
        raise ValueError("Gene burden limit must be between 1 and 1000")
    with _snapshot() as session:
        rows = session.execute(text(
            "SELECT assembly_key,gene_surrogate_id,gene_id,gene_symbol AS gene_name, "
            "count(*) AS variant_count, "
            "count(*) FILTER (WHERE impact='HIGH') AS high_impact_count, "
            "count(*) FILTER (WHERE impact='MODERATE') AS moderate_impact_count "
            "FROM variant_facts WHERE release_id=:release_id AND gene_id <> '' "
            "GROUP BY assembly_key,gene_surrogate_id,gene_id,gene_symbol "
            "ORDER BY high_impact_count DESC,variant_count DESC,assembly_key,gene_id LIMIT :top_n"
        ), {"release_id": _release_id(release_id), "top_n": top_n}).mappings().all()
        genes = [dict(row) for row in rows]
    return {"release_id": release_id, "top_n": top_n, "genes": genes}


@celery_app.task(
    bind=True, name="soymutdb_worker.tasks.stats.compute_mutant_line_comparison", queue="stats",
)
def compute_mutant_line_comparison(self, release_id: str, mutant_line_ids: list[int]):
    if len(mutant_line_ids) > 1000 or any(
        type(value) is not int or value < 1 for value in mutant_line_ids
    ):
        raise ValueError("Mutant comparison requires at most 1000 positive internal surrogates")
    with _snapshot() as session:
        rows = session.execute(text(
            "SELECT mutant_line_surrogate_id,count(*) AS variant_count, "
            "count(*) FILTER (WHERE impact='HIGH') AS high_impact_count, "
            "count(DISTINCT (assembly_id,chromosome,position,ref_allele,alt_allele)) "
            "AS unique_variants "
            "FROM variant_facts WHERE release_id=:release_id "
            "AND mutant_line_surrogate_id=ANY(:mutant_line_ids) GROUP BY mutant_line_surrogate_id"
        ), {"release_id": _release_id(release_id), "mutant_line_ids": mutant_line_ids})
        rows = rows.mappings().all()
        lines = [dict(row) for row in rows]
    return {"release_id": release_id, "mutant_lines": lines}
