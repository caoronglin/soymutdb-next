#!/usr/bin/env python3
"""Enforce the backend import-direction and service-cycle contract."""
from __future__ import annotations

import argparse
import ast
import tempfile
from pathlib import Path


def module_for(app_root: Path, path: Path) -> str:
    relative = path.relative_to(app_root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imported_module(current: str, node: ast.ImportFrom) -> str:
    target = node.module or ""
    if node.level == 0:
        return target
    package = current.split(".")[:-1]
    trim = max(0, node.level - 1)
    base = package[: len(package) - trim] if trim else package
    return ".".join([*base, *target.split(".")]) if target else ".".join(base)


def imports_for(path: Path, current: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            resolved = imported_module(current, node)
            if node.module is None:
                result.update(resolved + "." + alias.name for alias in node.names)
            else:
                result.add(resolved)
    return {item for item in result if item}


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    cycles: set[tuple[str, ...]] = set()

    def visit(node: str) -> None:
        if node in visiting:
            start = stack.index(node)
            cycle = stack[start:] + [node]
            cycles.add(tuple(cycle))
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for child in sorted(graph.get(node, ())):
            visit(child)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for item in sorted(graph):
        visit(item)
    return [list(cycle) for cycle in sorted(cycles)]


def check(app_root: Path) -> list[str]:
    services = app_root / "services"
    models = app_root / "models"
    api_v1 = app_root / "api" / "v1"
    violations: list[str] = []
    graph: dict[str, set[str]] = {}

    for path in sorted(services.rglob("*.py")):
        current = module_for(app_root, path)
        imported = imports_for(path, current)
        for name in sorted(imported):
            if name == "api.v1" or name.startswith("api.v1."):
                violations.append(f"{path}: services must not import api/v1 ({name})")
        graph[current] = {name for name in imported if name in graph or name.startswith("services.")}

    # Keep only real in-repository service modules so external namespace names cannot form edges.
    service_modules = {module_for(app_root, path) for path in services.rglob("*.py")}
    graph = {node: {edge for edge in edges if edge in service_modules} for node, edges in graph.items()}

    for path in sorted(models.rglob("*.py")):
        current = module_for(app_root, path)
        for name in sorted(imports_for(path, current)):
            if name == "services" or name.startswith("services."):
                violations.append(f"{path}: models must not import services ({name})")

    for cycle in find_cycles(graph):
        violations.append("service import cycle: " + " -> ".join(cycle))
    return violations


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "app"
        for directory in (root / "services", root / "models", root / "api" / "v1"):
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "__init__.py").write_text("", encoding="utf-8")
        (root / "services" / "a.py").write_text("from ..api.v1 import routes\nfrom . import b\n", encoding="utf-8")
        (root / "services" / "b.py").write_text("from . import a\n", encoding="utf-8")
        (root / "models" / "bad.py").write_text("from ..services import a\n", encoding="utf-8")
        results = check(root)
        expected = ("services must not import api/v1", "models must not import services", "service import cycle")
        if not all(any(marker in item for item in results) for marker in expected):
            raise AssertionError(f"architecture guard self-test failed: {results}")
    print("architecture guard self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, default=Path("apps/api/app"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    violations = check(args.app_root)
    if violations:
        print("Architecture guard failed:")
        for item in violations:
            print(" - " + item)
        return 1
    print("Architecture guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
