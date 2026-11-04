#!/usr/bin/env python3
"""Fail when the Rust bio-core contract is inconsistent or the wheel is absent.

Two independent checks, so a missing prerequisite is reported as a failure,
never as a skipped pass:

1. Static (any Python 3): the crate declares a pinned toolchain, its lock file
   is committed, the CI job is registered in the shared dispatcher, and the
   verification script actually installs + imports the wheel.
2. Runtime (CPython 3.15 with the wheel installed): import the compiled
   extension and execute real scientific assertions.

Usage:
    python3 scripts/check_bio_core_wheel.py --static
    python3 scripts/check_bio_core_wheel.py --runtime
    python3 scripts/check_bio_core_wheel.py            # both
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "packages" / "bio-core"


def check_static() -> int:
    errors: list[str] = []
    required = (
        "Cargo.toml",
        "Cargo.lock",
        "rust-toolchain.toml",
        "pyproject.toml",
        "src/lib.rs",
    )
    for name in required:
        if not (CRATE / name).is_file():
            errors.append(f"missing {CRATE / name}")

    toolchain = (CRATE / "rust-toolchain.toml").read_text(encoding="utf-8")
    if "channel" not in toolchain:
        errors.append("rust-toolchain.toml does not pin a channel")
    if (CRATE / "Cargo.toml").is_file():
        cargo = (CRATE / "Cargo.toml").read_text(encoding="utf-8")
        for dep in ("bio =", "noodles =", "rust-lapper =", "bio-seq =", "pyo3 ="):
            if dep not in cargo:
                errors.append(f"Cargo.toml missing pinned dependency {dep!r}")

    steps = (ROOT / "scripts" / "ci-job-steps.sh").read_text(encoding="utf-8")
    if "bio-core" not in steps or "bio_core_run()" not in steps:
        errors.append("bio-core job is not registered in scripts/ci-job-steps.sh")
    verify = (ROOT / "scripts" / "verify-bio-core.sh").read_text(encoding="utf-8")
    for marker in ("maturin build", "import soymutdb_bio_core", "-m pytest", "--locked"):
        if marker not in verify:
            errors.append(f"verify-bio-core.sh missing {marker!r}")

    for message in errors:
        print(f"FAIL: {message}", file=sys.stderr)
    if errors:
        return 1
    print("bio-core static contract: OK")
    return 0


def check_runtime() -> int:
    if importlib.util.find_spec("soymutdb_bio_core") is None:
        print(
            "FAIL: compiled soymutdb_bio_core wheel is not installed "
            "(sequence tools must fail closed; a missing wheel cannot pass smoke)",
            file=sys.stderr,
        )
        return 1
    import soymutdb_bio_core as core

    cap = core.capabilities()
    assert cap["engine"] == "soymutdb-bio-core", cap
    assert cap["genetic_codes"] == [1], "only implemented tables may be advertised"
    assert core.reverse_complement("ATGCRY") == "RYGCAT"
    assert core.sequence_statistics("ACGTNN")["denominator"] == 4
    assert core.kmer_counts("ACGTACGTNACG", 4)["distinct_kmers"] == 3
    assert core.translate_sequence("ATGAAATAA")["protein"] == "MK*"
    assert core.align_pairwise("ACGT", "ACGT")["cigar"] == "4M"
    q = core.overlap_intervals([(10, 20, 0), (10, 20, 1)], [(10, 20)])[0]
    assert q["overlap_count"] == 2 and q["covered_bp"] == 10
    print(f"bio-core runtime wheel: OK ({cap['engine_version']})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true")
    parser.add_argument("--runtime", action="store_true")
    args = parser.parse_args()
    both = not args.static and not args.runtime
    rc = 0
    if args.static or both:
        rc |= check_static()
    if args.runtime or both:
        rc |= check_runtime()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
