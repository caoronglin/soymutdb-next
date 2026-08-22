"""Worker deployment boundary: contracts and its own code only, never API app code."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_SOURCE = ROOT / "apps/worker/src"
WORKER_DOCKERFILE = ROOT / "infra/docker/Dockerfile.worker"


def test_worker_image_does_not_copy_or_expose_api_application() -> None:
    dockerfile = WORKER_DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY apps/api" not in dockerfile
    assert "apps/api/app" not in dockerfile
    assert "SOYMUTDB_API_APP_PATH" not in dockerfile


def test_worker_source_does_not_import_api_application_package() -> None:
    violations: list[str] = []
    for path in WORKER_SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            if any(name == "app" or name.startswith("app.") for name in names):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert violations == []
