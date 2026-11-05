"""Ablation coverage for the bio-core wheel ABI/platform-tag evidence guard.

The wheel contract checks a glob (``*-cp315-*.whl``) and an import. Neither can
tell a genuine CPython 3.15 native extension from a ``py3-none-any`` lookalike
or a wheel built for the other architecture. These tests feed synthetic wheel
directories to the real checker, including the co-revert case where the guard
is removed from the producer but the ledger still looks plausible.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_bio_core_wheel_tags.py"
PRODUCER = ROOT / "scripts" / "verify-bio-core.sh"
SMOKE = ROOT / "scripts" / "smoke.sh"

GOOD_AMD64 = "soymutdb_bio_core-0.1.2-cp315-cp315-manylinux_2_34_x86_64.whl"
GOOD_ARM64 = "soymutdb_bio_core-0.1.2-cp315-cp315-manylinux_2_34_aarch64.whl"


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def wheel_dir(tmp_path: Path, name: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "wheels"
    path.mkdir(exist_ok=True)
    (path / name).write_bytes(b"fake-wheel-bytes")
    return path


def test_good_native_wheels_pass_for_their_own_arch(tmp_path: Path) -> None:
    for name, arch in ((GOOD_AMD64, "amd64"), (GOOD_ARM64, "arm64")):
        d = wheel_dir(tmp_path / arch, name)
        result = run(["--wheel-dir", str(d), "--arch", arch])
        assert result.returncode == 0, (arch, result.stdout, result.stderr)
        assert "wheel tag evidence: OK" in result.stdout


def test_bad_tag_shapes_are_rejected(tmp_path: Path) -> None:
    bad = [
        ("soymutdb_bio_core-0.1.2-py3-none-any.whl", "amd64", "python tag"),
        ("soymutdb_bio_core-0.1.2-cp314-cp314-manylinux_2_34_x86_64.whl", "amd64", "python tag"),
        ("soymutdb_bio_core-0.1.2-cp315-abi3-manylinux_2_34_x86_64.whl", "amd64", "abi tag"),
        ("soymutdb_bio_core-0.1.2-cp315-none-manylinux_2_34_x86_64.whl", "amd64", "abi tag"),
        ("soymutdb_bio_core-0.1.2-cp315-cp315-any.whl", "amd64", "platform tag"),
        (GOOD_ARM64, "amd64", "not native"),
        (GOOD_AMD64, "arm64", "not native"),
        ("other_package-0.1.2-cp315-cp315-manylinux_2_34_x86_64.whl", "amd64", "distribution"),
    ]
    for name, arch, reason in bad:
        d = wheel_dir(tmp_path / f"{name}-{arch}", name)
        result = run(["--wheel-dir", str(d), "--arch", arch])
        assert result.returncode == 1, (name, arch, result.stdout, result.stderr)
        assert reason in result.stderr, (name, reason, result.stderr)


def test_missing_or_ambiguous_wheel_fails_closed(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run(["--wheel-dir", str(empty), "--arch", "amd64"])
    assert result.returncode == 1 and "no wheel" in result.stderr

    two = wheel_dir(tmp_path / "two", GOOD_AMD64)
    (two / GOOD_ARM64).write_bytes(b"another")
    result = run(["--wheel-dir", str(two), "--arch", "amd64"])
    assert result.returncode == 1 and "exactly one wheel" in result.stderr


def test_ledger_is_written_with_checksum_and_platform_tag(tmp_path: Path) -> None:
    d = wheel_dir(tmp_path / "wheels", GOOD_AMD64)
    out = tmp_path / "out"
    result = run(["--wheel-dir", str(d), "--arch", "amd64", "--out", str(out)])
    assert result.returncode == 0, result.stderr
    ledger = json.loads((out / "wheel-tags-amd64.json").read_text(encoding="utf-8"))
    assert ledger["python_tag"] == "cp315"
    assert ledger["abi_tag"] == "cp315"
    assert ledger["platform_tag"].endswith("x86_64")
    assert ledger["arch"] == "amd64"
    assert len(ledger["sha256"]) == 64


def test_two_arch_ledgers_must_agree_and_be_native(tmp_path: Path) -> None:
    out = tmp_path / "ledgers"
    out.mkdir()
    for arch, name in (("amd64", GOOD_AMD64), ("arm64", GOOD_ARM64)):
        d = wheel_dir(tmp_path / arch, name)
        assert run(["--wheel-dir", str(d), "--arch", arch, "--out", str(out)]).returncode == 0
    assert run(["--verify-ledger", str(out)]).returncode == 0

    # A stale/mismatched arm64 ledger (wrong arch tag) must be caught.
    arm = json.loads((out / "wheel-tags-arm64.json").read_text(encoding="utf-8"))
    arm["platform_tag"] = "manylinux_2_34_x86_64"
    arm["filename"] = GOOD_AMD64
    (out / "wheel-tags-arm64.json").write_text(json.dumps(arm), encoding="utf-8")
    result = run(["--verify-ledger", str(out)])
    assert result.returncode == 1
    assert "not native for arm64" in result.stderr or "same platform tag" in result.stderr

    # Missing one arch is incomplete evidence, not a pass.
    (out / "wheel-tags-arm64.json").unlink()
    result = run(["--verify-ledger", str(out)])
    assert result.returncode == 1 and "missing" in result.stderr


def test_producer_and_contracts_layer_are_wired() -> None:
    """Guard removal from the producer or smoke layer is caught by these bytes."""
    producer = PRODUCER.read_text(encoding="utf-8")
    assert "check_bio_core_wheel_tags.py" in producer, "producer must emit the tag ledger"
    smoke = SMOKE.read_text(encoding="utf-8")
    assert "scripts/test_bio_core_wheel_tags.py" in smoke, "ablation suite must be in contracts layer"
