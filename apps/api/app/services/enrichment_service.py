"""GO/KEGG enrichment analysis service.

Implements two analysis modes over the ``gene_annotations`` table
(``gene_id``, ``term_id``, ``term_name``, ``ontology`` columns):

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

The table is probed with ``inspect().has_table()`` first: when it does not
exist or holds no rows for the requested ontology, the service degrades
gracefully to an explicit empty result with a human-readable ``message`` —
never an error.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.enrichment import (
    MAX_TERM_GENES,
    EnrichmentGseaResponse,
    EnrichmentGseaTerm,
    EnrichmentResponse,
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
    db: AsyncSession, ontology: Ontology
) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Load gene → term mapping from the ``gene_annotations`` table.

    Returns ``(gene_to_terms, term_names)`` where ``gene_to_terms`` maps each
    annotated gene id to the set of its term ids for *ontology*, and
    ``term_names`` maps term id → display name.  When the table is missing or
    contains no rows for the ontology, both mappings are empty (the caller
    turns this into an explicit empty result with a message).
    """
    try:
        connection = await db.connection()
        has_table = await connection.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table(ANNOTATION_TABLE)
        )
    except Exception:
        # Session unusable (e.g. mocked in tests) — treat as no annotations.
        return {}, {}

    if not has_table:
        return {}, {}

    stmt = text(
        "SELECT gene_id, term_id, term_name "
        f"FROM {ANNOTATION_TABLE} WHERE ontology = :ontology"
    )
    result = await db.execute(stmt, {"ontology": ontology})

    gene_to_terms: dict[str, set[str]] = {}
    term_names: dict[str, str] = {}
    for gene_id, term_id, term_name in result.all():
        term_id = str(term_id)
        gene_to_terms.setdefault(str(gene_id), set()).add(term_id)
        term_names.setdefault(term_id, str(term_name) if term_name else term_id)
    return gene_to_terms, term_names


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
) -> EnrichmentResponse:
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
        return EnrichmentResponse(
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
        return EnrichmentResponse(
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
    return EnrichmentResponse(
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
) -> EnrichmentGseaResponse:
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
        return EnrichmentGseaResponse(
            mode="gsea",
            ontology=ontology,
            input_genes=n,
            background_genes=0,
            terms=[],
            message=message,
        )

    if n == 0:
        message = "No input genes with values were provided; no GSEA could be computed."
        return EnrichmentGseaResponse(
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
    return EnrichmentGseaResponse(
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
    genes: list[str],
    ontology: Ontology,
    p_threshold: float,
    max_terms: int,
) -> EnrichmentResponse:
    """Load annotations for *ontology* and compute the ORA result.

    ``background_genes`` is the number of distinct genes annotated for the
    requested ontology — i.e. the full annotated set, not limited to the
    input genes.  Input genes without annotations are simply excluded from
    the tested set (and reported via the message when none remain).
    """
    gene_to_terms, term_names = await fetch_annotations(db, ontology)

    return compute_enrichment(
        genes,
        gene_to_terms,
        term_names,
        ontology=ontology,
        p_threshold=p_threshold,
        max_terms=max_terms,
    )


async def run_gsea_enrichment(
    db: AsyncSession,
    *,
    genes: list[str],
    values: list[float],
    ontology: Ontology,
    p_threshold: float,
    max_terms: int,
    min_genes: int,
) -> EnrichmentGseaResponse:
    """Load annotations for *ontology* and compute the GSEA result."""
    gene_to_terms, term_names = await fetch_annotations(db, ontology)

    return compute_gsea_enrichment(
        genes,
        values,
        gene_to_terms,
        term_names,
        ontology=ontology,
        p_threshold=p_threshold,
        max_terms=max_terms,
        min_genes=min_genes,
    )


__all__ = [
    "ANNOTATION_TABLE",
    "benjamini_hochberg",
    "compute_enrichment",
    "compute_gsea_enrichment",
    "fetch_annotations",
    "gsea_term_stat",
    "hypergeom_sf",
    "run_enrichment",
    "run_gsea_enrichment",
]
