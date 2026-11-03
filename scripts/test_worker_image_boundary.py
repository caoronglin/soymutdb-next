"""Worker deployment boundary: contracts and its own code only, never API app code."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_SOURCE = ROOT / "apps/worker/src"
WORKER_DOCKERFILE = ROOT / "infra/docker/Dockerfile.worker"

# Grammar floor, read from the distribution itself so the pin cannot drift from
# `apps/worker/pyproject.toml` (`requires-python = ">=3.15"`).
_PYTHON_MINOR = int(
    re.search(
        r'requires-python\s*=\s*">=3\.(\d+)"',
        (ROOT / "apps/worker/pyproject.toml").read_text(encoding="utf-8"),
    ).group(1)
)


_PEP695_TYPE_PARAM = re.compile(
    r"^(?P<indent>\s*)(?P<kw>(?:async\s+)?def\s+)(?P<name>\w+)\[[^\]]*\]",
    re.MULTILINE,
)


def _worker_ast(path: Path) -> ast.AST:
    """Parse a worker source file without depending on the runner's grammar.

    The worker is a Python 3.15 package (`requires-python = ">=3.15"`) and its
    sources use PEP 695 type parameters, e.g. `def get_setting[T](...)`. A bare
    ``ast.parse`` inherits the *runner's* grammar, so on an interpreter older
    than 3.12 this contract failed with

        SyntaxError: expected '('  (def get_setting[T](...))

    which says nothing about the import direction under test. ``feature_version``
    cannot help: CPython only calls it a `ValueError` for versions it knows,
    and raises the same `SyntaxError` for a newer grammar. So the type-parameter
    list is blanked out for the parse only — import statements are unaffected and
    a genuinely malformed file still fails loudly through the second parse.
    """
    source = path.read_text(encoding="utf-8")
    stripped = _PEP695_TYPE_PARAM.sub(
        lambda m: f"{m.group('indent')}{m.group('kw')}{m.group('name')}", source
    )
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        return ast.parse(stripped, filename=str(path))


def test_worker_image_does_not_copy_or_expose_api_application() -> None:
    dockerfile = WORKER_DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY apps/api" not in dockerfile
    assert "apps/api/app" not in dockerfile
    assert "SOYMUTDB_API_APP_PATH" not in dockerfile


def test_worker_source_does_not_import_api_application_package() -> None:
    violations: list[str] = []
    for path in WORKER_SOURCE.rglob("*.py"):
        tree = _worker_ast(path)
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
