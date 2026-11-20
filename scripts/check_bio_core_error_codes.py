#!/usr/bin/env python3
"""Bind the Rust bio-core error codes to the message the API actually returns.

``packages/bio-core/src/errors.rs`` owns the machine-readable code set and the
one human sentence that explains each code. ``bio_core_bridge.translate_error``
turns a ``BioCoreException`` into the HTTP envelope. Nothing in between proved
the two agree, and two things had gone wrong:

* the bridge replaced the kernel's sentence with a single neutral fallback for
  every code except two, so ``EMPTY_SEQUENCE`` and ``INVALID_CHARACTER`` reached
  the client with the same text;
* unknown / non-kernel exceptions were trusted verbatim -- ``Exception("timeout")``
  published ``details.code == "timeout"``, a machine code the client enum has
  never heard of.

This guard reads the committed bytes (no wheel, no CPython 3.15, no database):

1. every ``BioCoreError`` variant has exactly one code and one sentence, and the
   Python message table covers that code with *that* sentence;
2. every code travels through the mapping -- no code silently falls back;
3. a non-kernel exception can never contribute its own code or text;
4. the API regression file still pins the same code set, so deleting the tests
   cannot make the gate greener.

Run ``--self-test`` for the guard's own cases; the default run inspects this
repository's tree.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS_RS = ROOT / "packages/bio-core/src/errors.rs"
BRIDGE_PY = ROOT / "apps/api/app/services/bio_core_bridge.py"
API_TESTS = ROOT / "apps/api/tests/test_sequence_tools_error_codes.py"

#: The table name the bridge must expose and every consumer must be able to read.
TABLE_NAME = "KERNEL_ERROR_MESSAGES"
MAP_NAME = "translate_error"


# --------------------------------------------------------------------------
# Rust side: the code set AND its sentence.
# --------------------------------------------------------------------------


def parse_errors_rs(text: str) -> tuple[dict[str, str], list[str]]:
    """Return {code: sentence} plus parse failures for a ``thiserror`` enum."""
    failures: list[str] = []
    body = _strip_rust_comments(text)
    enum = re.search(r"pub enum BioCoreError\s*\{(?P<arms>[\s\S]*?)\n\}\s*\n", body)
    if not enum:
        return {}, ["errors.rs declares no `pub enum BioCoreError` block"]
    arms = enum.group("arms")

    sentences: dict[str, str] = {}
    variant_order: list[str] = []
    for match in re.finditer(
        r"#\[error\((?P<msg>\"(?:[^\"\\]|\\.)*\")\)\]\s*(?P<variant>[A-Za-z_]\w*)",
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
        r"Self::(?P<variant>[A-Za-z_]\w*)\s*=>\s*\"(?P<code>[^\"]+)\"",
        code_block.group("body"),
    ):
        variant = match.group("variant")
        code = match.group("code")
        if variant in codes:
            failures.append(f"code() maps {variant} more than once")
        codes[variant] = code

    declared = re.findall(
        r"^\s*(?P<variant>[A-Za-z_]\w*)\s*,\s*$",
        arms,
        re.MULTILINE,
    )
    for variant in declared:
        if variant not in sentences and variant not in {
            "pub", "enum", "impl", "fn", "if", "match", "self", "use",
        }:
            failures.append(f"variant {variant} has no #[error(...)] sentence")

    if len(codes) != len(variant_order):
        missing = sorted(set(variant_order) - set(codes))
        extra = sorted(set(codes) - set(variant_order))
        if missing:
            failures.append(f"code() is missing a mapping for: {', '.join(missing)}")
        if extra:
            failures.append(f"code() maps variants that do not exist: {', '.join(extra)}")

    codes_seen: dict[str, str] = {}
    for variant in variant_order:
        code = codes.get(variant)
        if code is None:
            continue
        if code in codes_seen:
            failures.append(
                f"code {code} is shared by {codes_seen[code]} and {variant}"
            )
        codes_seen[code] = variant
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", code):
            failures.append(f"code {code!r} is not an UPPER_SNAKE machine code")

    sentences_by_code = {
        codes[variant]: sentences[variant]
        for variant in variant_order
        if variant in codes and variant in sentences
    }
    for variant in variant_order:
        if variant not in sentences:
            failures.append(f"variant {variant} has no #[error(...)] sentence")
    return sentences_by_code, failures


def _strip_rust_comments(text: str) -> str:
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return re.sub(r"//[^\n]*", "", text)


def _rust_string(literal: str) -> str:
    """Decode the few escapes a thiserror message realistically uses."""
    inner = literal[1:-1]
    return (
        inner.replace('\\"', '"')
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\\\", "\\")
    )


# --------------------------------------------------------------------------
# Python side: the bridge's mapping.
# --------------------------------------------------------------------------


def parse_bridge(text: str) -> tuple[dict[str, str], str, list[str]]:
    """Return ({code: message}, translate_error source, failures)."""
    failures: list[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:  # pragma: no cover - a syntax error fails the run
        return {}, "", [f"bio_core_bridge.py does not parse: {exc}"]

    table: dict[str, str] | None = None
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
        if not isinstance(target, ast.Name) or target.id != TABLE_NAME:
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            failures.append(f"{TABLE_NAME} must be a dict literal")
            continue
        table = {}
        for key, item in zip(value.keys, value.values, strict=True):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                failures.append(f"{TABLE_NAME} has a non-literal key")
                continue
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                failures.append(f"{TABLE_NAME}[{key.value!r}] must be a string literal")
                continue
            table[key.value] = item.value
    if table is None:
        failures.append(f"bio_core_bridge.py declares no {TABLE_NAME} dict")

    source = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == MAP_NAME:
            source = ast.get_source_segment(text, node) or ""
            break
    if not source:
        failures.append(f"bio_core_bridge.py declares no {MAP_NAME}()")
    return table or {}, source, failures


def inspect_bridge_mapping(
    codes: dict[str, str], table: dict[str, str], source: str, module_text: str = ""
) -> list[str]:
    """Codes, sentences and fallback behaviour must stay bound."""
    failures: list[str] = []
    if not source:
        return ["translate_error() body is missing"]

    for code, sentence in codes.items():
        if code not in table:
            failures.append(
                f"{code} has no entry in {TABLE_NAME}: its kernel sentence "
                f"({sentence!r}) can never reach the client"
            )
        elif table[code] != sentence:
            failures.append(
                f"{TABLE_NAME}[{code!r}] is {table[code]!r} but errors.rs says "
                f"{sentence!r}; the mapping is a second, disagreeing truth"
            )
    for code in table:
        if code not in codes:
            failures.append(f"{TABLE_NAME} carries {code!r}, which the kernel never raises")

    # Publishing a code is: the exception's arg acts as a KEY into the table.
    # Anything looser -- the arg itself, or the arg assumed to already be a code
    # -- forges one, which is how ``Exception("timeout")`` once reached
    # ``details.code``. The arg appears legitimately in two shapes only:
    # ``args[0] in TABLE`` (membership guard) and ``TABLE[args[0]]`` (lookup).
    arg_keyed = re.search(
        rf"\bargs\[0\]\s+(?:not\s+)?in\s+{TABLE_NAME}\b"
        rf"|{TABLE_NAME}\[\s*args\[0\]\s*\]",
        source,
    )
    if re.search(r"\bargs\[0\]", source) and arg_keyed is None:
        failures.append(
            "an exception's first arg is published as details.code; a plain "
            "Exception('timeout') would forge a machine code"
        )

    # The membership test is load-bearing wherever the table is read.  It may
    # sit in a multi-condition `if (...)` or a nested branch, so the shape is
    # "arg is proven to be a key before the lookup", not a particular spelling.
    #
    # A bare lookup is itself such a proof only if the KeyError path is handled:
    # an unguarded `TABLE[args[0]]` raises for a foreign code and the caller gets
    # a 500 instead of the fallback envelope.
    if f"{TABLE_NAME}[" in source:
        membership = re.search(
            rf"\bargs\[0\]\s+(?:not\s+)?in\s+{TABLE_NAME}\b", source
        )
        handles_miss = re.search(r"except\s+KeyError|\bKeyError\b|\.get\(\s*args\[0\]", source)
        if membership is None and handles_miss is None:
            failures.append(
                f"{MAP_NAME}() reads {TABLE_NAME} without proving the exception's "
                "arg is one of its keys and without handling the miss"
            )

    if re.search(rf"\b{TABLE_NAME}\b", source) and f"{TABLE_NAME}[" not in source:
        failures.append(
            f"{MAP_NAME}() never reads {TABLE_NAME}; every code would hit the "
            "generic fallback message"
        )

    # The unknown-exception path must not trust the exception's own args.
    # The pair may be declared as module constants (``_FALLBACK_CODE`` /
    # ``_FALLBACK_MESSAGE``) or assigned inline inside the function; both read as
    # "the fallback state is written down", which is the point.
    fallback = re.search(
        r"^\s*code\s*=\s*\"(?P<code>\w+)\"\n\s*message\s*=\s*\"(?P<msg>[^\"]*)\"",
        source,
        re.MULTILINE,
    ) or re.search(
        r"\b_FALLBACK_CODE\s*(?::\s*\w+)?\s*=\s*\"(?P<code>\w+)\""
        r"[\s\S]{0,200}?\b_FALLBACK_MESSAGE\s*(?::\s*\w+)?\s*=\s*\"(?P<msg>[^\"]*)\"",
        module_text or source,
    )
    if not fallback:
        failures.append(f"{MAP_NAME}() has no explicit fallback code/message pair")
    else:
        for code in table:
            if fallback.group("code") == code:
                failures.append(
                    f"the fallback code {code!r} collides with a real kernel code"
                )
        for sentence in table.values():
            if fallback.group("msg") == sentence:
                failures.append(
                    "the fallback message duplicates a kernel sentence; an unknown "
                    "exception would be indistinguishable from a real kernel error"
                )

    return failures


def parse_api_tests(text: str) -> tuple[set[str], list[str]]:
    """The API regression file must pin codes that come from a derived table."""
    failures: list[str] = []
    if "errors.rs" not in text:
        failures.append(
            "the API regression file does not derive its expectations from errors.rs"
        )
    codes = set(re.findall(r"\b[A-Z][A-Z0-9_]{3,}\b", _strip_python_comments(text)))
    return codes, failures


def _strip_python_comments(text: str) -> str:
    tree = None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    kept: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            kept.append(node.value)
    return "\n".join(kept) if kept else text


# --------------------------------------------------------------------------
# Wiring


def inspect(
    codes: dict[str, str],
    codes_failures: list[str],
    table: dict[str, str],
    source: str,
    bridge_failures: list[str],
    test_text: str | None,
    module_text: str = "",
) -> list[str]:
    failures = [*codes_failures, *bridge_failures]
    if codes and not codes_failures:
        failures.extend(inspect_bridge_mapping(codes, table, source, module_text))
    if test_text is not None:
        failures.extend(parse_api_tests(test_text)[1])
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--errors-rs", type=Path, default=ERRORS_RS)
    parser.add_argument("--bridge", type=Path, default=BRIDGE_PY)
    parser.add_argument("--api-tests", type=Path, default=API_TESTS)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    missing = [
        str(path)
        for path in (args.errors_rs, args.bridge, args.api_tests)
        if not path.is_file()
    ]
    if missing:
        print(
            "bio-core error code contract failed:\n  - missing: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    codes, codes_failures = parse_errors_rs(args.errors_rs.read_text(encoding="utf-8"))
    bridge_text = args.bridge.read_text(encoding="utf-8")
    table, source, bridge_failures = parse_bridge(bridge_text)
    failures = inspect(
        codes,
        codes_failures,
        table,
        source,
        bridge_failures,
        args.api_tests.read_text(encoding="utf-8"),
        bridge_text,
    )
    if failures:
        print("bio-core error code contract failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"bio-core error code contract passed ({len(codes)} codes bound)")
    return 0


# --------------------------------------------------------------------------
# Self-test: synthetic trees only, never this repository.

_GOOD_ERRORS_RS = '''
use thiserror::Error;

#[derive(Debug, Error)]
pub enum BioCoreError {
    #[error("empty sequence")]
    EmptySequence,
    #[error("invalid character")]
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
'''

_GOOD_BRIDGE = '''
KERNEL_ERROR_MESSAGES = {
    "EMPTY_SEQUENCE": "empty sequence",
    "INVALID_CHARACTER": "invalid character",
}


def translate_error(exc):
    code = "validation_error"
    message = "invalid sequence tool request"
    args = getattr(exc, "args", ())
    if len(args) == 2 and isinstance(args[0], str) and isinstance(args[1], str):
        if args[0] in KERNEL_ERROR_MESSAGES:
            code = args[0]
            message = KERNEL_ERROR_MESSAGES[code]
    return ValidationError(message, details={"code": code})
'''

_GOOD_TESTS = '''
"""Derived from errors.rs so it cannot drift."""
def test_codes():
    assert codes_from_errors_rs()["EMPTY_SEQUENCE"]
'''

# (name, errors_rs, bridge, tests, expected substring of a failure)
_CASES: tuple[tuple[str, str, str, str, str | None], ...] = (
    ("clean tree passes", _GOOD_ERRORS_RS, _GOOD_BRIDGE, _GOOD_TESTS, None),
    (
        "missing table entry",
        _GOOD_ERRORS_RS,
        _GOOD_BRIDGE.replace('    "INVALID_CHARACTER": "invalid character",\n', ""),
        _GOOD_TESTS,
        "has no entry in KERNEL_ERROR_MESSAGES",
    ),
    (
        "sentence disagrees with errors.rs",
        _GOOD_ERRORS_RS,
        _GOOD_BRIDGE.replace('"empty sequence"', '"invalid sequence tool request"', 1),
        _GOOD_TESTS,
        "the mapping is a second, disagreeing truth",
    ),
    (
        "table carries a code the kernel never raises",
        _GOOD_ERRORS_RS,
        _GOOD_BRIDGE.replace(
            '    "INVALID_CHARACTER": "invalid character",',
            '    "INVALID_CHARACTER": "invalid character",\n    "TIMEOUT": "timed out",',
        ),
        _GOOD_TESTS,
        "which the kernel never raises",
    ),
    (
        "mapping is never read",
        _GOOD_ERRORS_RS,
        _GOOD_BRIDGE.replace('message = KERNEL_ERROR_MESSAGES[code]', "pass"),
        _GOOD_TESTS,
        "never reads KERNEL_ERROR_MESSAGES",
    ),
    (
        "exception arg published as code",
        _GOOD_ERRORS_RS,
        _GOOD_BRIDGE.replace(
            "    if len(args) == 2 and isinstance(args[0], str) and isinstance(args[1], str):",
            "    if args and isinstance(args[0], str):",
        ).replace("        if args[0] in KERNEL_ERROR_MESSAGES:", "        if True:"),
        _GOOD_TESTS,
        "a plain Exception('timeout') would forge a machine code",
    ),
    (
        "table assignment without a membership guard",
        _GOOD_ERRORS_RS,
        _GOOD_BRIDGE.replace(
            "        if args[0] in KERNEL_ERROR_MESSAGES:", "        if True:"
        ),
        _GOOD_TESTS,
        "without proving the exception's arg is one of its keys",
    ),
    (
        "fallback collides with a real code",
        _GOOD_ERRORS_RS,
        _GOOD_BRIDGE.replace('code = "validation_error"', 'code = "EMPTY_SEQUENCE"'),
        _GOOD_TESTS,
        "collides with a real kernel code",
    ),
    (
        "fallback reuses a kernel sentence",
        _GOOD_ERRORS_RS,
        _GOOD_BRIDGE.replace(
            'message = "invalid sequence tool request"', 'message = "empty sequence"'
        ),
        _GOOD_TESTS,
        "duplicates a kernel sentence",
    ),
    (
        "variant without a sentence",
        _GOOD_ERRORS_RS.replace('    #[error("invalid character")]\n', ""),
        _GOOD_BRIDGE,
        _GOOD_TESTS,
        "has no #[error(...)] sentence",
    ),
    (
        "duplicate machine code",
        _GOOD_ERRORS_RS.replace(
            'Self::InvalidCharacter => "INVALID_CHARACTER"',
            'Self::InvalidCharacter => "EMPTY_SEQUENCE"',
        ),
        _GOOD_BRIDGE,
        _GOOD_TESTS,
        "is shared by",
    ),
    (
        "lowercase code",
        _GOOD_ERRORS_RS.replace('"INVALID_CHARACTER"', '"invalid_character"'),
        _GOOD_BRIDGE,
        _GOOD_TESTS,
        "is not an UPPER_SNAKE machine code",
    ),
    (
        "api tests stop deriving from errors.rs",
        _GOOD_ERRORS_RS,
        _GOOD_BRIDGE,
        _GOOD_TESTS.replace("errors.rs", "the kernel"),
        "does not derive its expectations from errors.rs",
    ),
)


def _self_test() -> int:
    failures: list[str] = []
    for name, errors_rs, bridge, tests, expected in _CASES:
        codes, codes_failures = parse_errors_rs(errors_rs)
        table, source, bridge_failures = parse_bridge(bridge)
        found = inspect(
            codes, codes_failures, table, source, bridge_failures, tests, bridge
        )
        if expected is None:
            if found:
                failures.append(f"{name}: expected a pass, got {found}")
            continue
        if not any(expected in item for item in found):
            failures.append(f"{name}: expected a failure containing {expected!r}, got {found}")
    if failures:
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"bio-core error code guard self-test passed ({len(_CASES)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
