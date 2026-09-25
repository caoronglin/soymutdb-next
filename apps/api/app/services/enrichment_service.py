"""GO/KEGG enrichment analysis service.

Implements two analysis modes over an assembly-scoped ``gene_annotations``
table (``assembly_id``, ``gene_id``, ``term_id``, ``term_name``, ``ontology``):

1. **ORA** — hand-written hypergeometric (right-tail) enrichment test with
   Benjamini-Hochberg multiple-testing correction.  SciPy is deliberately
   **not** required (not present in ``pyproject.toml``): all statistics are
   computed with the standard library (``math.lgamma`` / log-space
   arithmetic), which is numerically stable for the soybean genome scale
   (~56k background genes).

2. **GSEA** (simplified, numpy) — rank-based gene-set test over a list of
   per-gene values (e.g. log2 fold-changes).  For every annotated term the
   signed running-sum enrichment score is computed over the value-descending
   ranked list; the p-value uses the analytic one-sided Smirnov asymptotic
   and NES is a z-score of ES under the same null.

Source limitation note
----------------------
The external reference material planned for the GSEA implementation could
not be retrieved (the scraping source was blocked), so the statistics follow
the standard field definitions as documented in the primary literature:
running-sum ES (Mootha et al. 2003 / Subramanian et al. 2005), the one-sided
two-sample Kolmogorov-Smirnov (Smirnov) asymptotic for the p-value, and
Benjamini-Hochberg FDR.  NES is simplified to a z-score instead of the
phenotype-permutation normalization of the reference implementation.

The table is probed before querying. A missing table or ontology with no rows
returns an explicit empty result. If the table exists but assembly provenance
cannot be verified, the service fails closed with HTTP 503 rather than risk
mixing records from different assemblies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import NotFoundError, ServiceUnavailableError
from ..models.gene_annotation import GeneAnnotationSet
from ..models.genomic import Assembly
from ..schemas.enrichment import (
    MAX_TERM_GENES,
    EnrichmentCalculationResponse,
    EnrichmentGseaCalculationResponse,
    EnrichmentGseaResponse,
    EnrichmentGseaTerm,
    EnrichmentResponse,
    EnrichmentSource,
    EnrichmentTerm,
    Ontology,
)

# Guard against pathological right-tail sums (many terms with large K and n);
# the truncated tail mass is negligible for significance testing.
_MAX_TAIL_STEPS = 100_000

# Expected table that carries GO/KEGG annotations.
ANNOTATION_TABLE = "gene_annotations"


# ---------------------------------------------------------------------------
# Statistics (pure, unit-testable)
# ---------------------------------------------------------------------------


def _log_pmf(N: int, K: int, n: int, x: int) -> float:
    """Log of the hypergeometric PMF P(X = x).

    P(X = x) = C(K, x) * C(N - K, n - x) / C(N, n), computed via
    ``math.lgamma`` so no intermediate integer overflows / huge ints occur.
    """
    return (
        math.lgamma(K + 1)
        - math.lgamma(x + 1)
        - math.lgamma(K - x + 1)
        + math.lgamma(N - K + 1)
        - math.lgamma(n - x + 1)
        - math.lgamma(N - K - n + x + 1)
        - math.lgamma(N + 1)
        + math.lgamma(n + 1)
        + math.lgamma(N - n + 1)
    )


def _logsumexp(logs: list[float]) -> float:
    """Numerically stable ``log(sum(exp(logs)))``."""
    if not logs:
        return -math.inf
    peak = max(logs)
    return peak + math.log(sum(math.exp(log - peak) for log in logs))


def hypergeom_sf(N: int, K: int, n: int, k: int) -> float:
    """Hypergeometric survival function: P(X >= k).

    Draws ``n`` genes without replacement from ``N`` background genes, of
    which ``K`` are annotated to the term; ``k`` of the drawn genes carry the
    annotation.  Right-tail probabilities are accumulated from the PMF via
    the log-space ratio recurrence

        P(X = x + 1) / P(X = x) = (K - x)/(x + 1) * (n - x)/(N - K - n + x + 1)

    Edge cases mirror scipy.stats.hypergeom.sf: P(X >= k) == 1 when ``k`` is
    at (or below) the minimum possible overlap ``max(0, n + K - N)``.
    """
    x_min = max(0, n + K - N)
    x_max = min(n, K)
    if k <= x_min:
        return 1.0
    if k > x_max:
        return 0.0

    tail: list[float] = []
    log_p = _log_pmf(N, K, n, x_min)
    x = x_min
    while x <= x_max:
        if x >= k:
            tail.append(log_p)
            if len(tail) >= _MAX_TAIL_STEPS:
                break
        if x == x_max:
            break
        # P(X = x + 1) / P(X = x) recurrence (all factors >= 1 in this range).
        log_p += math.log(K - x) - math.log(x + 1)
        log_p += math.log(n - x) - math.log(N - K - n + x + 1)
        x += 1

    return float(math.exp(_logsumexp(tail)))


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR correction for a list of raw p-values.

    Returns adjusted q-values in the same order as the input.  The standard
    step-up procedure walks the p-values from largest to smallest::

        q_(i) = min(p_(i) * m / i, q_(i+1))

    which guarantees monotone, non-decreasing q-values in the sorted order.
    """
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: p_values[i], reverse=True)
    q_values = [0.0] * m
    prev = 1.0
    for rank_from_end, idx in enumerate(order, start=1):
        rank = m - rank_from_end + 1
        adjusted = p_values[idx] * m / rank
        prev = min(adjusted, prev)
        q_values[idx] = prev
    return q_values


def gsea_term_stat(hit_positions: list[int], k: int, n: int) -> tuple[float, float, float]:
    """Enrichment score, simplified NES and p-value for one gene set.

    ``hit_positions`` are the 0-based positions of the set's member genes in
    the value-descending ranked list (length ``k``); ``n`` is the length of
    the ranked list.

    ES — signed running-sum statistic (one-sided two-sample KS form): the
    walk starts at 0, adds ``+1/k`` at member positions and ``-1/(n-k)`` at
    non-member positions, and ES is the extremum with the largest absolute
    value (positive when the set concentrates at high values, negative at
    low values; ties resolve towards the positive extremum).

    NES — z-score normalization ``ES * sqrt(k(n-k)/n)`` under the analytic
    null; a documented simplification of the phenotype-permutation NES.

    p-value — one-sided Smirnov asymptotic ``exp(-2 * k(n-k)/n * ES^2)``
    (no permutations are run).
    """
    steps = np.full(n, -1.0 / (n - k))
    steps[hit_positions] = 1.0 / k
    running = np.cumsum(steps)
    es_max = float(running.max())
    es_min = float(running.min())
    es = es_max if es_max >= -es_min else es_min
    lam = k * (n - k) / n
    nes = es * math.sqrt(lam)
    p_value = math.exp(-2.0 * lam * es * es)
    return es, nes, p_value


# ---------------------------------------------------------------------------
# Annotation loading
# ---------------------------------------------------------------------------


async def fetch_annotations(
    db: AsyncSession, ontology: Ontology, *, assembly_id: int, release_id: int
) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Load gene → term mapping from the ``gene_annotations`` table.

    Returns ``(gene_to_terms, term_names)`` where ``gene_to_terms`` maps each
    annotated gene id to the set of its term ids for *ontology*, and
    ``term_names`` maps term id → display name. When the table or ontology is
    absent, both mappings are empty. Failure to inspect table provenance, or
    a table without ``assembly_id`` and ``release_id``, raises
    ``ServiceUnavailableError``.
    """
    try:
        connection = await db.connection()
        has_table = await connection.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table(ANNOTATION_TABLE)
        )
    except Exception as exc:
        raise ServiceUnavailableError(
            "Could not verify assembly and release provenance for GO/KEGG annotations.",
            details={"code": "annotation_provenance_unavailable"},
        ) from exc

    if not has_table:
        return {}, {}

    try:
        columns = await connection.run_sync(
            lambda sync_conn: {
                column["name"]
                for column in inspect(sync_conn).get_columns(ANNOTATION_TABLE)
            }
        )
    except Exception as exc:
        raise ServiceUnavailableError(
            "Could not verify assembly and release provenance for GO/KEGG annotations.",
            details={"code": "annotation_provenance_unavailable"},
        ) from exc
    scope_columns = {"assembly_id", "release_id", "annotation_set_id"}
    if not scope_columns.issubset(columns):
        raise ServiceUnavailableError(
            "GO/KEGG annotations do not carry source, assembly, and release "
            "provenance; import scoped annotations before using this tool.",
            details={
                "code": "annotation_provenance_required",
                "table": ANNOTATION_TABLE,
            },
        )
    query_columns = {"ontology", "gene_id", "term_id", "term_name"}
    if not query_columns.issubset(columns):
        raise ServiceUnavailableError(
            "GO/KEGG annotation table is missing required query columns.",
            details={
                "code": "annotation_schema_required",
                "table": ANNOTATION_TABLE,
            },
        )

    stmt = text(
        "SELECT gene_id, term_id, term_name "
        f"FROM {ANNOTATION_TABLE} WHERE ontology = :ontology "
        "AND assembly_id = :assembly_id AND release_id = :release_id"
    )
    result = await db.execute(
        stmt,
        {
            "ontology": ontology,
            "assembly_id": assembly_id,
            "release_id": release_id,
        },
    )

    gene_to_terms: dict[str, set[str]] = {}
    term_names: dict[str, str] = {}
    for gene_id, term_id, term_name in result.all():
        term_id = str(term_id)
        gene_to_terms.setdefault(str(gene_id), set()).add(term_id)
        term_names.setdefault(term_id, str(term_name) if term_name else term_id)
    return gene_to_terms, term_names


async def fetch_annotation_source(
    db: AsyncSession,
    ontology: Ontology,
    *,
    assembly_id: int,
    release_id: int,
) -> EnrichmentSource | None:
    """Return the provenance record for the selected annotation snapshot.

    A legacy annotation table with scoped rows but no source record is not
    suitable for a public enrichment result and fails closed. A missing or
    empty annotation table yields ``None`` so the API can return its explicit
    empty-result message. The recorded snapshot row count is compared with the
    current scoped rows so cascaded gene deletion cannot leave stale source
    attribution in a public result.
    """
    try:
        connection = await db.connection()
        table_state = await connection.run_sync(
            lambda sync_conn: (
                inspect(sync_conn).has_table(ANNOTATION_TABLE),
                inspect(sync_conn).has_table("gene_annotation_sets"),
            )
        )
    except Exception as exc:
        raise ServiceUnavailableError(
            "Could not verify source provenance for GO/KEGG annotations.",
            details={"code": "annotation_source_unavailable"},
        ) from exc

    has_annotations, has_sources = table_state
    if not has_annotations:
        return None

    if not has_sources:
        raise ServiceUnavailableError(
            "GO/KEGG annotations have no source provenance table; apply the "
            "annotation schema migration before using this tool.",
            details={"code": "annotation_source_required"},
        )

    try:
        source_columns = await connection.run_sync(
            lambda sync_conn: {
                column["name"]
                for column in inspect(sync_conn).get_columns("gene_annotation_sets")
            }
        )
    except Exception as exc:
        raise ServiceUnavailableError(
            "Could not verify source provenance for GO/KEGG annotations.",
            details={"code": "annotation_source_unavailable"},
        ) from exc
    required = {
        "id",
        "assembly_id",
        "release_id",
        "ontology",
        "source_name",
        "source_version",
        "source_url",
        "source_sha256",
        "row_count",
        "imported_at",
    }
    if not required.issubset(source_columns):
        raise ServiceUnavailableError(
            "GO/KEGG annotation source metadata is incomplete; re-import a "
            "source-attributed annotation snapshot.",
            details={"code": "annotation_source_required"},
        )

    source_result = await db.execute(
        select(
            GeneAnnotationSet.id,
            GeneAnnotationSet.source_name,
            GeneAnnotationSet.source_version,
            GeneAnnotationSet.source_url,
            GeneAnnotationSet.source_sha256,
            GeneAnnotationSet.row_count,
            GeneAnnotationSet.imported_at,
        )
        .where(
            GeneAnnotationSet.ontology == ontology,
            GeneAnnotationSet.assembly_id == assembly_id,
            GeneAnnotationSet.release_id == release_id,
        )
        .limit(2)
    )
    sources = source_result.all()
    if len(sources) > 1:
        raise ServiceUnavailableError(
            "Multiple GO/KEGG annotation sources match the selected assembly and release.",
            details={"code": "annotation_source_ambiguous"},
        )
    if not sources:
        scoped_rows = await db.execute(
            text(
                f"SELECT 1 FROM {ANNOTATION_TABLE} "
                "WHERE ontology = :ontology AND assembly_id = :assembly_id "
                "AND release_id = :release_id LIMIT 1"
            ),
            {
                "ontology": ontology,
                "assembly_id": assembly_id,
                "release_id": release_id,
            },
        )
        if scoped_rows.first() is not None:
            raise ServiceUnavailableError(
                "GO/KEGG annotation rows exist without a matching source snapshot.",
                details={"code": "annotation_source_required"},
            )
        return None

    source = sources[0]
    row_count_result = await db.execute(
        text(
            f"SELECT COUNT(*) FROM {ANNOTATION_TABLE} "
            "WHERE ontology = :ontology AND assembly_id = :assembly_id "
            "AND release_id = :release_id"
        ),
        {
            "ontology": ontology,
            "assembly_id": assembly_id,
            "release_id": release_id,
        },
    )
    if row_count_result.scalar_one() != source.row_count:
        raise ServiceUnavailableError(
            "GO/KEGG annotation rows do not match the selected source snapshot row count.",
            details={"code": "annotation_source_row_count_mismatch"},
        )

    mismatched_rows = await db.execute(
        text(
            f"SELECT 1 FROM {ANNOTATION_TABLE} "
            "WHERE ontology = :ontology AND assembly_id = :assembly_id "
            "AND release_id = :release_id "
            "AND (annotation_set_id IS NULL OR annotation_set_id != :annotation_set_id) "
            "LIMIT 1"
        ),
        {
            "ontology": ontology,
            "assembly_id": assembly_id,
            "release_id": release_id,
            "annotation_set_id": source.id,
        },
    )
    if mismatched_rows.first() is not None:
        raise ServiceUnavailableError(
            "GO/KEGG annotation rows do not match the selected source snapshot.",
            details={"code": "annotation_source_mismatch"},
        )

    return EnrichmentSource(
        name=source.source_name,
        version=source.source_version,
        url=source.source_url,
        sha256=source.source_sha256,
        imported_at=source.imported_at,
    )


# ---------------------------------------------------------------------------
# Core analysis — ORA
# ---------------------------------------------------------------------------


@dataclass
class _TermStats:
    """Intermediate per-term enrichment statistics."""

    term_id: str
    name: str
    k: int  # annotated input genes belonging to the term
    K: int  # background genes belonging to the term
    p_value: float
    member_genes: list[str]


def compute_enrichment(
    genes: list[str],
    gene_to_terms: dict[str, set[str]],
    term_names: dict[str, str],
    *,
    ontology: Ontology,
    p_threshold: float = 0.05,
    max_terms: int = 20,
) -> EnrichmentCalculationResponse:
    """Run the hypergeometric enrichment test over pre-loaded annotations.

    ``genes``: unique input gene ids (order preserved).
    ``gene_to_terms``: gene id → set of term ids (the background set is the
    set of genes present in this mapping).
    ``term_names``: term id → display name.
    ``ontology``: annotation source, reported verbatim in the response.

    All terms observed in the annotation table for the input genes are
    tested; p-values are corrected with Benjamini-Hochberg across the full
    term set, filtered by ``p_threshold`` on the raw p-value, sorted by
    q-value ascending, and truncated to ``max_terms``.
    """
    # Deduplicate while preserving first-seen order.
    seen: set[str] = set()
    unique_genes = [g for g in genes if not (g in seen or seen.add(g))]

    background_genes = len(gene_to_terms)
    n = len(unique_genes)
    message: str | None = None

    if background_genes == 0:
        message = (
            f"No {ontology.upper()} annotations are available; "
            "the gene_annotations table is empty or missing for this ontology."
        )
        return EnrichmentCalculationResponse(
            mode="ora",
            ontology=ontology,
            input_genes=n,
            background_genes=0,
            terms=[],
            message=message,
        )

    annotated_input = [g for g in unique_genes if g in gene_to_terms]
    if not annotated_input:
        message = (
            f"None of the {n} input genes have {ontology.upper()} annotations; "
            "no enrichment could be computed."
        )
        return EnrichmentCalculationResponse(
            mode="ora",
            ontology=ontology,
            input_genes=n,
            background_genes=background_genes,
            terms=[],
            message=message,
        )

    # Term → input member genes (only terms present in the annotation table).
    term_members: dict[str, list[str]] = {}
    for gene in annotated_input:
        for term_id in gene_to_terms[gene]:
            term_members.setdefault(term_id, []).append(gene)

    # Background counts per term.
    term_background: dict[str, int] = {}
    for terms in gene_to_terms.values():
        for term_id in terms:
            term_background[term_id] = term_background.get(term_id, 0) + 1

    # N = annotated genes in the background; n = annotated input genes.
    n_annotated = len(annotated_input)
    N = background_genes

    stats: list[_TermStats] = []
    for term_id, members in term_members.items():
        K = term_background[term_id]
        k = len(members)
        p_value = hypergeom_sf(N=N, K=K, n=n_annotated, k=k)
        stats.append(
            _TermStats(
                term_id=term_id,
                name=term_names.get(term_id, term_id),
                k=k,
                K=K,
                p_value=p_value,
                member_genes=members,
            )
        )

    # BH correction across every tested term, then filter by raw p-value.
    q_values = benjamini_hochberg([s.p_value for s in stats])

    significant = [
        (s, q)
        for s, q in zip(stats, q_values)
        if s.p_value <= p_threshold
    ]
    significant.sort(key=lambda sq: (sq[1], sq[0].p_value, sq[0].term_id))

    terms = [
        EnrichmentTerm(
            id=s.term_id,
            name=s.name,
            p_value=s.p_value,
            q_value=q,
            gene_count=s.k,
            genes=s.member_genes[:MAX_TERM_GENES],
        )
        for s, q in significant[:max_terms]
    ]
    return EnrichmentCalculationResponse(
        mode="ora",
        ontology=ontology,
        input_genes=n,
        background_genes=background_genes,
        terms=terms,
        message=message,
    )


# ---------------------------------------------------------------------------
# Core analysis — GSEA (simplified, rank-based)
# ---------------------------------------------------------------------------


@dataclass
class _GseaTermStats:
    """Intermediate per-term rank-based statistics."""

    term_id: str
    name: str
    es: float
    nes: float
    p_value: float
    size: int  # member genes present in the ranked input
    member_genes: list[str]


def compute_gsea_enrichment(
    genes: list[str],
    values: list[float],
    gene_to_terms: dict[str, set[str]],
    term_names: dict[str, str],
    *,
    ontology: Ontology,
    p_threshold: float = 0.05,
    max_terms: int = 20,
    min_genes: int = 5,
) -> EnrichmentGseaCalculationResponse:
    """Run the simplified rank-based (GSEA) test over pre-loaded annotations.

    ``genes``/``values``: input gene ids aligned 1:1 with per-gene values
    (e.g. log2 fold-changes); duplicates are deduplicated keeping the first
    value.  The ranked list is the full deduplicated input sorted by value
    descending (ties broken by gene id for determinism); genes without
    annotations still rank and contribute background steps only.

    Every annotated term with at least ``min_genes`` members in the ranked
    list is tested with the running-sum statistic (see ``gsea_term_stat``);
    p-values are corrected with Benjamini-Hochberg across the tested term
    set, filtered by ``p_threshold`` on the raw p-value, sorted by q-value
    ascending, and truncated to ``max_terms``.  Terms that would be
    degenerate for the statistic (member count >= ranked-list length) are
    skipped.
    """
    # Deduplicate while preserving first-seen order (keep the first value).
    seen: set[str] = set()
    pairs: list[tuple[str, float]] = []
    for gene, value in zip(genes, values):
        if gene not in seen:
            seen.add(gene)
            pairs.append((gene, value))

    background_genes = len(gene_to_terms)
    n = len(pairs)
    message: str | None = None

    if background_genes == 0:
        message = (
            f"No {ontology.upper()} annotations are available; "
            "the gene_annotations table is empty or missing for this ontology."
        )
        return EnrichmentGseaCalculationResponse(
            mode="gsea",
            ontology=ontology,
            input_genes=n,
            background_genes=0,
            terms=[],
            message=message,
        )

    if n == 0:
        message = "No input genes with values were provided; no GSEA could be computed."
        return EnrichmentGseaCalculationResponse(
            mode="gsea",
            ontology=ontology,
            input_genes=0,
            background_genes=background_genes,
            terms=[],
            message=message,
        )

    # Ranked list: value descending, ties broken by gene id for determinism.
    ranked = sorted(pairs, key=lambda pv: (-pv[1], pv[0]))

    # Term → positions of its member genes within the ranked list.
    term_positions: dict[str, list[int]] = {}
    for idx, (gene, _value) in enumerate(ranked):
        for term_id in gene_to_terms.get(gene, ()):
            term_positions.setdefault(term_id, []).append(idx)

    n_ranked = len(ranked)
    stats: list[_GseaTermStats] = []
    for term_id, positions in term_positions.items():
        k = len(positions)
        # k == 0 cannot occur (positions are built from members); k >= n is
        # degenerate (no background steps) and skipped.
        if k < min_genes or k >= n_ranked:
            continue
        es, nes, p_value = gsea_term_stat(positions, k=k, n=n_ranked)
        stats.append(
            _GseaTermStats(
                term_id=term_id,
                name=term_names.get(term_id, term_id),
                es=es,
                nes=nes,
                p_value=p_value,
                size=k,
                member_genes=[ranked[i][0] for i in positions],
            )
        )

    if not stats and message is None:
        message = (
            f"No {ontology.upper()} term reached min_genes={min_genes} members "
            "in the ranked input; no GSEA could be computed."
        )

    # BH correction across every tested term, then filter by raw p-value.
    q_values = benjamini_hochberg([s.p_value for s in stats])

    significant = [
        (s, q)
        for s, q in zip(stats, q_values)
        if s.p_value <= p_threshold
    ]
    significant.sort(key=lambda sq: (sq[1], sq[0].p_value, sq[0].term_id))

    terms = [
        EnrichmentGseaTerm(
            id=s.term_id,
            name=s.name,
            es=s.es,
            nes=s.nes,
            p_value=s.p_value,
            q_value=q,
            size=s.size,
            genes=s.member_genes[:MAX_TERM_GENES],
        )
        for s, q in significant[:max_terms]
    ]
    return EnrichmentGseaCalculationResponse(
        mode="gsea",
        ontology=ontology,
        input_genes=n,
        background_genes=background_genes,
        terms=terms,
        message=message,
    )


# ---------------------------------------------------------------------------
# Orchestration (called by the API route)
# ---------------------------------------------------------------------------


async def run_enrichment(
    db: AsyncSession,
    *,
    assembly_id: int,
    release_id: int,
    genes: list[str],
    ontology: Ontology,
    p_threshold: float,
    max_terms: int,
) -> EnrichmentResponse:
    """Load annotations for *ontology* and compute the ORA result.

    ``background_genes`` is the number of distinct genes annotated for the
    requested ontology in the selected assembly — not limited to input genes.
    Input genes without annotations are excluded from the tested set.
    """
    assembly = await _resolve_assembly(db, assembly_id, release_id)
    gene_to_terms, term_names = await fetch_annotations(
        db, ontology, assembly_id=assembly_id, release_id=release_id
    )
    annotation_source = await fetch_annotation_source(
        db, ontology, assembly_id=assembly_id, release_id=release_id
    )

    result = compute_enrichment(
        genes,
        gene_to_terms,
        term_names,
        ontology=ontology,
        p_threshold=p_threshold,
        max_terms=max_terms,
    )
    return EnrichmentResponse(
        assembly_id=assembly.id,
        release_id=release_id,
        assembly_name=assembly.name,
        assembly_version=assembly.version,
        annotation_source=annotation_source,
        **result.model_dump(),
    )


async def run_gsea_enrichment(
    db: AsyncSession,
    *,
    assembly_id: int,
    release_id: int,
    genes: list[str],
    values: list[float],
    ontology: Ontology,
    p_threshold: float,
    max_terms: int,
    min_genes: int,
) -> EnrichmentGseaResponse:
    """Load annotations for *ontology* and compute the GSEA result."""
    assembly = await _resolve_assembly(db, assembly_id, release_id)
    gene_to_terms, term_names = await fetch_annotations(
        db, ontology, assembly_id=assembly_id, release_id=release_id
    )
    annotation_source = await fetch_annotation_source(
        db, ontology, assembly_id=assembly_id, release_id=release_id
    )

    result = compute_gsea_enrichment(
        genes,
        values,
        gene_to_terms,
        term_names,
        ontology=ontology,
        p_threshold=p_threshold,
        max_terms=max_terms,
        min_genes=min_genes,
    )
    return EnrichmentGseaResponse(
        assembly_id=assembly.id,
        release_id=release_id,
        assembly_name=assembly.name,
        assembly_version=assembly.version,
        annotation_source=annotation_source,
        **result.model_dump(),
    )


async def _resolve_assembly(
    db: AsyncSession, assembly_id: int, release_id: int
) -> Assembly:
    result = await db.execute(
        select(Assembly).where(
            Assembly.id == assembly_id,
            Assembly.release_id == release_id,
        )
    )
    assembly = result.scalars().first()
    if assembly is None:
        raise NotFoundError(f"Assembly {assembly_id} not found")
    return assembly


__all__ = [
    "ANNOTATION_TABLE",
    "benjamini_hochberg",
    "compute_enrichment",
    "compute_gsea_enrichment",
    "fetch_annotation_source",
    "fetch_annotations",
    "gsea_term_stat",
    "hypergeom_sf",
    "run_enrichment",
    "run_gsea_enrichment",
]
