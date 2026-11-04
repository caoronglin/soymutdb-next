#!/usr/bin/env python3
"""Pin the advertised sequence-tool limits to the Rust kernel's own constants.

``GET /tools/sequence/capabilities`` reports the input limits a client must
respect (1 MiB inline sequence, 256 nt pattern, 1000 hits/regions, k 1..32,
the implemented genetic codes, and the two coordinate-system labels). Those
values live in two places: the Rust kernel owns them as the real enforcement
bounds, and ``apps/api/app/schemas/sequence_tools.py`` copies them into the
Pydantic response. Nothing compared the two, so a change to one side would
silently advertise a limit the other side does not enforce -- a client that
trusted the advertised bound would get a kernel rejection for input it was
told was valid, with no contract drift anywhere in the OpenAPI snapshot.

This guard reads committed sources only (no wheel, no Rust toolchain, no
FastAPI import), so it runs before the expensive build in the bio-core gate.
``--self-test`` injects one-sided drifts into copies of the sources and asserts
each is caught; the real check refuses to treat a missing field as a match.

Usage:
    python3 scripts/check_bio_core_capability_parity.py --self-test
    python3 scripts/check_bio_core_capability_parity.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEQUENCE_RS = ROOT / "packages/bio-core/src/sequence.rs"
INTERVALS_RS = ROOT / "packages/bio-core/src/intervals.rs"
TRANSLATION_RS = ROOT / "packages/bio-core/src/translation.rs"
BINDINGS_RS = ROOT / "packages/bio-core/src/bindings.rs"
SCHEMA_PY = ROOT / "apps/api/app/schemas/sequence_tools.py"

# (name, Rust source regex, Python source regex). Each pair must resolve to the
# SAME integer. The Rust side is the authority; the Python side is the copy.
NUMERIC_LIMITS: tuple[tuple[str, str, str], ...] = (
    (
        "max_inline_sequence",
        r"pub const MAX_INLINE_SEQUENCE:\s*usize\s*=\s*([\d_]+)",
        r"^MAX_INLINE_SEQUENCE\s*=\s*([\d_]+)",
    ),
    (
        "max_pattern",
        r"pub const MAX_PATTERN:\s*usize\s*=\s*([\d_]+)",
        r"^MAX_PATTERN\s*=\s*([\d_]+)",
    ),
    (
        "max_hits",
        r"pub const MAX_HITS:\s*usize\s*=\s*([\d_]+)",
        r"^MAX_HITS\s*=\s*([\d_]+)",
    ),
    (
        "max_regions",
        r"pub const MAX_REGIONS:\s*usize\s*=\s*([\d_]+)",
        r"^MAX_REGIONS\s*=\s*([\d_]+)",
    ),
)


def _one_int(pattern: str, text: str, *, label: str, multiline: bool = False) -> int:
    flags = re.MULTILINE if multiline else 0
    matches = re.findall(pattern, text, flags)
    if len(matches) != 1:
        raise ValueError(
            f"{label}: expected exactly one match for {pattern!r}, got {len(matches)}"
        )
    return int(matches[0].replace("_", ""))


def _rust_numeric_limits(sources: dict[str, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    rust_by_name = {
        "max_inline_sequence": (SEQUENCE_RS, "MAX_INLINE_SEQUENCE"),
        "max_pattern": (SEQUENCE_RS, "MAX_PATTERN"),
        "max_hits": (INTERVALS_RS, "MAX_HITS"),
        "max_regions": (INTERVALS_RS, "MAX_REGIONS"),
    }
    for name, rs_pattern, _ in NUMERIC_LIMITS:
        path, _const = rust_by_name[name]
        out[name] = _one_int(rs_pattern, sources[str(path)], label=f"rust {name}")
    return out


def _python_numeric_limits(schema: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for name, _, py_pattern in NUMERIC_LIMITS:
        out[name] = _one_int(py_pattern, schema, label=f"python {name}", multiline=True)
    return out


def _rust_literals(sources: dict[str, str]) -> dict[str, object]:
    bindings = sources[str(BINDINGS_RS)]
    translation = sources[str(TRANSLATION_RS)]
    k_range = re.search(r'd\.set_item\("k_range",\s*\((\d+),\s*(\d+)\)\)', bindings)
    if not k_range:
        raise ValueError("rust k_range: could not read capabilities() k_range literal")
    code = re.search(r"pub const STANDARD_GENETIC_CODE:\s*u32\s*=\s*(\d+)", translation)
    if not code:
        raise ValueError("rust genetic_codes: STANDARD_GENETIC_CODE constant missing")
    if "vec![STANDARD_GENETIC_CODE]" not in translation:
        raise ValueError("rust genetic_codes: implemented_genetic_codes() no longer returns one code")
    internal = re.search(
        r'd\.set_item\("coordinate_system_internal",\s*"([^"]+)"\)', bindings
    )
    public = re.search(r'd\.set_item\("coordinate_system_public",\s*"([^"]+)"\)', bindings)
    if not internal or not public:
        raise ValueError("rust coordinate_system: capabilities() labels missing")
    return {
        "k_range": (int(k_range.group(1)), int(k_range.group(2))),
        "genetic_codes": [int(code.group(1))],
        "coordinate_system_internal": internal.group(1),
        "coordinate_system_public": public.group(1),
    }


def _python_literals(schema: str) -> dict[str, object]:
    k_range = re.search(r"k_range:\s*tuple\[int,\s*int\]\s*=\s*\((\d+),\s*(\d+)\)", schema)
    codes = re.search(r"genetic_codes:\s*list\[int\]\s*=\s*Field\(default_factory=lambda:\s*\[([\d,\s]+)\]\)", schema)
    internal = re.search(r'coordinate_system_internal:\s*str\s*=\s*"([^"]+)"', schema)
    public = re.search(r'coordinate_system_public:\s*str\s*=\s*"([^"]+)"', schema)
    if not k_range or not codes or not internal or not public:
        raise ValueError("python capabilities: a literal field is missing or reshaped")
    return {
        "k_range": (int(k_range.group(1)), int(k_range.group(2))),
        "genetic_codes": [int(part) for part in codes.group(1).split(",") if part.strip()],
        "coordinate_system_internal": internal.group(1),
        "coordinate_system_public": public.group(1),
    }


def check(sources: dict[str, str]) -> list[str]:
    """Return drift descriptions; empty list means parity."""
    errors: list[str] = []
    try:
        rust_num = _rust_numeric_limits(sources)
        py_num = _python_numeric_limits(sources[str(SCHEMA_PY)])
        rust_lit = _rust_literals(sources)
        py_lit = _python_literals(sources[str(SCHEMA_PY)])
    except ValueError as exc:
        return [str(exc)]

    for name in rust_num:
        if rust_num[name] != py_num[name]:
            errors.append(
                f"{name}: Rust enforces {rust_num[name]} but the API advertises {py_num[name]}"
            )
    for name in rust_lit:
        if rust_lit[name] != py_lit[name]:
            errors.append(
                f"{name}: kernel reports {rust_lit[name]!r} but the API advertises {py_lit[name]!r}"
            )
    return errors


def load_sources() -> dict[str, str]:
    return {str(path): path.read_text(encoding="utf-8") for path in (
        SEQUENCE_RS, INTERVALS_RS, TRANSLATION_RS, BINDINGS_RS, SCHEMA_PY
    )}


def self_test() -> int:
    """Every one-sided drift must be caught, and the clean tree must pass."""
    base = load_sources()
    clean = check(base)
    if clean:
        print(f"FAIL self-test: clean tree drifts: {clean}")
        return 1

    cases: list[tuple[str, str, str, str]] = []
    for name, rs_pattern, py_pattern in NUMERIC_LIMITS:
        path = str(SEQUENCE_RS) if name in {"max_inline_sequence", "max_pattern"} else str(INTERVALS_RS)
        cases.append((f"rust {name} drifts", path, rs_pattern, "MUTATE_RUST"))
        cases.append((f"python {name} drifts", str(SCHEMA_PY), py_pattern, "MUTATE_PY"))
    cases += [
        ("rust k_range drifts", str(BINDINGS_RS), r'\("k_range",\s*\(1,\s*32\)\)', "MUTATE_K"),
        ("python k_range drifts", str(SCHEMA_PY), r"k_range:\s*tuple\[int,\s*int\]\s*=\s*\(1,\s*32\)", "MUTATE_K_PY"),
        ("rust genetic code drifts", str(TRANSLATION_RS), r"pub const STANDARD_GENETIC_CODE:\s*u32\s*=\s*1", "MUTATE_CODE"),
        ("python genetic code drifts", str(SCHEMA_PY), r"lambda:\s*\[1\]", "MUTATE_CODE_PY"),
        ("rust internal label drifts", str(BINDINGS_RS), r'"coordinate_system_internal",\s*"0-based-half-open"', "MUTATE_LABEL"),
        ("python internal label drifts", str(SCHEMA_PY), r'coordinate_system_internal:\s*str\s*=\s*"0-based-half-open"', "MUTATE_LABEL_PY"),
    ]

    failures = 0
    for label, path, pattern, mode in cases:
        mutated = dict(base)
        text = mutated[path]
        if mode == "MUTATE_RUST":
            m = re.search(pattern, text)
            assert m, pattern
            value = int(m.group(1).replace("_", "")) + 1
            mutated[path] = text[: m.start(1)] + str(value) + text[m.end(1) :]
        elif mode == "MUTATE_PY":
            m = re.search(pattern, text, re.MULTILINE)
            assert m, pattern
            value = int(m.group(1).replace("_", "")) + 1
            mutated[path] = text[: m.start(1)] + str(value) + text[m.end(1) :]
        elif mode == "MUTATE_K":
            mutated[path] = text.replace('("k_range", (1, 32))', '("k_range", (1, 33))')
        elif mode == "MUTATE_K_PY":
            mutated[path] = text.replace("k_range: tuple[int, int] = (1, 32)", "k_range: tuple[int, int] = (1, 33)")
        elif mode == "MUTATE_CODE":
            mutated[path] = text.replace("STANDARD_GENETIC_CODE: u32 = 1", "STANDARD_GENETIC_CODE: u32 = 2")
        elif mode == "MUTATE_CODE_PY":
            mutated[path] = text.replace("lambda: [1]", "lambda: [2]")
        elif mode == "MUTATE_LABEL":
            mutated[path] = text.replace('"coordinate_system_internal", "0-based-half-open"', '"coordinate_system_internal", "0-based-closed"')
        elif mode == "MUTATE_LABEL_PY":
            mutated[path] = text.replace('coordinate_system_internal: str = "0-based-half-open"', 'coordinate_system_internal: str = "0-based-closed"')
        if mutated[path] == text:
            print(f"FAIL {label}: mutation did not apply")
            failures += 1
            continue
        found = check(mutated)
        if not found:
            print(f"FAIL {label}: drift was not caught")
            failures += 1
        else:
            print(f"PASS {label}: {found[0]}")
    print(f"collected {len(cases)} / {len(cases) - failures} passed")
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
            print(f"CAPABILITY DRIFT: {error}", file=sys.stderr)
        print("sequence capabilities disagree with the Rust kernel", file=sys.stderr)
        return 1
    print("bio-core capability parity: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
