#!/usr/bin/env python3
"""Fail when the Rust bio-core contract is inconsistent or the wheel is absent.

Two independent checks, so a missing prerequisite is reported as a failure,
never as a skipped pass. The static check also rejects a dangling documentation
citation in any shared script; the full contract is spelled out below.

1. Static: the crate declares a pinned toolchain, its lock file is committed,
   the CI job is registered in the shared dispatcher, the verification script
   actually installs + imports the wheel, and every documentation citation in
   every shared script resolves to a committed file and a real heading. The
   manifest is parsed, not grep-ed.
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
import re
import sys
import tomllib
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "packages" / "bio-core"

DOC_REF = re.compile(r"docs/[\w./-]+\.md(?![.\w/-])")
# A docs/ path inside a sentence is prose, not a citation. --static reads this
# very file, so the rule cannot treat its own explanation as a link. Only the
# shapes a citation really takes count: parenthesised or comma-introduced, a
# line-leading path in a block comment, or one behind the doc path itself.
PROSE_BEFORE_PATH = (
    "every", "each", "any", "a", "an", "the", "no", "doc", "docs", "document",
    "file", "path", "missing", "cited", "cites", "cite", "unresolved", "dangling",
    "real", "of", "to", "with", "from", "by", "for", "on", "into", "than", "as",
    "in", "section",
)
# A quoted label beside a path, in either order: after a comma or the word
# `section`, or in front of the path. Only the post-path form used to be
# searched, so a dangling label written first stayed silently green.
SECTION_HINT = re.compile(r'(?:,\s*|section\s+)"([^"]+)"')
SECTION_HINT_BEFORE = re.compile(r'section\s+"([^"]+)"[^"]*?$')
PRE_PATH_WINDOW = 120
# An unquoted heading is deliberately NOT parsed: the `docs/` path already
# carries a mandatory quotation in every checked form, so an unquoted run of
# prose beside it is a coincidence, not a citation. Guessing at the run's
# extent turns reading prose into a contract; see
# test_unquoted_section_heading_is_not_a_citation in test_ci_job_contracts.py.


def shared_scripts() -> list[str]:
    """Read the canonical SHARED_SCRIPTS list from the contract test.

    The wheel static gate and the contract gate must scan the same files. The
    list lives in test_ci_job_contracts.py; parsing its source with stdlib keeps
    one source of truth without importing that module (which needs PyYAML).
    """
    source = (ROOT / "scripts" / "test_ci_job_contracts.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r"SHARED_SCRIPTS\s*=\s*\((.*?)\n\)", source, re.DOTALL)
    if match is None:
        raise RuntimeError("SHARED_SCRIPTS not found in test_ci_job_contracts.py")
    return re.findall(r'"([^"]+)"', match.group(1))


def section_labels(line: str, start: int, end: int) -> list[str]:
    """Return every quoted section label attached to one docs/ path.

    Both orderings count. `end` is the end of the path match, so the post-path
    form is the window that follows it, and the pre-path form is the window
    before `start`. A label is only read when the preceding token is a comma or
    the word `section`, which is what keeps an unrelated quoted string in the
    same comment from being mistaken for a citation.
    """
    labels: list[str] = []
    after = SECTION_HINT.search(line[end:end + PRE_PATH_WINDOW])
    if after:
        labels.append(after.group(1))
    before = SECTION_HINT_BEFORE.search(line[max(0, start - PRE_PATH_WINDOW):start])
    if before:
        labels.append(before.group(1))
    return labels


def is_doc_citation(prefix: str) -> bool:
    """True when `prefix` — the text before a docs/ path — introduces a citation.

    A path inside a sentence is prose, not a citation. The checker is itself a
    shared script, so --static reads this file too and its own docstrings spell
    out what the guard accepts; those mentions must not be followed as links.
    The allowlist covers the shapes a citation actually takes — parenthesised or
    comma-introduced, line-leading in a shell block comment, or behind
    `in`/`see`/`and` — and everything else stays prose, which keeps the rule
    closed instead of chasing an open-ended list of English nouns.
    """
    stripped = prefix.rstrip()
    if stripped.endswith(("(", "（", ",", "，", ";", "；", ":", "：", "\u3001")):
        return True
    # Strip the comment marker, so a line-leading path is recognised as one.
    line_prefix = re.sub(r"^\s*(?:[\w./-]+\s+)?#+[ \t]*", "", stripped)
    first = line_prefix.split()[:1]
    if first and first[0] in ("docs", "in", "see", "cf."):
        return True
    words = re.findall(r"[\w.]+", stripped)
    return not words or words[-1].lower() not in PROSE_BEFORE_PATH


def _fold_wrapped_comments(text: str) -> str:
    """Join a wrapped `#` comment continuation onto the line it continues.

    The whole `\n` + indent + `#` prefix is replaced by the separator, so the
    fold is observable: re-emitting `"#"` with a single space would reproduce
    the matched text byte for byte and silently do nothing. ASCII prose needs a
    space where the line break stood in for one (`"build once,\n# consume"`),
    while CJK headings carry no inter-word spaces so the break must vanish
    (`"构建一次，\n# 消费一次"`).
    """
    def join(match: re.Match[str]) -> str:
        prev = match.string[match.start() - 1]
        return "" if unicodedata.east_asian_width(prev) in ("W", "F") else " "

    return re.sub(r"\n[ \t]*#[ \t]*", join, text)


def doc_ref_errors(
    text: str, root: Path = ROOT, source: str = "ci-job-steps.sh"
) -> list[str]:
    """Fail when a docs/ citation points at a missing file or section.

    A squash dropped a citation fix and reintroduced a path into a directory
    that never existed; neither review nor any gate noticed. Called on every
    shared script: every cited path plus a quoted section hint beside it. A
    dangling path or a renamed heading now fails instead of lingering.
    """
    errors: list[str] = []
    for line in _fold_wrapped_comments(text).splitlines():
        for match in DOC_REF.finditer(line):
            if not is_doc_citation(line[:match.start()]):
                continue
            ref = match.group(0)
            doc = root / ref
            if not doc.is_file():
                errors.append(f"{source} cites missing doc {ref!r}")
                continue
            labels = section_labels(line, match.start(), match.end())
            if not labels:
                continue
            headings = {
                heading.lstrip("#").strip()
                for heading in doc.read_text(encoding="utf-8").splitlines()
                if re.match(r"#{1,6}\s", heading)
            }
            for label in labels:
                if label not in headings:
                    errors.append(f"{source} cites missing section {label!r} in {ref}")
    return errors


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
        # Parse the manifest instead of grep-ing it: a string match silently
        # breaks on a reformat (`pyo3 = { version = ..., optional = true }`),
        # a workspace-inherited `pyo3.workspace = true`, or a renamed table.
        # tomllib is stdlib on 3.11+; every environment this repo declares is
        # 3.15, so a 3.10 interpreter would already be out of spec.
        try:
            cargo = tomllib.loads((CRATE / "Cargo.toml").read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            errors.append(f"Cargo.toml is not valid TOML: {exc}")
        else:
            deps = cargo.get("dependencies", {})
            for dep in ("bio", "noodles", "rust-lapper", "bio-seq", "pyo3"):
                if dep not in deps:
                    errors.append(f"Cargo.toml missing pinned dependency {dep!r}")
                elif not isinstance(deps[dep], (str, dict)) or (
                    isinstance(deps[dep], dict)
                    and "version" not in deps[dep]
                    and "workspace" not in deps[dep]
                ):
                    errors.append(f"Cargo.toml dependency {dep!r} has no version/workspace pin")

    steps = (ROOT / "scripts" / "ci-job-steps.sh").read_text(encoding="utf-8")
    if "bio-core" not in steps or "bio_core_run()" not in steps:
        errors.append("bio-core job is not registered in scripts/ci-job-steps.sh")

    # Scan every shared script, not just the dispatcher. The contract gate does
    # the same; a dangling doc citation planted in any of the others used to pass
    # --static silently. doc_ref_errors already takes a root, so this is a loop.
    for script in shared_scripts():
        path = ROOT / script
        if not path.is_file():
            errors.append(f"missing shared script: {script}")
            continue
        errors.extend(
            doc_ref_errors(path.read_text(encoding="utf-8"), root=ROOT, source=script)
        )
    verify = (ROOT / "scripts" / "verify-bio-core.sh").read_text(encoding="utf-8")
    for marker in ("maturin build", "import soymutdb_bio_core", "-m pytest", "--locked"):
        if marker not in verify:
            errors.append(f"verify-bio-core.sh missing {marker!r}")

    # The wheel is built ONCE by the bio-core job. The backend gate (api-tests,
    # a bare python:3.15) must only install it: a second build there dies on
    # missing cargo/curl/cc and adds an uncached native compile to every PR.
    backend = (ROOT / "scripts" / "verify-backend-tests.sh").read_text(encoding="utf-8")
    for marker in ("soymutdb_bio_core-*-cp315-*.whl", "--force-reinstall --no-deps",
                   "import soymutdb_bio_core as c"):
        if marker not in backend:
            errors.append(f"verify-backend-tests.sh missing wheel-install marker {marker!r}")
    for forbidden in ("maturin build", "sh.rustup.rs", "CARGO_HOME", "RUSTUP_HOME"):
        if forbidden in backend:
            errors.append(f"verify-backend-tests.sh must not build a wheel ({forbidden!r})")

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
