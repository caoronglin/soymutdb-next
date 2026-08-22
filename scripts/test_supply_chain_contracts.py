"""Regression contracts for the supply-chain shell checks."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_supply_chain_check_allows_non_secret_bind_address_default(
    tmp_path: Path,
) -> None:
    """A safe bind-address default must not be treated as a secret default."""
    checker = tmp_path / "scripts" / "check-supply-chain.sh"
    checker.parent.mkdir()
    shutil.copy2(REPOSITORY_ROOT / "scripts" / "check-supply-chain.sh", checker)

    for service in ("api", "worker"):
        lock = tmp_path / "apps" / service / "uv.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("version = 1\n", encoding="utf-8")

    (tmp_path / "docker-compose.yml").write_text(
        """services:
  jbrowse:
    ports:
      - \"${JBROWSE_BIND_ADDRESS:-127.0.0.1}:${JBROWSE_PORT:-8082}:80\"
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(checker)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_supply_chain_check_rejects_nonempty_postgres_password_default(
    tmp_path: Path,
) -> None:
    """A literal PostgreSQL password fallback must remain a hard failure."""
    checker = tmp_path / "scripts" / "check-supply-chain.sh"
    checker.parent.mkdir()
    shutil.copy2(REPOSITORY_ROOT / "scripts" / "check-supply-chain.sh", checker)

    for service in ("api", "worker"):
        lock = tmp_path / "apps" / service / "uv.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("version = 1\n", encoding="utf-8")

    (tmp_path / "docker-compose.yml").write_text(
        """services:
  postgres:
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-unsafe}
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(checker)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "POSTGRES_PASSWORD" in result.stdout
    assert "FAIL: production compose contains insecure secret defaults" in result.stderr
