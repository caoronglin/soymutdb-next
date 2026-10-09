"""Protect the real static artifact gate from regression and false positives."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


SCANNER = Path(__file__).resolve().with_name("check-production-artifact.sh")


def scan(tmp_path: Path, content: str, *, demo: bool = True) -> subprocess.CompletedProcess[str]:
    (tmp_path / "index.html").write_text("<!doctype html><title>Smoke</title>", encoding="utf-8")
    (tmp_path / "app.js").write_text(content, encoding="utf-8")
    command = ["bash", str(SCANNER), str(tmp_path)]
    if demo:
        command.append("--allow-demo")
    return subprocess.run(command, capture_output=True, text=True, check=False)


@pytest.mark.parametrize("marker", [
    "api.example.com", "jbrowse.example.com", "CHANGE_ME",
    "change-me", "localhost:8000",
])
def test_demo_rejects_real_placeholder_or_loopback_origin(tmp_path: Path, marker: str) -> None:
    result = scan(tmp_path, "const endpoint = " + repr(marker) + ";")
    assert result.returncode == 1, (marker, result.stdout, result.stderr)


def test_demo_allows_non_origin_build_variable_name(tmp_path: Path) -> None:
    result = scan(tmp_path, "const name = 'VITE_API_BASE_URL';")
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_demo_and_production_fixtures_are_separate(tmp_path: Path) -> None:
    assert scan(tmp_path, "const id = 'SMDB-00001';", demo=True).returncode == 0
    assert scan(tmp_path, "const id = 'SMDB-00001';", demo=False).returncode == 1
