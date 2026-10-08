#!/usr/bin/env python3
"""M0 workload profiler for the public enrichment path.

Purpose
-------
The DIAMOND/Biopython/pyDEG/Rust plan gates a Rust statistical core on *real*
enrichment traffic: a request set with explicit ``assembly``/``release``/
``ontology`` scope, a recorded source checksum, and stage-separated timings.
This script produces that evidence, or refuses to produce it.

Design rules (deliberate, so the output cannot be mistaken for a result)
------------------------------------------------------------------------
* Database replay (the default, also selected by ``--real``) **fails closed**
  without scoped annotation rows and provenance, reporting ``unavailable``.
  A successful ``database_replay`` report is not evidence of real user traffic
  or an authentic upstream dataset; the operator must establish both separately.
* ``--synthetic`` only exercises the harness itself and is always labelled
  ``workload_kind: "synthetic"``.
* The staged SQL/mapping instrumentation is a manual replay. Numeric functions
  come from production, and calculation parity with the production entry point
  is asserted before reporting a successful database replay.
* Stage names map to the real request path:
  ``resolve_assembly`` → ``sql_annotations`` → ``mapping`` →
  ``provenance_source`` → ``numeric_core`` → ``serialization``.

Usage
-----
    PYTHONPATH=apps/api apps/api/.venv/bin/python \
        scripts/profile_enrichment_workload.py \
        --database-url postgresql+asyncpg://user:pass@host:5432/db \
        --ontology go --repeats 5 --concurrency 4 \
        --out .validation/m0-real-profile.json

    # harness self-check without a database (never a workload claim)
    PYTHONPATH=apps/api apps/api/.venv/bin/python \
        scripts/profile_enrichment_workload.py --synthetic \
        --out .validation/m0-harness-selfcheck.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import random
import resource
import statistics
import sys
import time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.services import enrichment_service as service
from app.services.enrichment_service import (
    compute_enrichment,
    fetch_annotation_source,
    fetch_annotations,
    run_enrichment,
)

ONTOLOGIES = ("go", "kegg")

#: Stages reported separately, in real request order.
STAGES = (
    "resolve_assembly",
    "sql_annotations",
    "mapping",
    "provenance_source",
    "numeric_core",
    "serialization",
)


# ---------------------------------------------------------------------------
# Resource sampling
# ---------------------------------------------------------------------------


def current_rss_bytes() -> int:
    """Resident set size from /proc/self/statm (resident pages * page size)."""
    with open("/proc/self/statm", encoding="ascii") as handle:
        resident_pages = int(handle.read().split()[1])
    return resident_pages * os.sysconf("SC_PAGE_SIZE")


def peak_rss_bytes() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def summarize(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "samples": len(ordered),
        "median_seconds": statistics.median(ordered),
        "min_seconds": ordered[0],
        "max_seconds": ordered[-1],
        "p95_seconds": ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1) + 0.5))],
    }


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def environment_report() -> dict[str, Any]:
    packages = (
        "fastapi",
        "pydantic",
        "sqlalchemy",
        "asyncpg",
        "numpy",
        "scipy",
        "biopython",
    )
    libraries: dict[str, str | None] = {}
    for name in packages:
        try:
            libraries[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            libraries[name] = None
    binaries: dict[str, str | None] = {}
    from shutil import which

    for name in ("rustc", "cargo", "docker", "diamond"):
        binaries[name] = which(name)
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": {
            "version": sys.version.split()[0],
            "implementation": platform.python_implementation(),
        },
        "libraries": libraries,
        "binaries_on_path": binaries,
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
            "cpu_count": os.cpu_count(),
        },
        "thread_budget": {
            "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS"),
            "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS"),
        },
    }


# ---------------------------------------------------------------------------
# Scoped annotation discovery
# ---------------------------------------------------------------------------


async def discover_scopes(engine, ontology: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """List annotation sets for *ontology* whose stored row count matches reality.

    Mirrors ``fetch_annotation_source``'s provenance rule: a snapshot whose
    declared ``row_count`` disagrees with the scoped rows is not a usable source
    and must not become workload evidence.
    """
    from sqlalchemy import text

    inventory: dict[str, Any] = {"probed": "gene_annotation_sets + gene_annotations"}
    async with engine.connect() as connection:
        presence = await connection.execute(
            text("SELECT to_regclass('public.gene_annotation_sets'), "
                 "to_regclass('public.gene_annotations')")
        )
        sets_table, rows_table = presence.first()
        inventory["annotation_sets_table_present"] = bool(sets_table)
        inventory["annotations_table_present"] = bool(rows_table)
        if not sets_table:
            inventory["reason"] = "gene_annotation_sets table is absent"
            return [], inventory
        result = await connection.execute(
            text(
                "SELECT id, assembly_id, release_id, ontology, source_name, "
                "source_version, source_url, source_sha256, importer_version, row_count "
                "FROM gene_annotation_sets WHERE ontology = :ontology ORDER BY id"
            ),
            {"ontology": ontology},
        )
        rows = result.all()
        inventory["annotation_set_rows_for_ontology"] = len(rows)

    usable: list[dict[str, Any]] = []
    mismatched: list[dict[str, Any]] = []
    for row in rows:
        scope = {
            "annotation_set_id": row.id,
            "assembly_id": row.assembly_id,
            "release_id": row.release_id,
            "ontology": row.ontology,
            "source_name": row.source_name,
            "source_version": row.source_version,
            "source_url": row.source_url,
            "source_sha256": row.source_sha256,
            "importer_version": row.importer_version,
            "declared_row_count": int(row.row_count),
        }
        async with engine.connect() as connection:
            actual = await connection.execute(
                text(
                    "SELECT count(*) FROM gene_annotations "
                    "WHERE ontology = :ontology AND assembly_id = :assembly_id "
                    "AND release_id = :release_id"
                ),
                {
                    "ontology": row.ontology,
                    "assembly_id": row.assembly_id,
                    "release_id": row.release_id,
                },
            )
            scope["scoped_row_count"] = int(actual.scalar_one())
        if scope["scoped_row_count"] == scope["declared_row_count"] and scope["scoped_row_count"] > 0:
            usable.append(scope)
        else:
            mismatched.append(scope)
    inventory["provenance_mismatched_sets"] = len(mismatched)
    inventory["mismatch_detail"] = mismatched[:10]
    if not usable:
        if rows:
            inventory["reason"] = (
                "annotation sets exist for this ontology but none has a positive "
                "scoped row count equal to its declared provenance row_count"
            )
        else:
            inventory["reason"] = "no annotation set rows for this ontology"
    return usable, inventory


# ---------------------------------------------------------------------------
# Stage-separated real request
# ---------------------------------------------------------------------------


def build_case_export(
    gene_to_terms: dict[str, set[str]],
    request_genes: list[str],
    *,
    p_threshold: float,
) -> dict[str, Any]:
    """Freeze the integers a Rust candidate must reproduce, plus a checksum.

    ``[N, K, n, k]`` follows the service convention: ``N`` background genes,
    ``K`` background genes in the term, ``n`` annotated unique input genes,
    ``k`` input genes in the term. Unannotated input is counted in the request
    shape but excluded from the hypergeometric population, as in production.
    """
    background = set(gene_to_terms)
    unique_input = list(dict.fromkeys(request_genes))
    terms: dict[str, set[str]] = {}
    for gene in unique_input:
        for term in gene_to_terms.get(gene, ()):
            terms.setdefault(term, set()).add(gene)
    # ``K`` needs every annotated gene per term, which the input-only view above
    # does not carry, so build the term -> background gene index explicitly.
    term_background: dict[str, set[str]] = {}
    for gene, gene_terms in gene_to_terms.items():
        for term in gene_terms:
            term_background.setdefault(term, set()).add(gene)
    annotated_input = [gene for gene in unique_input if gene in background]
    term_ids = sorted(terms)
    cases = [
        [len(background), len(term_background[term]), len(annotated_input), len(terms[term])]
        for term in term_ids
    ]
    for case in cases:
        service.hypergeom_sf(*case)
    payload = {
        "format_version": 2,
        "convention": "[N, K, n, k] = background, term background, annotated input, term input",
        "background_genes": len(background),
        "input_genes": len(unique_input),
        "annotated_input_genes": len(annotated_input),
        "request_genes": unique_input,
        "term_ids": term_ids,
        "tested_terms": len(cases),
        "p_threshold": p_threshold,
        "cases": cases,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["cases_sha256"] = hashlib.sha256(blob).hexdigest()
    payload["request_genes_sha256"] = hashlib.sha256(
        "\n".join(sorted(unique_input)).encode()
    ).hexdigest()
    return payload


async def time_real_request(
    session_factory, scope: dict[str, Any], request_genes: list[str], *, ontology: str,
    p_threshold: float, max_terms: int,
) -> tuple[dict[str, float], Any, str]:
    """Replay the request with manual SQL/mapping instrumentation.

    The orchestration entry point below checks this replay against production;
    stage timings are instrumentation, not an independent production latency.
    """
    timings: dict[str, float] = {}
    async with session_factory() as session:
        started = time.perf_counter()
        await service._resolve_assembly(
            session, scope["assembly_id"], scope["release_id"]
        )
        timings["resolve_assembly"] = time.perf_counter() - started

        started = time.perf_counter()
        rows_result = await session.execute(
            _annotation_query(ontology, scope["assembly_id"], scope["release_id"])
        )
        raw_rows = rows_result.all()
        timings["sql_annotations"] = time.perf_counter() - started

        started = time.perf_counter()
        gene_to_terms: dict[str, set[str]] = {}
        term_names: dict[str, str] = {}
        for gene_id, term_id, term_name in raw_rows:
            term_id = str(term_id)
            gene_to_terms.setdefault(str(gene_id), set()).add(term_id)
            term_names.setdefault(term_id, str(term_name) if term_name else term_id)
        timings["mapping"] = time.perf_counter() - started

        started = time.perf_counter()
        await fetch_annotation_source(
            session, ontology,
            assembly_id=scope["assembly_id"], release_id=scope["release_id"],
        )
        timings["provenance_source"] = time.perf_counter() - started

        started = time.perf_counter()
        result = compute_enrichment(
            request_genes, gene_to_terms, term_names,
            ontology=ontology, p_threshold=p_threshold, max_terms=max_terms,
        )
        timings["numeric_core"] = time.perf_counter() - started

        started = time.perf_counter()
        serialized = result.model_dump_json()
        timings["serialization"] = time.perf_counter() - started
    return timings, result, serialized


def _annotation_query(ontology: str, assembly_id: int, release_id: int):
    from sqlalchemy import text

    return text(
        "SELECT gene_id, term_id, term_name "
        "FROM gene_annotations WHERE ontology = :ontology "
        "AND assembly_id = :assembly_id AND release_id = :release_id"
    ).bindparams(
        ontology=ontology, assembly_id=assembly_id, release_id=release_id
    )


# ---------------------------------------------------------------------------
# Synthetic harness self-check (never a workload claim)
# ---------------------------------------------------------------------------


def synthetic_annotation_map(
    *, genes: int = 56000, terms: int = 700, seed: int = 20261006
) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Soybean-scale shape with a fixed seed, for harness validation only."""
    rng = random.Random(seed)
    gene_ids = [f"GMA{i:06d}" for i in range(genes)]
    gene_to_terms: dict[str, set[str]] = {}
    term_names: dict[str, str] = {}
    for term_index in range(terms):
        term_id = f"GO:{term_index:07d}"
        term_names[term_id] = f"synthetic term {term_index}"
        members = rng.sample(gene_ids, rng.randint(5, 120))
        for gene in members:
            gene_to_terms.setdefault(gene, set()).add(term_id)
    return gene_to_terms, term_names


def time_synthetic_request(
    gene_to_terms: dict[str, set[str]],
    term_names: dict[str, str],
    request_genes: list[str],
    *,
    ontology: str,
    p_threshold: float,
    max_terms: int,
) -> tuple[dict[str, float], float]:
    timings: dict[str, float] = {}
    started = time.perf_counter()
    for gene_id, gene_terms in gene_to_terms.items():
        gene_to_terms.setdefault(str(gene_id), set()).update(gene_terms)
    timings["mapping"] = time.perf_counter() - started

    started = time.perf_counter()
    result = compute_enrichment(
        request_genes, gene_to_terms, term_names,
        ontology=ontology, p_threshold=p_threshold, max_terms=max_terms,
    )
    timings["numeric_core"] = time.perf_counter() - started

    started = time.perf_counter()
    serialized = result.model_dump_json()
    timings["serialization"] = time.perf_counter() - started
    return timings, len(serialized)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def run_real(args: argparse.Namespace) -> dict[str, Any]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(args.database_url, pool_pre_ping=True)
    try:
        scopes, inventory = await discover_scopes(engine, args.ontology)
        report: dict[str, Any] = {
            "workload_kind": "unavailable",
            "scope_request": {
                "database_url": _redact(args.database_url),
                "ontology": args.ontology,
                "repeats": args.repeats,
                "concurrency": args.concurrency,
                "input_genes": args.input_genes,
            },
            "annotation_inventory": inventory,
            "environment": environment_report(),
        }
        if not scopes:
            report["unavailable_reason"] = inventory.get(
                "reason", "no usable scoped annotation snapshot"
            )
            report["next_prerequisite"] = (
                "Import a release-scoped GO/KEGG snapshot into gene_annotation_sets "
                "+ gene_annotations (source_name/version/url/sha256/importer_version, "
                "row_count matching the scoped rows) before measuring a real workload."
            )
            return report

        scope = scopes[0]
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        # One unmeasured pass: build the replay input from the real scope.
        async with session_factory() as session:
            gene_to_terms, _names = await fetch_annotations(
                session, args.ontology,
                assembly_id=scope["assembly_id"], release_id=scope["release_id"],
            )
        if not gene_to_terms:
            report["unavailable_reason"] = "scoped annotation mapping resolved empty"
            return report

        background = sorted(gene_to_terms)
        rng = random.Random(args.seed)
        size = min(args.input_genes, len(background))
        request_genes = rng.sample(background, size)
        case_export = build_case_export(
            gene_to_terms, request_genes, p_threshold=args.p_threshold
        )

        stage_samples: dict[str, list[float]] = {stage: [] for stage in STAGES}
        end_to_end: list[float] = []
        rss_before = current_rss_bytes()
        serialized = ""
        for _ in range(args.repeats):
            started = time.perf_counter()
            timings, _result, serialized = await time_real_request(
                session_factory, scope, request_genes,
                ontology=args.ontology, p_threshold=args.p_threshold,
                max_terms=args.max_terms,
            )
            end_to_end.append(time.perf_counter() - started)
            for stage, elapsed in timings.items():
                stage_samples[stage].append(elapsed)

        concurrency_result = await run_concurrent(
            session_factory, scope, request_genes,
            ontology=args.ontology, p_threshold=args.p_threshold,
            max_terms=args.max_terms, concurrency=args.concurrency,
        )

        # Fail closed on replay drift; previously this comment had no assertion.
        async with session_factory() as session:
            production = await run_enrichment(
                session,
                assembly_id=scope["assembly_id"], release_id=scope["release_id"],
                genes=request_genes, ontology=args.ontology,
                p_threshold=args.p_threshold, max_terms=args.max_terms,
            )
        staged_fields = set(_result.model_dump())
        if production.model_dump(include=staged_fields) != _result.model_dump():
            raise RuntimeError("staged enrichment replay differs from the production result")
        return {
            "workload_kind": "database_replay",
            "production_calculation_parity": True,
            "scope": scope,
            "scope_selection": {
                "usable_sets": len(scopes),
                "chosen_annotation_set_id": scope["annotation_set_id"],
            },
            "annotation_inventory": inventory,
            "case_export": case_export,
            "result_shape": {
                "background_genes": production.background_genes,
                "input_genes": production.input_genes,
                "returned_terms": len(production.terms),
                "message": production.message,
            },
            "single_request": {
                "stages": {stage: summarize(samples) for stage, samples in stage_samples.items()},
                "end_to_end": summarize(end_to_end),
                "serialized_bytes": len(serialized),
                "measurement_path": "instrumented replay; serialization is calculation-only",
            },
            "concurrency": concurrency_result,
            "rss": {
                "before_bytes": rss_before,
                "after_bytes": current_rss_bytes(),
                "peak_bytes": peak_rss_bytes(),
                "growth_bytes": peak_rss_bytes() - rss_before,
            },
            "environment": environment_report(),
            "harness_disclosure": (
                "Request genes are a seeded sample from the database scope, not "
                "recorded user traffic. Database provenance does not establish "
                "upstream authenticity. Staged SQL/mapping are manual instrumentation; "
                "calculation parity is verified, and concurrency uses production."
            ),
        }
    finally:
        await engine.dispose()


async def run_concurrent(
    session_factory, scope, request_genes, *, ontology, p_threshold, max_terms, concurrency
) -> dict[str, Any]:
    async def one() -> float:
        started = time.perf_counter()
        async with session_factory() as session:
            await run_enrichment(
                session,
                assembly_id=scope["assembly_id"], release_id=scope["release_id"],
                genes=request_genes, ontology=ontology,
                p_threshold=p_threshold, max_terms=max_terms,
            )
        return time.perf_counter() - started

    started = time.perf_counter()
    latencies = await asyncio.gather(*[one() for _ in range(concurrency)])
    wall = time.perf_counter() - started
    stats = summarize(list(latencies))
    return {
        "concurrency": concurrency,
        "per_request": stats,
        "wall_seconds": wall,
        "rss_after_bytes": current_rss_bytes(),
        "peak_rss_bytes": peak_rss_bytes(),
    }


def run_synthetic(args: argparse.Namespace) -> dict[str, Any]:
    gene_to_terms, term_names = synthetic_annotation_map()
    background = sorted(gene_to_terms)
    rng = random.Random(args.seed)
    request_genes = rng.sample(background, min(args.input_genes, len(background)))
    stage_samples: dict[str, list[float]] = {stage: [] for stage in STAGES}
    end_to_end: list[float] = []
    rss_before = current_rss_bytes()
    payload_bytes = 0
    for _ in range(args.repeats):
        started = time.perf_counter()
        timings, payload_bytes = time_synthetic_request(
            gene_to_terms, term_names, request_genes,
            ontology=args.ontology, p_threshold=args.p_threshold,
            max_terms=args.max_terms,
        )
        end_to_end.append(time.perf_counter() - started)
        for stage, elapsed in timings.items():
            stage_samples[stage].append(elapsed)
    return {
        "workload_kind": "synthetic",
        "disclosure": (
            "Harness self-check only. Synthetic soybean-scale rows: NOT a real "
            "workload, NOT a Rust gate result, and not comparable to production "
            "traffic. SQL and provenance stages are absent by construction."
        ),
        "shape": {
            "background_genes": len(gene_to_terms),
            "terms": len(term_names),
            "input_genes": len(request_genes),
        },
        "case_export": build_case_export(
            gene_to_terms, request_genes, p_threshold=args.p_threshold
        ),
        "single_request": {
            "stages": {
                stage: summarize(samples)
                for stage, samples in stage_samples.items()
                if samples
            },
            "end_to_end": summarize(end_to_end),
            "serialized_bytes": payload_bytes,
        },
        "rss": {
            "before_bytes": rss_before,
            "after_bytes": current_rss_bytes(),
            "peak_bytes": peak_rss_bytes(),
        },
        "environment": environment_report(),
    }


def _redact(url: str) -> str:
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    credentials, _, host = rest.rpartition("@")
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", help="postgresql+asyncpg:// URL (required for --real)")
    parser.add_argument("--ontology", default="go", choices=ONTOLOGIES)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--input-genes", type=int, default=500)
    parser.add_argument("--p-threshold", type=float, default=0.05)
    parser.add_argument("--max-terms", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20261006)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--real", action="store_true", help="database replay (not real traffic proof)")
    mode.add_argument("--synthetic", action="store_true", help="harness self-check only")
    mode.add_argument(
        "--inventory",
        action="store_true",
        help="emit only the runtime/library/binary environment inventory; no database needed",
    )
    parser.add_argument("--out", help="write the JSON report here")
    args = parser.parse_args(argv)
    for name in ("repeats", "concurrency", "input_genes", "max_terms"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if not 0 <= args.p_threshold <= 1:
        parser.error("--p-threshold must be finite and between 0 and 1")

    if args.inventory:
        report = {"workload_kind": "inventory", "environment": environment_report()}
    elif args.synthetic:
        report = run_synthetic(args)
    else:
        if not args.database_url:
            parser.error("--real profiling needs --database-url")
        if not args.database_url.startswith("postgresql+asyncpg://"):
            parser.error("--database-url must use the postgresql+asyncpg:// scheme")
        report = asyncio.run(run_real(args))

    text = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
    # Unavailable real workloads are reported, not failed: the missing data is
    # the finding. A crash or an invalid scope still exits non-zero.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())