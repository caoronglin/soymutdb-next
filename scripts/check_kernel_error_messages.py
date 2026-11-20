#!/usr/bin/env python3
"""Pin the FFI exception shape to the single canonical error definition.

``BioCoreException`` is the public boundary: ``args[0]`` is a machine code the
frontend keys on (``error.details.code``) and ``args[1]`` is the human sentence.
``packages/bio-core/src/errors.rs`` is the only place that owns that mapping --
``BioCoreError::code()`` and ``#[error(\"...\")]``. ``bindings.rs`` used to
construct one exception by hand with a literal ``\"invalid utf-8\"`` sentence for
the same ``INVALID_CHARACTER`` code, so one code carried two different messages
depending on which path raised it. Neither the exported snapshot nor the
API/bridge guards could see it: they compare API-side tables, not the FFI site.

This guard reads committed Rust bytes only (no wheel, no cargo, no Python 3.15)
and fails when a ``new_err`` call stops going through ``raise(BioCoreError::...)``,
or when ``errors.rs`` stops defining every code it publishes. Run with
``--root`` against a synthetic tree, or ``--self-test`` for the ablations.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS_RS = "packages/bio-core/src/errors.rs"
BINDINGS_RS = "packages/bio-core/src/bindings.rs"

# code() -> "CODE" arm defines the published code set.
CODE_RE = re.compile(r'Self::\w+\s*=>\s*"([A-Z][A-Z0-9_]*)"')
# thiserror #[error("sentence")] owns the human sentence.
SENTENCE_RE = re.compile(r'#\[error\("([^"]+)"\)\]')
# Every FFI exception must be built by raise(BioCoreError::Variant).
RAISE_CALL_RE = re.compile(
    r"BioCoreException::new_err\(\(\s*err\.code\(\)\.to_string\(\)\s*,\s*"
    r"err\.to_string\(\)\s*,?\s*\)\)"
)
NEW_ERR_RE = re.compile(r"BioCoreException::new_err\(")
RAISE_DEF_RE = re.compile(r"fn raise<[^>]*>\(err:\s*BioCoreError\)")
DIRECT_TUPLE_RE = re.compile(
    r'new_err\(\(\s*"([A-Z][A-Z0-9_]*)"\s*,\s*"([^"]*)"\s*\)\)'
)


def check(root: Path) -> list[str]:
    failures: list[str] = []
    paths = [root / ERRORS_RS, root / BINDINGS_RS]
    for path in paths:
        if not path.is_file():
            failures.append(f"missing contract file: {path.relative_to(root)}")
    if failures:
        return failures

    errors = paths[0].read_text(encoding="utf-8")
    bindings = paths[1].read_text(encoding="utf-8")

    codes = CODE_RE.findall(errors)
    sentences = SENTENCE_RE.findall(errors)
    if not codes:
        failures.append("errors.rs publishes no machine codes")
    if not sentences:
        failures.append("errors.rs declares no #[error] sentences")
    if len(codes) != len(sentences):
        failures.append(
            f"errors.rs has {len(codes)} codes but {len(sentences)} sentences; "
            "one code = one sentence is the contract"
        )
    if len(set(codes)) != len(codes):
        failures.append("errors.rs publishes a duplicate machine code")
    if "pub const fn code(&self)" not in errors:
        failures.append("errors.rs no longer centralises code()")

    if not RAISE_DEF_RE.search(bindings):
        failures.append("bindings.rs has no raise(BioCoreError) helper")
    if not RAISE_CALL_RE.search(bindings):
        failures.append(
            "raise() no longer builds the exception from err.code()/err.to_string()"
        )

    new_err_sites = NEW_ERR_RE.findall(bindings)
    if len(new_err_sites) != 1:
        failures.append(
            f"expected exactly one new_err site (inside raise()), found {len(new_err_sites)}"
        )
    for code, sentence in DIRECT_TUPLE_RE.findall(bindings):
        failures.append(
            f"bindings.rs hardcodes ({code}, {sentence!r}) outside errors.rs; "
            "route it through raise(BioCoreError::...)"
        )

    return failures


# --------------------------------------------------------------------------
# Self-test: synthetic trees only, never this repository.

_GOOD_ERRORS = """\
use thiserror::Error;
#[derive(Debug, Error)]
pub enum BioCoreError {
    #[error("empty sequence")]
    EmptySequence,
    #[error("invalid character for the selected alphabet")]
    InvalidCharacter,
}
impl BioCoreError {
    pub const fn code(&self) -> &'static str {
        match self {
            Self::EmptySequence => "EMPTY_SEQUENCE",
            Self::InvalidCharacter => "INVALID_CHARACTER",
        }
    }
}
"""

_GOOD_BINDINGS = """\
fn raise<T>(err: BioCoreError) -> PyResult<T> {
    Err(BioCoreException::new_err((
        err.code().to_string(),
        err.to_string(),
    )))
}
fn reverse_complement() -> PyResult<String> {
    let bytes = out.or_else(raise)?;
    String::from_utf8(bytes).or_else(|_| raise(BioCoreError::InvalidCharacter))
}
"""


def self_test() -> int:
    import tempfile

    cases: list[tuple[str, str, str, bool]] = [
        ("clean tree passes", _GOOD_ERRORS, _GOOD_BINDINGS, False),
        (
            "literal tuple returns to the FFI",
            _GOOD_ERRORS,
            _GOOD_BINDINGS.replace(
                "String::from_utf8(bytes).or_else(|_| raise(BioCoreError::InvalidCharacter))",
                'String::from_utf8(bytes).map_err(|_| BioCoreException::new_err(("INVALID_CHARACTER", "invalid utf-8")))',
            ),
            True,
        ),
        (
            "raise() stops using code()",
            _GOOD_ERRORS,
            _GOOD_BINDINGS.replace(
                "err.code().to_string(),", '"validation_error".to_string(),'
            ),
            True,
        ),
        (
            "raise() stops using to_string()",
            _GOOD_ERRORS,
            _GOOD_BINDINGS.replace("err.to_string(),", '"oops".to_string(),'),
            True,
        ),
        (
            "a code loses its sentence",
            _GOOD_ERRORS.replace(
                '    #[error("empty sequence")]\n    EmptySequence,\n',
                "    EmptySequence,\n",
            ),
            _GOOD_BINDINGS,
            True,
        ),
        (
            "code() disappears",
            _GOOD_ERRORS.replace(
                "pub const fn code(&self) -> &'static str",
                "fn code(&self) -> &'static str",
            ),
            _GOOD_BINDINGS,
            True,
        ),
        (
            "a duplicate code is published",
            _GOOD_ERRORS.replace(
                'Self::InvalidCharacter => "INVALID_CHARACTER",',
                'Self::InvalidCharacter => "INVALID_CHARACTER",\n'
                '            Self::EmptySequence => "EMPTY_SEQUENCE",',
            ),
            _GOOD_BINDINGS,
            True,
        ),
        (
            "errors.rs is missing",
            None,  # type: ignore[arg-type]
            _GOOD_BINDINGS,
            True,
        ),
    ]
    failures = 0
    for name, errors, bindings, expect_fail in cases:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "packages/bio-core/src").mkdir(parents=True)
            if errors is not None:
                (root / ERRORS_RS).write_text(errors, encoding="utf-8")
            (root / BINDINGS_RS).write_text(bindings, encoding="utf-8")
            problems = check(root)
            caught = bool(problems)
            ok = caught == expect_fail
            print(f"  [{'OK' if ok else 'FAIL'}] {name}: {problems}")
            if not ok:
                failures += 1
    print(
        f"kernel error-message contract self-test: {len(cases) - failures}/{len(cases)} passed"
    )
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=ROOT, help="tree to check (default: repository)"
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    failures = check(args.root)
    if failures:
        print("kernel error-message contract failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("kernel error-message contract passed (FFI errors derive from errors.rs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
