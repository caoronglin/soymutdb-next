#!/usr/bin/env python3
"""Prove the bio-core wheel carries the pinned CPython ABI and a native tag.

The wheel glob used by the producer and consumer is ``*-cp315-*.whl``. That
shape check alone cannot distinguish a genuine CPython 3.15 native extension
from a ``py3-none-any`` lookalike or a wheel built for the wrong CPU: both
still contain the string ``cp315`` somewhere in the version or build tag, and
``abi3`` / ``none`` wheels install cleanly on 3.15 while silently changing the
ABI contract the release images are verified against.

This guard parses the wheel filename per PEP 427, resolves the build
architecture and writes a small JSON ledger with the wheel's checksum. Both the
per-architecture image pipelines and the release publisher can then verify
that the two ledgers agree on version/ABI and each names its own native
platform tag.

Usage:
    python3 scripts/check_bio_core_wheel_tags.py --self-test
    python3 scripts/check_bio_core_wheel_tags.py --wheel-dir artifacts/wheels \
        --arch auto --out artifacts/wheels
    python3 scripts/check_bio_core_wheel_tags.py --verify-ledger <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

PYTHON_TAG = "cp315"
ABI_TAG = "cp315"
DISTRIBUTION = "soymutdb_bio_core"
ARCH_SUFFIX = {"amd64": "x86_64", "arm64": "aarch64"}
LEDGER_PREFIX = "wheel-tags-"

WHEEL_RE = re.compile(
    r"^(?P<distribution>[A-Za-z0-9_]+)-(?P<version>[A-Za-z0-9_.!+]+)"
    r"(?:-(?P<build>[0-9][A-Za-z0-9_]*))?"
    r"-(?P<python>[A-Za-z0-9_.]+)-(?P<abi>[A-Za-z0-9_.]+)"
    r"-(?P<platform>[A-Za-z0-9_.]+)\.whl$"
)


def arch_from_machine(machine: str | None = None) -> str:
    """Map uname to the release pipeline's architecture vocabulary."""
    value = (machine or platform.machine()).lower()
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        value, value
    )


@dataclass(frozen=True)
class WheelTags:
    filename: str
    distribution: str
    version: str
    python_tag: str
    abi_tag: str
    platform_tag: str
    arch: str
    sha256: str = ""


def parse(filename: str, arch: str, sha256: str = "") -> WheelTags | None:
    match = WHEEL_RE.match(filename)
    if match is None:
        return None
    return WheelTags(
        filename=filename,
        distribution=match.group("distribution").lower().replace("-", "_"),
        version=match.group("version"),
        python_tag=match.group("python"),
        abi_tag=match.group("abi"),
        platform_tag=match.group("platform"),
        arch=arch,
        sha256=sha256,
    )


def validate(tags: WheelTags | None, arch: str) -> list[str]:
    """Return every reason this wheel is not an acceptable bio-core artifact."""
    if tags is None:
        return ["filename is not a PEP 427 wheel"]
    errors: list[str] = []
    if tags.distribution != DISTRIBUTION:
        errors.append(f"distribution {tags.distribution!r} is not {DISTRIBUTION!r}")
    if tags.python_tag != PYTHON_TAG:
        errors.append(f"python tag {tags.python_tag!r} != {PYTHON_TAG!r}")
    if tags.abi_tag != ABI_TAG:
        errors.append(f"abi tag {tags.abi_tag!r} != {ABI_TAG!r} (abi3/none change the ABI)")
    suffix = ARCH_SUFFIX.get(arch)
    if suffix is None:
        errors.append(f"unknown architecture {arch!r}")
    elif tags.platform_tag == "any" or not tags.platform_tag.endswith(suffix):
        errors.append(
            f"platform tag {tags.platform_tag!r} is not native for {arch} "
            f"(expected a tag ending in {suffix})"
        )
    return errors


def scan(wheel_dir: Path, arch: str) -> tuple[WheelTags | None, list[str]]:
    if not wheel_dir.is_dir():
        return None, [f"wheel directory is missing: {wheel_dir}"]
    wheels = sorted(wheel_dir.glob("*.whl"))
    if not wheels:
        return None, [f"no wheel in {wheel_dir}"]
    if len(wheels) != 1:
        return None, [f"expected exactly one wheel, found {len(wheels)}: {[w.name for w in wheels]}"]
    wheel = wheels[0]
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    return parse(wheel.name, arch, digest), validate(parse(wheel.name, arch, digest), arch)


def ledger_path(out_dir: Path, arch: str) -> Path:
    return out_dir / f"{LEDGER_PREFIX}{arch}.json"


def write_ledger(out_dir: Path, tags: WheelTags) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = ledger_path(out_dir, tags.arch)
    path.write_text(json.dumps(asdict(tags), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def verify_ledgers(directory: Path) -> list[str]:
    """Both arches must be present, agree on ABI/version and name native tags."""
    errors: list[str] = []
    records: dict[str, WheelTags] = {}
    for arch in ARCH_SUFFIX:
        path = ledger_path(directory, arch)
        if not path.is_file():
            errors.append(f"missing {path.name}")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            tags = WheelTags(**data)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            errors.append(f"{path.name} is not a valid ledger: {exc}")
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", tags.sha256):
            errors.append(f"{path.name} has no sha256 evidence")
        found = validate(tags, arch)
        errors.extend(f"{path.name}: {reason}" for reason in found)
        records[arch] = tags
    if len(records) == 2:
        amd64, arm64 = records["amd64"], records["arm64"]
        for field in ("version", "python_tag", "abi_tag"):
            if getattr(amd64, field) != getattr(arm64, field):
                errors.append(f"arches disagree on {field}: {getattr(amd64, field)} vs {getattr(arm64, field)}")
        if amd64.platform_tag == arm64.platform_tag:
            errors.append("both arches report the same platform tag")
    return errors


def self_test() -> int:
    cases: list[tuple[str, str, bool]] = [
        ("soymutdb_bio_core-0.1.2-cp315-cp315-manylinux_2_34_x86_64.whl", "amd64", True),
        ("soymutdb_bio_core-0.1.2-cp315-cp315-manylinux_2_34_aarch64.whl", "arm64", True),
        ("soymutdb_bio_core-0.1.2-cp315-cp315-linux_x86_64.whl", "amd64", True),
        ("soymutdb_bio_core-0.1.2-1-cp315-cp315-manylinux_2_34_x86_64.whl", "amd64", True),
        ("soymutdb_bio_core-0.1.2-py3-none-any.whl", "amd64", False),
        ("soymutdb_bio_core-0.1.2-cp314-cp314-manylinux_2_34_x86_64.whl", "amd64", False),
        ("soymutdb_bio_core-0.1.2-cp315-abi3-manylinux_2_34_x86_64.whl", "amd64", False),
        ("soymutdb_bio_core-0.1.2-cp315-none-manylinux_2_34_x86_64.whl", "amd64", False),
        ("soymutdb_bio_core-0.1.2-cp315-cp315-any.whl", "amd64", False),
        ("soymutdb_bio_core-0.1.2-cp315-cp315-manylinux_2_34_aarch64.whl", "amd64", False),
        ("soymutdb_bio_core-0.1.2-cp315-cp315-manylinux_2_34_x86_64.whl", "arm64", False),
        ("other_package-0.1.2-cp315-cp315-manylinux_2_34_x86_64.whl", "amd64", False),
        ("not-a-wheel.txt", "amd64", False),
    ]
    failures: list[str] = []
    for filename, arch, expect_ok in cases:
        tags = parse(filename, arch)
        errors = validate(tags, arch)
        if (not errors) != expect_ok:
            failures.append(f"{filename} ({arch}): expected ok={expect_ok}, errors={errors}")
    assert arch_from_machine("x86_64") == "amd64"
    assert arch_from_machine("aarch64") == "arm64"
    if failures:
        for failure in failures:
            print(f"SELF-TEST FAIL: {failure}", file=sys.stderr)
        return 1
    print(f"wheel tag self-test: PASS ({len(cases)} cases)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--wheel-dir", type=Path)
    parser.add_argument("--arch", default="auto")
    parser.add_argument("--out", type=Path, help="directory to write the JSON ledger into")
    parser.add_argument("--verify-ledger", type=Path, metavar="DIR")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if args.verify_ledger is not None:
        errors = verify_ledgers(args.verify_ledger)
        if errors:
            for error in errors:
                print(f"FAIL: {error}", file=sys.stderr)
            return 1
        print("wheel tag ledger: both arches agree on ABI/version, platform tags native")
        return 0
    if args.wheel_dir is None:
        parser.error("--wheel-dir, --self-test or --verify-ledger is required")

    arch = arch_from_machine() if args.arch == "auto" else args.arch
    tags, errors = scan(args.wheel_dir, arch)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    assert tags is not None
    if args.out is not None:
        path = write_ledger(args.out, tags)
        print(f"ledger: {path}")
    print(
        f"wheel tag evidence: OK ({tags.python_tag}-{tags.abi_tag}-{tags.platform_tag}, "
        f"arch={tags.arch}, sha256={tags.sha256[:12]}…)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
