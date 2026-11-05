#!/usr/bin/env python3
"""Pin the advertised capability *surface* to the implemented one.

``GET /api/v1/tools/sequence/capabilities`` advertises two lists a client uses
to decide what the service can do: ``programs`` (the compute operations) and
``formats`` (the file formats ``/inspect`` accepts). The neighbouring numeric
parity guard (check_bio_core_capability_parity.py) only compares numbers and
labels that exist on BOTH sides, so dropping an entry from either list reads
exactly like "no difference": the Pydantic default is still a valid response,
the OpenAPI snapshot still reflects that response, and every gate stays green.

Deleting ``"kmers"`` from ``programs`` while ``POST /tools/sequence/kmers`` and
the Rust ``kmer_counts`` binding remain live is the concrete failure this guard
closes. Adding a program with no route would be the opposite lie.

The surface is DERIVED from committed bytes, not hardcoded: program labels come
from the ``@router.post`` declarations, format labels and their validator names
come from the ``/inspect`` dispatch table. That way another PR adding a genuine
new route + advertised program stays green without editing this guard. On top of
that derivation, the known PyO3 compute/validator kernels are a lower bound
that must remain exported, so a kernel-side deletion is caught too.

Nothing here imports the wheel, FastAPI or Rust: it reads source bytes only, so
it runs before the expensive build. ``--self-test`` injects one-sided mutations
into copies and asserts each is caught; the real check fails closed on a
missing or reshaped field.

Usage:
    python3 scripts/check_bio_core_capability_surface.py --self-test
    python3 scripts/check_bio_core_capability_surface.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PY = ROOT / "apps/api/app/schemas/sequence_tools.py"
ROUTES_PY = ROOT / "apps/api/app/api/v1/tools_sequence.py"
INSPECT_PY = ROOT / "apps/api/app/services/format_inspect_service.py"
BINDINGS_RS = ROOT / "packages/bio-core/src/bindings.rs"

# PyO3 functions that MUST stay exported. These are the kernel side of the
# surface; a deletion here means a compute/validator path can no longer work.
# The labels are only used for readable error messages -- the surface itself is
# derived from the routes and the /inspect dispatch table, not from this map.
COMPUTE_KERNELS = {
    "reverse_complement",
    "find_matches",
    "align_pairwise",
    "sequence_statistics",
    "find_orfs",
    "translate_sequence",
    "kmer_counts",
}
VALIDATOR_KERNELS = {"validate_fasta", "validate_fastq", "validate_bed"}


def _one_block(pattern: str, text: str, *, label: str) -> str:
    match = re.search(pattern, text, re.DOTALL)
    if match is None:
        raise ValueError(f"{label}: could not read advertised list / dispatch table")
    return match.group(1)


def advertised_programs(schema: str) -> list[str]:
    body = _one_block(
        r"programs:\s*list\[str\]\s*=\s*Field\(\s*default_factory=lambda:\s*\[(.*?)\]\s*\)",
        schema,
        label="programs",
    )
    return re.findall(r'"([a-z][a-z0-9-]*)"', body)


def advertised_formats(schema: str) -> list[str]:
    body = _one_block(
        r"formats:\s*list\[str\]\s*=\s*Field\(default_factory=lambda:\s*\[(.*?)\]\)",
        schema,
        label="formats",
    )
    return re.findall(r'"([a-z][a-z0-9]*)"', body)


def route_programs(routes: str) -> list[str]:
    """POST paths under /tools/sequence; /inspect is a format endpoint."""
    paths = re.findall(r'@router\.post\("([^"]+)"', routes)
    return [p.lstrip("/") for p in paths if p.lstrip("/") != "inspect"]


def kernel_functions(bindings: str) -> set[str]:
    """Function names actually exported by the PyO3 module."""
    return set(
        re.findall(r"add_function\(wrap_pyfunction!\(\s*(\w+)\s*,", bindings)
    )


def inspect_dispatch(service: str) -> dict[str, str]:
    """Format label -> kernel validator, read from the /inspect fn table."""
    block = _one_block(r"fn\s*=\s*\{(.*?)\}\[payload\.fmt\]", service, label="inspect dispatch")
    return dict(re.findall(r'"([a-z][a-z0-9]*)"\s*:\s*"(\w+)"', block))


def _drift(label: str, advertised: list[str], implemented: list[str]) -> list[str]:
    """Two-way set comparison that also rejects duplicates."""
    errors: list[str] = []
    if len(advertised) != len(set(advertised)):
        errors.append(f"{label}: advertised list contains duplicates")
    adv, impl = set(advertised), set(implemented)
    for name in sorted(adv - impl):
        errors.append(f"{label} {name!r}: advertised but not implemented")
    for name in sorted(impl - adv):
        errors.append(f"{label} {name!r}: implemented but not advertised")
    return errors


def check(sources: dict[str, str]) -> list[str]:
    """Return drift descriptions; empty list means the surface is honest."""
    errors: list[str] = []
    try:
        programs = advertised_programs(sources[str(SCHEMA_PY)])
        formats = advertised_formats(sources[str(SCHEMA_PY)])
        routes = route_programs(sources[str(ROUTES_PY)])
        exported = kernel_functions(sources[str(BINDINGS_RS)])
        dispatch = inspect_dispatch(sources[str(INSPECT_PY)])
    except ValueError as exc:
        return [str(exc)]

    if not programs or not formats or not routes or not dispatch:
        errors.append("a capability source is empty; refusing a vacuous pass")
        return errors

    # 1. Advertised programs == the POST routes actually served.
    errors.extend(_drift("program", programs, routes))
    # 2. Advertised formats == the /inspect dispatch keys actually routed.
    errors.extend(_drift("format", formats, list(dispatch)))
    # 3. Every dispatch value must name a live kernel validator.
    for label, fn in sorted(dispatch.items()):
        if fn not in exported:
            errors.append(f"format {label!r}: dispatch validator {fn!r} is not exported by the kernel")
    # 4. The known compute/validator kernels must remain exported (lower bound).
    for fn in sorted(COMPUTE_KERNELS | VALIDATOR_KERNELS):
        if fn not in exported:
            errors.append(f"kernel no longer exports {fn!r}; the capability surface lost its backend")
    return errors


def load_sources() -> dict[str, str]:
    return {
        str(path): path.read_text(encoding="utf-8")
        for path in (SCHEMA_PY, ROUTES_PY, INSPECT_PY, BINDINGS_RS)
    }


def self_test() -> int:
    """Every one-sided surface mutation must be caught; clean tree must pass."""
    base = load_sources()
    clean = check(base)
    if clean:
        print(f"FAIL self-test: clean tree drifts: {clean}")
        return 1

    # (label, source key, old, new). Each case changes exactly ONE side.
    cases: list[tuple[str, str, str, str]] = [
        ("drop an advertised program", str(SCHEMA_PY), '            "kmers",\n', ""),
        ("drop an advertised format", str(SCHEMA_PY), '"fasta", "fastq", "bed"', '"fasta", "fastq"'),
        ("advertise a phantom program", str(SCHEMA_PY), '            "kmers",\n', '            "kmers",\n            "phantom",\n'),
        ("advertise a phantom format", str(SCHEMA_PY), '"fasta", "fastq", "bed"', '"fasta", "fastq", "bed", "phantom"'),
        ("advertise a duplicate program", str(SCHEMA_PY), '            "kmers",\n', '            "kmers",\n            "kmers",\n'),
        ("drop a route", str(ROUTES_PY), '@router.post("/kmers", response_model=s.KmerResponse)\nasync def sequence_kmers(payload: s.KmerRequest) -> s.KmerResponse:\n    return await service.kmers(payload)\n', ""),
        ("drop a kernel binding", str(BINDINGS_RS), "    m.add_function(wrap_pyfunction!(kmer_counts, m)?)?;\n", ""),
        ("drop a validator binding", str(BINDINGS_RS), "    m.add_function(wrap_pyfunction!(validate_bed, m)?)?;\n", ""),
        ("drop an inspect dispatch entry", str(INSPECT_PY), '        "bed": "validate_bed",\n', ""),
        ("point a dispatch entry at a dead validator", str(INSPECT_PY), '"bed": "validate_bed"', '"bed": "validate_gone"'),
    ]
    failures = 0
    for label, path, old, new in cases:
        mutated = dict(base)
        text = mutated[path]
        if old not in text:
            print(f"FAIL {label}: anchor not found")
            failures += 1
            continue
        mutated[path] = text.replace(old, new, 1)
        found = check(mutated)
        if not found:
            print(f"FAIL {label}: drift was not caught")
            failures += 1
        else:
            print(f"PASS {label}: {found[0]}")

    # A legitimate addition (new route + new advertised program, no kernel
    # change) must stay GREEN: the surface is derived, not a fixed whitelist.
    grown = dict(base)
    grown[str(SCHEMA_PY)] = base[str(SCHEMA_PY)].replace(
        '            "kmers",\n', '            "kmers",\n            "newtool",\n'
    )
    grown[str(ROUTES_PY)] = base[str(ROUTES_PY)].replace(
        '@router.post("/inspect", response_model=s.FormatInspectResponse)',
        '@router.post("/newtool", response_model=s.KmerResponse)\n'
        'async def sequence_newtool(payload: s.KmerRequest) -> s.KmerResponse:\n'
        '    return await service.kmers(payload)\n\n\n'
        '@router.post("/inspect", response_model=s.FormatInspectResponse)',
    )
    if check(grown):
        print(f"FAIL legitimate extension was rejected: {check(grown)}")
        failures += 1
    else:
        print("PASS a genuine new route + advertised program stays green")

    print(f"collected {len(cases) + 1} / {len(cases) + 1 - failures} passed")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove one-sided drifts are caught")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    errors = check(load_sources())
    if errors:
        for error in errors:
            print(f"CAPABILITY SURFACE DRIFT: {error}", file=sys.stderr)
        print("advertised capability surface disagrees with the implementation", file=sys.stderr)
        return 1
    print("bio-core capability surface: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
