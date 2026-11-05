#!/usr/bin/env python3
"""Freeze the kernel's public error-code vocabulary against a hand-written lock.

``packages/bio-core/src/errors.rs`` owns the code set AND the sentence for each
code. Every other consumer -- the bridge's message table, the API regression
expectations, the wheel contract assertions -- derives its expectations from
that file. A coordinated rename can therefore move the whole chain together
and stay green: ``errors.rs`` is compared only with things that were generated
from ``errors.rs``.

``packages/bio-core/errors.golden.json`` is the one anchor that is NOT derived.
It is hand-maintained, sits downstream of the Rust source, and records the
public contract: which ``error.details.code`` values a client may receive and
what each one means. This guard reads both files as committed bytes and fails
when they disagree. Renaming any code in ``errors.rs`` alone now turns a gate
red -- the rename has to be an explicit, reviewed edit to the lock file too.

Deliberately narrow: this binds *values*, not the bridge mapping. #134 owns
code-set-to-bridge consistency; #148 owns the FFI raise site. Neither can
replace a value-level anchor, and this guard does not try to duplicate either.

Runs on a bare CPython with stdlib only: no wheel, no Rust toolchain, no
FastAPI, no database, no pytest. Suitable before the expensive build.

Usage:
    python3 scripts/check_kernel_error_golden.py [--root <tree>] [--self-test]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS_RS = Path("packages/bio-core/src/errors.rs")
GOLDEN = Path("packages/bio-core/errors.golden.json")

#: The single canonical shape of a public kernel code.
CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _strip_rust_comments(text: str) -> str:
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return re.sub(r"//[^\n]*", "", text)


def _rust_string(literal: str) -> str:
    inner = literal[1:-1]
    return (
        inner.replace('\\"', '"')
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\\\", "\\")
    )


def parse_errors_rs(text: str) -> tuple[dict[str, str], list[str]]:
    """Return {code: sentence} plus parse failures for the thiserror enum."""
    failures: list[str] = []
    body = _strip_rust_comments(text)
    enum = re.search(r"pub enum BioCoreError\s*\{(?P<arms>[\s\S]*?)\n\}", body)
    if not enum:
        return {}, ["errors.rs declares no `pub enum BioCoreError` block"]
    arms = enum.group("arms")

    sentences: dict[str, str] = {}
    variant_order: list[str] = []
    for match in re.finditer(
        r'#\[error\((?P<msg>"(?:[^"\\]|\\.)*")\)\]\s*(?P<variant>[A-Za-z_]\w*)',
        arms,
    ):
        variant = match.group("variant")
        if variant in sentences:
            failures.append(f"variant {variant} is declared twice")
        variant_order.append(variant)
        sentences[variant] = _rust_string(match.group("msg"))

    code_block = re.search(
        r"pub const fn code\(&self\) -> &'static str \{\s*"
        r"match self \{(?P<body>[\s\S]*?)\n\s*\}\s*\n\s*\}",
        body,
    )
    if not code_block:
        return {}, [*failures, "errors.rs declares no `code()` match block"]

    codes: dict[str, str] = {}
    for match in re.finditer(
        r'Self::(?P<variant>[A-Za-z_]\w*)\s*=>\s*"(?P<code>[^"]+)"',
        code_block.group("body"),
    ):
        variant, code = match.group("variant"), match.group("code")
        if variant in codes:
            failures.append(f"code() maps {variant} more than once")
        codes[variant] = code

    if len(codes) != len(variant_order):
        missing = sorted(set(variant_order) - set(codes))
        extra = sorted(set(codes) - set(variant_order))
        if missing:
            failures.append(f"code() is missing a mapping for: {', '.join(missing)}")
        if extra:
            failures.append(f"code() maps variants that do not exist: {', '.join(extra)}")

    result: dict[str, str] = {}
    seen: dict[str, str] = {}
    for variant in variant_order:
        if variant not in sentences:
            failures.append(f"variant {variant} has no #[error(...)] sentence")
            continue
        code = codes.get(variant)
        if code is None:
            continue
        if not CODE_RE.fullmatch(code):
            failures.append(f"code {code!r} is not an UPPER_SNAKE machine code")
        if code in seen:
            failures.append(f"code {code} is shared by {seen[code]} and {variant}")
        seen[code] = variant
        result[code] = sentences[variant]

    return result, failures


def _load_golden(path: Path) -> tuple[dict[str, str] | None, list[str]]:
    """Read the lock file as opaque data; reject anything but a flat str map."""
    failures: list[str] = []
    if not path.is_file():
        return None, [f"missing hand-written lock file: {path}"]
    raw = path.read_text(encoding="utf-8")
    duplicates: list[str] = []

    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        seen: set[str] = set()
        for key, _ in pairs:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        return dict(pairs)

    try:
        data = json.loads(raw, object_pairs_hook=hook)
    except json.JSONDecodeError as exc:
        return None, [f"errors.golden.json is not valid JSON: {exc}"]
    if duplicates:
        failures.append(
            f"errors.golden.json repeats keys: {', '.join(sorted(set(duplicates)))}"
        )
    if not isinstance(data, dict) or not data:
        return None, [*failures, "errors.golden.json must be a non-empty JSON object"]
    for key, value in data.items():
        if not isinstance(key, str) or not CODE_RE.fullmatch(key):
            failures.append(f"errors.golden.json key {key!r} is not an UPPER_SNAKE code")
        if not isinstance(value, str) or not value:
            failures.append(f"errors.golden.json[{key!r}] must be a non-empty string")
    return data, failures


def _compare(codes: dict[str, str], golden: dict[str, str]) -> list[str]:
    """Name every disagreement; never silently treat a missing side as equality."""
    failures: list[str] = []
    for code in sorted(set(codes) - set(golden)):
        failures.append(
            f"errors.rs publishes {code!r} but the lock file does not: a new public "
            "code needs a reviewed entry in errors.golden.json"
        )
    for code in sorted(set(golden) - set(codes)):
        failures.append(
            f"errors.golden.json freezes {code!r}, which errors.rs no longer "
            "raises: a renamed or removed code is a breaking contract change"
        )
    for code in sorted(set(codes) & set(golden)):
        if codes[code] != golden[code]:
            failures.append(
                f"errors.golden.json[{code!r}] is {golden[code]!r} but errors.rs "
                f"says {codes[code]!r}: one code must carry one sentence"
            )
    return failures


def check(root: Path = ROOT) -> list[str]:
    errors_path, golden_path = root / ERRORS_RS, root / GOLDEN
    failures: list[str] = []
    if not errors_path.is_file():
        failures.append(f"missing kernel source: {errors_path}")
    golden, golden_failures = _load_golden(golden_path)
    failures.extend(golden_failures)
    if failures or not errors_path.is_file() or golden is None:
        return failures

    codes, rust_failures = parse_errors_rs(errors_path.read_text(encoding="utf-8"))
    failures.extend(rust_failures)
    if rust_failures or not codes:
        return failures
    failures.extend(_compare(codes, golden))
    return failures


def _write_tree(root: Path, errors_rs: str, golden: str | None) -> None:
    (root / ERRORS_RS).parent.mkdir(parents=True, exist_ok=True)
    (root / ERRORS_RS).write_text(errors_rs, encoding="utf-8")
    if golden is None:
        (root / GOLDEN).unlink(missing_ok=True)
    else:
        (root / GOLDEN).write_text(golden, encoding="utf-8")


def self_test() -> int:
    """Mutation-prove the guard; synthetic trees only, never the real repo."""
    source_errors = (ROOT / ERRORS_RS).read_text(encoding="utf-8")
    source_golden = (ROOT / GOLDEN).read_text(encoding="utf-8")

    cases: list[tuple[str, str, str | None, str | None]] = [
        ("clean tree passes", source_errors, source_golden, None),
        (
            "rename one code in errors.rs only",
            source_errors.replace('"EMPTY_SEQUENCE"', '"EMPTY_SEQUENCX"'),
            source_golden,
            "no longer raises",
        ),
        (
            "rename one code in the lock file only",
            source_errors,
            source_golden.replace('"EMPTY_SEQUENCE"', '"EMPTY_SEQUENCX"'),
            "needs a reviewed entry",
        ),
        (
            "rename errors.rs AND a co-derived bridge table together",
            source_errors.replace('"EMPTY_SEQUENCE"', '"EMPTY_SEQUENCX"'),
            source_golden,
            "no longer raises",
        ),
        (
            "change a sentence in errors.rs",
            source_errors.replace('"empty sequence"', '"blank input"'),
            source_golden,
            "must carry one sentence",
        ),
        (
            "change a sentence in the lock file",
            source_errors,
            source_golden.replace('"empty sequence"', '"blank input"'),
            "must carry one sentence",
        ),
        (
            "add a code to errors.rs without a lock entry",
            source_errors.replace(
                '    #[error("invalid FASTA/FASTQ record")]',
                '    #[error("brand new failure")]\n    BrandNew,\n'
                '    #[error("invalid FASTA/FASTQ record")]',
            ).replace(
                "            Self::InvalidRecord => \"INVALID_RECORD\",",
                '            Self::BrandNew => "BRAND_NEW",\n'
                "            Self::InvalidRecord => \"INVALID_RECORD\",",
            ),
            source_golden,
            "needs a reviewed entry",
        ),
        (
            "drop a code from errors.rs",
            source_errors.replace(
                '            Self::EmptySequence => "EMPTY_SEQUENCE",\n', ""
            ).replace('    #[error("empty sequence")]\n    EmptySequence,\n', ""),
            source_golden,
            "no longer raises",
        ),
        (
            "duplicate a machine code in errors.rs",
            source_errors.replace(
                '"INVALID_CHARACTER"', '"EMPTY_SEQUENCE"'
            ),
            source_golden,
            "is shared by",
        ),
        (
            "lowercase a code in errors.rs",
            source_errors.replace('"EMPTY_SEQUENCE"', '"empty_sequence"'),
            source_golden,
            "UPPER_SNAKE",
        ),
        (
            "duplicate keys in the lock file",
            source_errors,
            source_golden.replace(
                '"EMPTY_SEQUENCE": "empty sequence",',
                '"EMPTY_SEQUENCE": "empty sequence",\n  "EMPTY_SEQUENCE": "empty sequence",',
            ),
            "repeats keys",
        ),
        ("empty lock file", source_errors, "{}", "non-empty JSON object"),
        ("lock file is not an object", source_errors, "[]", "non-empty JSON object"),
        ("lock file is invalid JSON", source_errors, "{oops", "not valid JSON"),
        ("lock file removed", source_errors, None, "missing hand-written lock file"),
        (
            "positive control: a legitimate new code added to BOTH sides",
            source_errors.replace(
                '    #[error("invalid FASTA/FASTQ record")]',
                '    #[error("brand new failure")]\n    BrandNew,\n'
                '    #[error("invalid FASTA/FASTQ record")]',
            ).replace(
                "            Self::InvalidRecord => \"INVALID_RECORD\",",
                '            Self::BrandNew => "BRAND_NEW",\n'
                "            Self::InvalidRecord => \"INVALID_RECORD\",",
            ),
            source_golden.replace(
                '  "INVALID_RECORD": "invalid FASTA/FASTQ record"',
                '  "BRAND_NEW": "brand new failure",\n'
                '  "INVALID_RECORD": "invalid FASTA/FASTQ record"',
            ),
            None,
        ),
    ]

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, errors_rs, golden, expected in cases:
            _write_tree(root, errors_rs, golden)
            found = check(root)
            if expected is None:
                if found:
                    failures.append(f"{name}: expected a pass, got {found}")
            elif not any(expected in item for item in found):
                failures.append(
                    f"{name}: expected a failure containing {expected!r}, got {found}"
                )
    if failures:
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"kernel error-code golden guard self-test passed ({len(cases)} cases)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    failures = check(args.root)
    if failures:
        print("kernel error-code golden contract failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    codes, _ = parse_errors_rs(
        (args.root / ERRORS_RS).read_text(encoding="utf-8")
    )
    print(f"kernel error-code golden contract passed ({len(codes)} codes frozen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
