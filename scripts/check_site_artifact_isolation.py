#!/usr/bin/env python3
"""Fail-closed scan preventing private values from entering external artifacts.

The checker deliberately scans the caller-supplied sentinel values only.  A
generic field name such as ``internal_id`` is not a leak criterion by itself.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-root", type=Path)
    parser.add_argument("--internal-root", type=Path)
    parser.add_argument(
        "--sentinel", action="append", dest="sentinels", metavar="VALUE"
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


def scan_external(external: Path, sentinels: list[str]) -> list[str]:
    """Return stable, non-secret diagnostics for sentinel hits or read errors."""
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

    for directory, directories, filenames in os.walk(
        root, topdown=True, followlinks=False, onerror=on_walk_error
    ):
        relative_directory = Path(directory).relative_to(root).as_posix()
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
                    findings.append(f"sentinel #{index} found in path: {display_relative}")
            try:
                content = path.read_bytes()
            except OSError:
                findings.append(f"unreadable file: {display_relative}")
                continue
            for index, _, sentinel in entries:
                if sentinel in content:
                    findings.append(f"sentinel #{index} found: {display_relative}")
    # Sort by relative path and then the complete diagnostic so neither
    # traversal order nor set iteration can affect output.
    return sorted(
        set(findings),
        key=lambda finding: (finding.rsplit(": ", 1)[-1], finding),
    )


def self_test() -> None:
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
    print("site artifact isolation self-test passed")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.self_test:
        if (
            args.external_root is not None
            or args.internal_root is not None
            or args.sentinels is not None
        ):
            print("FAIL: --self-test cannot be combined with artifact arguments", file=sys.stderr)
            return 2
        self_test()
        return 0
    root_error = _validate_roots(args.external_root, args.internal_root)
    sentinel_error = _validate_sentinels(args.sentinels)
    if root_error or sentinel_error:
        print("FAIL: invalid artifact isolation configuration", file=sys.stderr)
        return 2
    assert args.external_root is not None
    assert args.sentinels is not None
    try:
        findings = scan_external(args.external_root, args.sentinels)
    except OSError:
        print("FAIL: external artifact root cannot be scanned", file=sys.stderr)
        return 2
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
