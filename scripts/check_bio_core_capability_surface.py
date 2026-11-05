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
from the paths ``packages/api-client/openapi.json`` actually serves under the
spec §7.1 roster prefixes (minus GET-only descriptions), format labels and their
validator names come from the ``/inspect`` dispatch table. That way another PR
adding a genuine new route + advertised program stays green without editing this
guard.

The program side is deliberately read from the OpenAPI snapshot and not from the
``@router.post`` declarations. Deriving it from the router made this guard blind
in exactly the way it exists to prevent: a route served by another module
(``/tools/intervals/overlap``) never appears there, and ``/tools/sequence/inspect``
was filtered out by request, so the advertised roster could omit both while every
gate stayed green. The document is the surface a client actually sees. On top of
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
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PY = ROOT / "apps/api/app/schemas/sequence_tools.py"
OPENAPI = ROOT / "packages/api-client/openapi.json"
INSPECT_PY = ROOT / "apps/api/app/services/format_inspect_service.py"
BINDINGS_RS = ROOT / "packages/bio-core/src/bindings.rs"

#: Path prefixes the ``programs`` roster is responsible for (spec §7.1). BLAST,
#: seqfetch, ld, enrichment and the other pre-existing /tools routers are
#: outside that table; folding them in would turn an honest roster into a false
#: claim about routers it never described.
ROSTER_PREFIXES: tuple[str, ...] = ("tools/sequence/", "tools/intervals/")

# PyO3 functions that MUST stay exported. These are the kernel side of the
# surface; a deletion here means a compute/validator path can no longer work.
# The labels are only used for readable error messages -- the surface itself is
# derived from the served document and the /inspect dispatch table, not from this
# map.
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
    # Labels are path segments: hyphens and slashes both occur
    # (``reverse-complement``, ``intervals/overlap``).
    return re.findall(r'"([a-z][a-z0-9/-]*)"', body)


def advertised_formats(schema: str) -> list[str]:
    body = _one_block(
        r"formats:\s*list\[str\]\s*=\s*Field\(default_factory=lambda:\s*\[(.*?)\]\)",
        schema,
        label="formats",
    )
    return re.findall(r'"([a-z][a-z0-9]*)"', body)


def served_programs(doc: str) -> list[str]:
    """Compute paths the OpenAPI snapshot actually serves under the roster prefixes.

    ``/tools/sequence/kmers`` -> ``kmers`` (what a client appends to the router
    prefix); ``/tools/intervals/overlap`` keeps its namespace, because the
    roster is flat and that path is not under ``/tools/sequence/``. GET-only
    entries are descriptions, not compute programs.
    """
    paths = json.loads(doc)["paths"]
    out: list[str] = []
    for path, entry in paths.items():
        if not path.startswith("/api/v1/"):
            continue
        relative = path[len("/api/v1/"):]
        if not relative.startswith(ROSTER_PREFIXES):
            continue
        if set(entry) == {"get"}:
            continue
        out.append(
            relative.removeprefix("tools/sequence/")
            if relative.startswith("tools/sequence/")
            else relative.removeprefix("tools/")
        )
    return out


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
        routes = served_programs(sources[str(OPENAPI)])
        exported = kernel_functions(sources[str(BINDINGS_RS)])
        dispatch = inspect_dispatch(sources[str(INSPECT_PY)])
    except ValueError as exc:
        return [str(exc)]

    if not programs or not formats or not routes or not dispatch:
        errors.append("a capability source is empty; refusing a vacuous pass")
        return errors

    # 1. Advertised programs == the compute paths the document actually serves.
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
        for path in (SCHEMA_PY, OPENAPI, INSPECT_PY, BINDINGS_RS)
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
        (
            "drop a route from the document",
            str(OPENAPI),
            '"/api/v1/tools/sequence/kmers"',
            '"/api/v1/tools/sequence/kmers-gone"',
        ),
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
    grown[str(OPENAPI)] = base[str(OPENAPI)].replace(
        '"/api/v1/tools/sequence/inspect"',
        '"/api/v1/tools/sequence/newtool": {"post": {}},\n'
        '    "/api/v1/tools/sequence/inspect"',
        1,
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
