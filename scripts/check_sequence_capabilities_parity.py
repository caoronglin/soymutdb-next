#!/usr/bin/env python3
"""Pin the sequence capabilities surface that the merged parity guard omits.

``check_bio_core_capability_parity.py`` (PR #135) binds the four numeric
limits, k_range, genetic_codes and the two coordinate labels to the *module
constants* in ``apps/api/app/schemas/sequence_tools.py``. It never reads the
``SequenceCapabilitiesResponse`` field defaults. So a response field that
drifts away from its own module constant -- or a program/format/endpoint that
is added, dropped or renamed -- stays invisible to it. Reproduced by mutation
on the merged tree: renaming a field default to a fresh literal leaves #135
PASS while the published OpenAPI contract is already wrong.

This guard is the complement, not a second parity checker. It reads committed
bytes from both languages and pins:

* each numeric field default equals the module constant AND the Rust const;
* the kernel's capabilities() dict derives from those same constants;
* formats == the fmt Literal == the registered Rust validators;
* programs == every POST operation except /inspect, and GET /capabilities
  stays registered;
* the CI hook and its backend collection point remain in place.

It needs no CPython 3.15, no pydantic, no wheel, no PostgreSQL and no OpenAPI
export, so a one-sided edit cannot hide behind a skipped lane. Both guards run
in the same tree without a shared-file conflict.

Usage:
    python3 scripts/check_sequence_capabilities_parity.py
    python3 scripts/check_sequence_capabilities_parity.py --self-test
    python3 scripts/check_sequence_capabilities_parity.py --root <tree>
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RUST_SEQUENCE = "packages/bio-core/src/sequence.rs"
RUST_INTERVALS = "packages/bio-core/src/intervals.rs"
RUST_TRANSLATION = "packages/bio-core/src/translation.rs"
RUST_BINDINGS = "packages/bio-core/src/bindings.rs"
PY_SCHEMA = "apps/api/app/schemas/sequence_tools.py"
PY_ROUTER = "apps/api/app/api/v1/tools_sequence.py"
BACKEND_GATE = "scripts/verify-backend-tests.sh"
HOOK_TEST = "apps/api/tests/test_sequence_capabilities_parity.py"

FILES = (
    RUST_SEQUENCE,
    RUST_INTERVALS,
    RUST_TRANSLATION,
    RUST_BINDINGS,
    PY_SCHEMA,
    PY_ROUTER,
)

#: Python module constant -> (Rust constant, capabilities field or None).
PY_TO_RUST = (
    ("MAX_INLINE_SEQUENCE", "MAX_INLINE_SEQUENCE", "max_inline_sequence"),
    ("MAX_PATTERN", "MAX_PATTERN", "max_pattern"),
    ("MAX_HITS", "MAX_HITS", "max_hits"),
    ("MAX_REGIONS", "MAX_REGIONS", None),
)

#: The kernel's capabilities() dict must derive these keys from the pinned
#: constants/functions, never from freshly written literals or a second table.
BINDING_EXPRS = {
    "max_inline_sequence": "crate::sequence::MAX_INLINE_SEQUENCE",
    "max_pattern": "crate::sequence::MAX_PATTERN",
    "max_hits": "crate::intervals::MAX_HITS",
    "max_regions": "crate::intervals::MAX_REGIONS",
    "genetic_codes": "crate::translation::implemented_genetic_codes()",
}

#: These two strings are a published contract, pinned here by identity.
COORD = {
    "coordinate_system_internal": "0-based-half-open",
    "coordinate_system_public": "1-based-inclusive",
}

RUST_CONST = re.compile(r"pub\s+const\s+(\w+)\s*:\s*[\w]+\s*=\s*([\d_]+)\s*;")
K_BOUND = re.compile(r"\((\d+)\.\.=(\d+)\)\.contains")
SET_ITEM = re.compile(r'd\.set_item\(\s*"([^"]+)"\s*,\s*(.*?)\s*,?\s*\)\?;', re.S)
CAPS_FN = re.compile(r"\nfn capabilities\(.*?\n\}", re.S)
ROUTER_OP = re.compile(r'@router\.(get|post)\(\s*["\']([^"\']+)["\']')
VALIDATOR = re.compile(r"wrap_pyfunction!\((validate_\w+),")


def _read(root: Path, rel: str, texts: dict[str, str] | None) -> str:
    if texts is not None and rel in texts:
        return texts[rel]
    return (root / rel).read_text(encoding="utf-8")


def _literal(node: ast.AST, consts: dict[str, int]):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, (ast.Tuple, ast.List)):
        vals = [_literal(e, consts) for e in node.elts]
        return tuple(vals) if isinstance(node, ast.Tuple) else vals
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Field":
        for kw in node.keywords:
            if kw.arg in {"default_factory", "default"}:
                value = kw.value.body if isinstance(kw.value, ast.Lambda) else kw.value
                return _literal(value, consts)
    return None


def _py_schema(text: str) -> tuple[dict[str, int], dict, set[str]]:
    tree = ast.parse(text)
    consts: dict[str, int] = {}
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
        for target in targets:
            value = _literal(node.value, {}) if node.value else None
            if isinstance(value, int):
                consts[target.id] = value

    caps_cls = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "SequenceCapabilitiesResponse"
    )
    caps: dict = {}
    for node in caps_cls.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            value = _literal(node.value, consts)
            if value is not None:
                caps[node.target.id] = value

    fmts: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.target.id == "fmt"):
            continue
        ann = node.annotation
        if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name) \
                and ann.value.id == "Literal" and isinstance(ann.slice, ast.Tuple):
            fmts.update(e.value for e in ann.slice.elts if isinstance(e, ast.Constant))
    return consts, caps, fmts


def _rust_consts(texts: dict[str, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for rel in (RUST_SEQUENCE, RUST_INTERVALS, RUST_TRANSLATION):
        for name, value in RUST_CONST.findall(texts[rel]):
            out[name] = int(value.replace("_", ""))
    return out


def _binding_caps(text: str) -> dict[str, str]:
    match = CAPS_FN.search(text)
    if match is None:
        return {}
    out: dict[str, str] = {}
    for key, expr in SET_ITEM.findall(match.group(0)):
        out[key] = expr.strip().rstrip(",").strip()
    return out


def _ops(text: str) -> tuple[set[str], set[str]]:
    stripped = re.sub(r'"""[\s\S]*?"""', "", text)
    stripped = re.sub(r"#[^\n]*", "", stripped)
    gets: set[str] = set()
    posts: set[str] = set()
    for method, path in ROUTER_OP.findall(stripped):
        (gets if method == "get" else posts).add(path.lstrip("/"))
    return gets, posts


def check(root: Path = ROOT, texts: dict[str, str] | None = None) -> list[str]:
    """Return a list of divergences; empty means the two declarations agree."""
    errors: list[str] = []

    def eq(label: str, got, want) -> None:
        if got != want:
            errors.append(f"{label}: got {got!r}, expected {want!r}")

    try:
        data = {rel: _read(root, rel, texts) for rel in FILES}
    except (OSError, UnicodeError) as exc:
        return [f"cannot read committed sources: {exc}"]

    rust = _rust_consts(data)
    py_consts, caps, fmts = _py_schema(data[PY_SCHEMA])
    bindings = _binding_caps(data[RUST_BINDINGS])
    gets, posts = _ops(data[PY_ROUTER])

    # 1. One numeric limit, one value, in both languages.
    for py_name, rust_name, field in PY_TO_RUST:
        if rust_name not in rust:
            errors.append(f"Rust constant {rust_name} is missing")
            continue
        if py_name not in py_consts:
            errors.append(f"Python constant {py_name} is missing")
            continue
        eq(f"{py_name} (Python)", py_consts[py_name], rust[rust_name])
        if field:
            if field not in caps:
                errors.append(f"capabilities field {field} is missing")
            else:
                eq(f"capabilities.{field}", caps[field], rust[rust_name])

    # 2. The kernel's own capabilities() dict derives from those constants.
    for key, expr in BINDING_EXPRS.items():
        if key not in bindings:
            errors.append(f"kernel capabilities() no longer publishes {key}")
        else:
            eq(f"kernel capabilities()[{key}]", bindings[key], expr)
    if "vec![STANDARD_GENETIC_CODE]" not in data[RUST_TRANSLATION]:
        errors.append("implemented_genetic_codes() no longer returns the pinned table")

    # 3. k_range: Python default == kernel tuple == the Rust k guard.
    k = K_BOUND.search(data[RUST_SEQUENCE])
    if k is None:
        errors.append("Rust k bound (1..=32) is missing")
        rust_k = None
    else:
        rust_k = (int(k.group(1)), int(k.group(2)))
    eq("k_range (Rust bound)", rust_k, (1, 32))
    if "k_range" in caps:
        eq("capabilities.k_range", caps["k_range"], rust_k)
    if "k_range" in bindings:
        m = re.match(r"\((\d+),\s*(\d+)\)", bindings["k_range"])
        eq("kernel capabilities()[k_range]",
           (int(m.group(1)), int(m.group(2))) if m else bindings["k_range"], rust_k)

    # 4. Only implemented genetic codes may be advertised.
    if "STANDARD_GENETIC_CODE" in rust:
        eq("capabilities.genetic_codes", caps.get("genetic_codes"),
           [rust["STANDARD_GENETIC_CODE"]])

    # 5. Coordinate-system strings are a published contract.
    for key, want in COORD.items():
        eq(f"capabilities.{key}", caps.get(key), want)
        eq(f"kernel capabilities()[{key}]", bindings.get(key), f'"{want}"')

    # 6. formats == the fmt Literal == the kernel's actual validators.
    validators = {m[len("validate_"):] for m in VALIDATOR.findall(data[RUST_BINDINGS])}
    eq("kernel format validators", sorted(validators), ["bed", "fasta", "fastq"])
    eq("capabilities.formats", sorted(caps.get("formats") or []), sorted(fmts))
    eq("capabilities.formats vs kernel validators",
       sorted(caps.get("formats") or []), sorted(validators))

    # 7. Every POST operation is either an advertised program or /inspect
    # (format inspection, covered by formats above).
    eq("capabilities.programs", sorted(caps.get("programs") or []),
       sorted(posts - {"inspect"}))
    if "inspect" not in posts:
        errors.append("router /inspect is missing; formats have no live validator")
    if "capabilities" not in gets:
        errors.append("router GET /capabilities is missing")

    # 8. The CI hook and its collection point must stay in place.
    if texts is None:
        if not (root / HOOK_TEST).is_file():
            errors.append(f"CI hook {HOOK_TEST} is missing")
        gate = _read(root, BACKEND_GATE, None)
        if "-m pytest tests -q" not in gate:
            errors.append("backend gate no longer collects the full tests tree")

    return errors


@dataclass(frozen=True)
class Case:
    name: str
    rel: str
    old: str
    new: str
    expect_error: bool


def synthetic_cases() -> list[Case]:
    return [
        Case("faithful copy", PY_SCHEMA, "", "", False),
        Case("field default drifts from its module constant", PY_SCHEMA,
             "max_inline_sequence: int = MAX_INLINE_SEQUENCE",
             "max_inline_sequence: int = 2_097_152", True),
        Case("response field dropped, module constant intact", PY_SCHEMA,
             "    max_hits: int = MAX_HITS\n", "", True),
        Case("python max_inline drifts", PY_SCHEMA,
             "MAX_INLINE_SEQUENCE = 1_048_576", "MAX_INLINE_SEQUENCE = 2_097_152", True),
        Case("rust max_pattern drifts", RUST_SEQUENCE,
             "MAX_PATTERN: usize = 256", "MAX_PATTERN: usize = 512", True),
        Case("rust max_hits drifts", RUST_INTERVALS,
             "MAX_HITS: usize = 1000", "MAX_HITS: usize = 2000", True),
        Case("k_range drifts", PY_SCHEMA,
             "k_range: tuple[int, int] = (1, 32)", "k_range: tuple[int, int] = (1, 64)", True),
        Case("unimplemented genetic code invented", PY_SCHEMA,
             "default_factory=lambda: [1]", "default_factory=lambda: [1, 2]", True),
        Case("coordinate string drifts", RUST_BINDINGS,
             '"0-based-half-open"', '"1-based-half-open"', True),
        Case("formats drop bed", PY_SCHEMA,
             '["fasta", "fastq", "bed"]', '["fasta", "fastq"]', True),
        Case("programs drop kmers", PY_SCHEMA, '"kmers",', "", True),
        Case("new router op not advertised", PY_ROUTER,
             '@router.get("/capabilities"',
             '@router.post("/gc-content", response_model=s.SequenceStatsResponse)\n'
             '@router.get("/capabilities"', True),
        Case("kernel binding stops deriving from const", RUST_BINDINGS,
             "crate::sequence::MAX_INLINE_SEQUENCE", "1048576", True),
    ]


def run_case(case: Case, root: Path = ROOT) -> list[str]:
    texts = {rel: (root / rel).read_text(encoding="utf-8") for rel in FILES}
    if case.old:
        if case.old not in texts[case.rel]:
            return [f"self-test anchor missing for {case.name}: {case.old!r}"]
        texts[case.rel] = texts[case.rel].replace(case.old, case.new, 1)
    return check(root, texts=texts)


def self_test() -> int:
    ok = True
    for case in synthetic_cases():
        errors = run_case(case)
        caught = bool(errors)
        status = "OK" if caught == case.expect_error else "FAIL"
        if status == "FAIL":
            ok = False
        print(f"  [{status}] {case.name}: "
              f"{'caught' if caught else 'no divergence'}")
        if status == "FAIL":
            print(f"         expected_error={case.expect_error}, errors={errors[:2]}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print("sequence capabilities parity: self-test")
        return self_test()
    errors = check(args.root)
    if errors:
        print("sequence capabilities parity: FAIL", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("sequence capabilities parity: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
