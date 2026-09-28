#!/usr/bin/env python3
"""Fail-closed scan preventing private values from entering external artifacts.

The checker deliberately scans the caller-supplied sentinel values only.  A
generic field name such as ``internal_id`` is not a leak criterion by itself.

When no ``--sentinel`` is supplied the checker falls back to
:data:`DEFAULT_SENTINELS`; ``--print-default-sentinels`` exposes that exact
list so shell gates can extend it without duplicating the literals.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

#: Values that must never appear in an external artifact.  The internal
#: noindex marker and the reserved internal origin host are both leaks even
#: though neither is a generic field name.  Kept as a module constant so the
#: scan and the shell verifier share one source of truth.
DEFAULT_SENTINELS: tuple[str, ...] = (
    "noindex, nofollow, noarchive",
    "internal.soymutdb.invalid",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-root", type=Path)
    parser.add_argument("--internal-root", type=Path)
    parser.add_argument(
        "--sentinel",
        action="append",
        dest="sentinels",
        metavar="VALUE",
        help="repeatable; defaults to the built-in default sentinel set",
    )
    parser.add_argument(
        "--print-default-sentinels",
        action="store_true",
        help="print one built-in default sentinel per line and exit",
    )
    parser.add_argument(
        "--self-test", action="store_true", help="run deterministic built-in checks"
    )
    return parser


def _validate_roots(external: Path | None, internal: Path | None) -> str | None:
    if external is None or internal is None:
        return "external and internal artifact roots are required"
    try:
        external_resolved = external.resolve(strict=True)
        internal_resolved = internal.resolve(strict=True)
    except OSError:
        return "artifact root is missing or cannot be resolved"
    if external_resolved == internal_resolved:
        return "external and internal artifact roots must be distinct"
    if (
        external_resolved in internal_resolved.parents
        or internal_resolved in external_resolved.parents
    ):
        return "external and internal artifact roots must not overlap"
    for root in (external_resolved, internal_resolved):
        if not root.is_dir() or not os.access(root, os.R_OK | os.X_OK):
            return "artifact root is missing or not readable"
    return None


def _validate_sentinels(sentinels: list[str] | None) -> str | None:
    if not sentinels:
        return "at least one non-empty sentinel is required"
    if any(not value or "\x00" in value for value in sentinels):
        return "sentinels must be non-empty and must not contain NUL"
    return None


def missing_html_entry(external: Path) -> str | None:
    """Return a diagnostic when the artifact has no top-level HTML entry.

    The internal variant is already required to expose ``*.html`` by
    ``verify-site-variant-artifacts.sh``; this keeps the external side
    symmetric instead of silently passing when its entry document is gone.
    """
    try:
        entries = sorted(
            path.name
            for path in external.iterdir()
            if path.suffix == ".html" and not path.is_symlink()
        )
    except OSError:
        return "external artifact root cannot be listed"
    if not entries:
        return (
            "external artifact is missing a top-level HTML entry (external/index.html)"
        )
    return None


def scan_external(external: Path, sentinels: list[str]) -> list[str]:
    """Return stable, non-secret diagnostics for sentinel hits or read errors.

    Sentinel hits are reported for file contents, file path names, and
    directory names -- including empty directories, which the file loop alone
    never reaches.  A directory hit is suppressed when a file inside it
    already reported the same sentinel, so one injection cannot produce two
    diagnostics for the same location.
    """
    findings: list[str] = []
    root = external.resolve(strict=True)
    entries = []
    seen: set[bytes] = set()
    for index, value in enumerate(sentinels, start=1):
        encoded = value.encode("utf-8")
        if encoded not in seen:
            entries.append((index, value, encoded))
            seen.add(encoded)

    def safe_path(relative: str) -> str:
        for index, value, _ in entries:
            relative = relative.replace(value, f"<sentinel-{index}>")
        return relative

    def on_walk_error(error: OSError) -> None:
        findings.append("artifact traversal failed")

    directory_paths: list[str] = []
    file_path_hits: list[tuple[int, str]] = []
    for directory, directories, filenames in os.walk(
        root, topdown=True, followlinks=False, onerror=on_walk_error
    ):
        relative_directory = Path(directory).relative_to(root).as_posix()
        if relative_directory != ".":
            directory_paths.append(relative_directory)
        for name in list(directories):
            path = Path(directory) / name
            if path.is_symlink():
                findings.append(
                    "symlink not allowed: "
                    + safe_path((Path(relative_directory) / name).as_posix())
                )
                directories.remove(name)
        for filename in sorted(filenames):
            path = Path(directory) / filename
            relative = path.relative_to(root).as_posix()
            display_relative = safe_path(relative)
            if path.is_symlink():
                findings.append(f"symlink not allowed: {display_relative}")
                continue
            for index, value, _ in entries:
                if value in relative:
                    findings.append(
                        f"sentinel #{index} found in path: {display_relative}"
                    )
                    file_path_hits.append((index, relative))
            try:
                content = path.read_bytes()
            except OSError:
                findings.append(f"unreadable file: {display_relative}")
                continue
            for index, _, sentinel in entries:
                if sentinel in content:
                    findings.append(f"sentinel #{index} found: {display_relative}")
    # Directory names are checked after the walk so a hit already reported for
    # a file inside the directory is not repeated for the directory itself.
    for relative_directory in directory_paths:
        for index, value, _ in entries:
            if value not in relative_directory:
                continue
            covered_by_file = any(
                hit_index == index and hit_path.startswith(relative_directory + "/")
                for hit_index, hit_path in file_path_hits
            )
            if not covered_by_file:
                findings.append(
                    "sentinel #%d found in directory path: %s"
                    % (index, safe_path(relative_directory))
                )
    # Sort by relative path and then the complete diagnostic so neither
    # traversal order nor set iteration can affect output.
    return sorted(
        set(findings),
        key=lambda finding: (finding.rsplit(": ", 1)[-1], finding),
    )


def self_test() -> None:
    assert DEFAULT_SENTINELS, "default sentinel set must not be empty"
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        external = root / "external"
        internal = root / "internal"
        (external / "nested").mkdir(parents=True)
        internal.mkdir()
        (external / "nested" / "clean.txt").write_bytes(b"public")
        assert scan_external(external, ["private-value"]) == []
        (external / "nested" / "hit.bin").write_bytes(b"\x00private-value\xff")
        assert scan_external(external, ["private-value"])
        (external / "dir-private-value").mkdir()
        assert any(
            "directory path" in finding
            for finding in scan_external(external, ["private-value"])
        )
    print("site artifact isolation self-test passed")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.print_default_sentinels:
        if (
            args.self_test
            or args.external_root is not None
            or args.internal_root is not None
            or args.sentinels is not None
        ):
            print(
                "FAIL: --print-default-sentinels cannot be combined with other arguments",
                file=sys.stderr,
            )
            return 2
        for value in DEFAULT_SENTINELS:
            print(value)
        return 0
    if args.self_test:
        if (
            args.external_root is not None
            or args.internal_root is not None
            or args.sentinels is not None
        ):
            print(
                "FAIL: --self-test cannot be combined with artifact arguments",
                file=sys.stderr,
            )
            return 2
        self_test()
        return 0
    root_error = _validate_roots(args.external_root, args.internal_root)
    if args.sentinels is None:
        sentinels = list(DEFAULT_SENTINELS)
    else:
        sentinels = args.sentinels
    sentinel_error = _validate_sentinels(sentinels)
    if root_error or sentinel_error:
        print("FAIL: invalid artifact isolation configuration", file=sys.stderr)
        return 2
    assert args.external_root is not None
    entry_error = missing_html_entry(args.external_root)
    try:
        findings = scan_external(args.external_root, sentinels)
    except OSError:
        print("FAIL: external artifact root cannot be scanned", file=sys.stderr)
        return 2
    if entry_error:
        print(f"FAIL: {entry_error}", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1
    if findings:
        print(
            "FAIL: external artifact contains protected values or unreadable files",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1
    print("OK: external artifact contains no supplied protected values")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
