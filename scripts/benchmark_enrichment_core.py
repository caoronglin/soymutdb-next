#!/usr/bin/env python3
"""Reproducible numerical-core benchmark; synthetic results are not API latency.

Run with the API environment. --cases accepts JSON rows [N, K, n, k] derived
from a release/assembly-scoped annotation workload. The default is synthetic.
Baseline code is extracted from the specified git commit, never overwritten.
"""

from __future__ import annotations

import argparse
import ast
import cProfile
import io
import json
import math
import platform
import pstats
import random
import statistics
import subprocess
import time
from pathlib import Path

import scipy
from app.services.enrichment_service import (
    benjamini_hochberg,
    compute_enrichment,
    hypergeom_sf,
)
from scipy.stats import hypergeom


def _baseline(ref: str):
    source = subprocess.run(
        ["git", "show", f"{ref}:apps/api/app/services/enrichment_service.py"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    tree = ast.parse(source)
    names = {"_log_pmf", "_logsumexp", "hypergeom_sf"}
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {"math": math, "_MAX_TAIL_STEPS": 100_000}
    # Trusted repository functions only; historical code never becomes a runtime owner.
    exec(  # noqa: S102
        compile(ast.Module(body=nodes, type_ignores=[]), "<git-baseline>", "exec"),
        namespace,
    )
    return namespace["hypergeom_sf"]


def _measure(function, samples: int):
    function()
    times = []
    for _ in range(samples):
        start = time.perf_counter()
        function()
        times.append(time.perf_counter() - start)
    return {
        "median_seconds": statistics.median(times),
        "min_seconds": min(times),
        "max_seconds": max(times),
        "spread_seconds": max(times) - min(times),
        "samples": samples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=11)
    parser.add_argument("--baseline-ref", default="7ec14b41f")
    parser.add_argument("--cases", type=Path)
    args = parser.parse_args()
    if args.samples < 3:
        parser.error("at least three measured samples are required")
    cases = (
        json.loads(args.cases.read_text())
        if args.cases
        else [
            [56000, K, 500, max(1, int(500 * K / 56000) + 2)]
            for K in (5, 20, 50, 100, 500, 2000, 10000)
        ]
        * 100
    )
    baseline = _baseline(args.baseline_ref)
    functions = {
        "baseline_python": lambda: [baseline(*case) for case in cases],
        "current_python": lambda: [hypergeom_sf(*case) for case in cases],
        "scipy_scalar": lambda: [
            float(hypergeom.sf(k - 1, N, K, n)) for N, K, n, k in cases
        ],
        "scipy_batch": lambda: hypergeom.sf(
            [row[3] - 1 for row in cases],
            *[[row[j] for row in cases] for j in range(3)],
        ),
    }
    timings = {name: _measure(fn, args.samples) for name, fn in functions.items()}
    rng = random.Random(17)
    pvalues = [rng.random() for _ in range(10000)]
    timings["bh_10000"] = _measure(lambda: benjamini_hochberg(pvalues), args.samples)
    # Deterministic in-memory pipeline profile, excluding annotation SQL loading.
    mapping = {
        f"g{i}": {f"t{(i * 17 + j) % 700}" for j in range(4)} for i in range(56000)
    }
    run = lambda: compute_enrichment(
        [f"g{i}" for i in range(500)],
        mapping,
        {},
        ontology="go",
        p_threshold=1,
    )
    timings["synthetic_ora_pipeline"] = _measure(run, args.samples)
    profile = cProfile.Profile()
    profile.runcall(run)
    stream = io.StringIO()
    pstats.Stats(profile, stream=stream).sort_stats("cumulative").print_stats(12)
    print(
        json.dumps(
            {
                "workload_kind": "supplied_cases" if args.cases else "synthetic",
                "case_count": len(cases),
                "python": platform.python_version(),
                "scipy": scipy.__version__,
                "baseline_ref": args.baseline_ref,
                "timings": timings,
                "synthetic_profile": stream.getvalue(),
                "rust_gate": "needs_real_workload_profile_and_candidate_end_to_end_comparison",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
