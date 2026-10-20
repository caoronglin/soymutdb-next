#!/usr/bin/env python3
"""Fail when the retired ClickHouse lane is re-imported by a runtime module.

`apps/api/app/services/clickhouse_service.py` is documented as a *migration and
test surface only*: PostgreSQL is authoritative for variant facts, statistics
and analytics, and no runtime module may reach the historical driver.  That is a
prose contract today — `scripts/test_native_compose_cutover_contracts.py` proves
the Compose topologies dropped the service, but nothing proves the Python import
graph did.  A single new `from ..services.clickhouse_service import ...` would
silently reintroduce a second authoritative read path.

The guard therefore enforces three import-shape rules:

1. No runtime module may import the retired service.
2. No runtime module may import ``clickhouse_connect`` at module scope.  A lazy
   import inside a function is allowed, because that is how the documented
   legacy tooling keeps working without the optional driver installed.
3. The retired module itself may still name the driver (a ``TYPE_CHECKING``
   import is how its exception types stay typed).

Scope is the shipped runtime trees only: ``apps/api/app`` and
``apps/worker/src/soymutdb_worker``.  The Python 3.14 legacy lane
(``infra/docker/Dockerfile.migrate-clickhouse``, ``scripts/assert-clickhouse-migration.py``)
and the historical schema contract are deliberately out of scope; retiring them
is a separate, audited change.
"""
from __future__ import annotations

import argparse
import ast
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Runtime trees that must never take a module-scope ClickHouse driver import.
RUNTIME_TREES = (
    "apps/api/app",
    "apps/worker/src/soymutdb_worker",
)

#: The retired service module is allowed to name the driver for its own typing.
DRIVER_REFERENCE_EXEMPT = (
    "apps/api/app/services/clickhouse_service.py",
)

RETIRED_SERVICE = "clickhouse_service"
DRIVER = "clickhouse_connect"


def names_module(name: str | None, module_name: str) -> bool:
    """True when a dotted import target names ``module_name`` (or a submodule).

    The repository uses both absolute (``app.services.clickhouse_service``) and
    relative (``from ...services.clickhouse_service import X``) forms, and a
    driver import may target a submodule
    (``from clickhouse_connect.driver.asyncclient import AsyncClient``).  Matching
    one dotted *component* covers every form without matching an unrelated name
    that merely ends with the same text.
    """
    if not name:
        return False
    return module_name in name.split(".")


def module_level_driver_imports(path: Path, source: str) -> list[int]:
    """Return line numbers of ``clickhouse_connect`` imports at module scope.

    A function-local import is deliberately not reported: the documented legacy
    entry points import the driver lazily so the 3.15 runtime image never needs
    the optional wheel installed.
    """
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:  # pragma: no cover - the repo is parsed by ruff/mypy too
        return []

    found: list[int] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                # Anything nested in a def/class/lambda is not module scope.
                continue
            if isinstance(child, ast.Import):
                for alias in child.names:
                    if names_module(alias.name, DRIVER):
                        found.append(child.lineno)
            elif isinstance(child, ast.ImportFrom):
                if names_module(child.module, DRIVER):
                    found.append(child.lineno)
                for alias in child.names:
                    if names_module(alias.name, DRIVER):
                        found.append(child.lineno)
            visit(child)

    visit(tree)
    return sorted(set(found))


def importers_of_retired_service(path: Path, source: str) -> list[int]:
    """Return line numbers importing the retired service, by module or symbol."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:  # pragma: no cover
        return []

    found: list[int] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Import):
                for alias in child.names:
                    if names_module(alias.name, RETIRED_SERVICE):
                        found.append(child.lineno)
            elif isinstance(child, ast.ImportFrom):
                if names_module(child.module, RETIRED_SERVICE):
                    found.append(child.lineno)
                else:
                    for alias in child.names:
                        # ``from . import clickhouse_service`` /
                        # ``from app.services import clickhouse_service``
                        if names_module(alias.name, RETIRED_SERVICE):
                            found.append(child.lineno)
            visit(child)

    visit(tree)
    return sorted(set(found))


def check(root: Path) -> list[str]:
    violations: list[str] = []
    for tree_name in RUNTIME_TREES:
        tree_root = root / tree_name
        if not tree_root.is_dir():
            violations.append(f"{tree_name}: runtime tree is missing")
            continue
        for path in sorted(tree_root.rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            source = path.read_text(encoding="utf-8")
            for line in importers_of_retired_service(path, source):
                violations.append(
                    f"{relative}:{line}: imports the retired {RETIRED_SERVICE}; "
                    "PostgreSQL is the authoritative read path"
                )
            if relative in DRIVER_REFERENCE_EXEMPT:
                continue
            for line in module_level_driver_imports(path, source):
                violations.append(
                    f"{relative}:{line}: module-scope `{DRIVER}` import; "
                    "the historical driver is a legacy-migration lane only"
                )
    return violations


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        api = root / "apps/api/app"
        worker = root / "apps/worker/src/soymutdb_worker"
        (api / "services").mkdir(parents=True)
        (api / "api/v1").mkdir(parents=True)
        worker.mkdir(parents=True)

        # Allowed: lazy driver import inside a function body.
        (api / "core.py").write_text(
            "def get_client():\n    import clickhouse_connect\n    return clickhouse_connect\n",
            encoding="utf-8",
        )
        # Allowed: the retired module naming the driver under TYPE_CHECKING.
        (api / "services" / "clickhouse_service.py").write_text(
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from clickhouse_connect.driver.asyncclient import AsyncClient\n",
            encoding="utf-8",
        )
        # Allowed: unrelated runtime module.
        (api / "api/v1/variants.py").write_text(
            "from ...services.variant_service import V\n", encoding="utf-8"
        )

        assert check(root) == [], check(root)

        # Reject: a runtime module importing the retired service.
        (api / "api/v1/stats.py").write_text(
            "from ...services.clickhouse_service import ClickHouseService\n", encoding="utf-8"
        )
        results = check(root)
        assert any("imports the retired clickhouse_service" in item for item in results), results

        # Reject: a module-scope driver import outside the retired module.
        (api / "api/v1/stats.py").write_text("import clickhouse_connect\n", encoding="utf-8")
        results = check(root)
        assert any("module-scope `clickhouse_connect` import" in item for item in results), results

        # Reject: a driver import at module scope inside a worker task.
        (worker / "task.py").write_text(
            "from clickhouse_connect import get_client\n", encoding="utf-8"
        )
        results = check(root)
        assert any("module-scope `clickhouse_connect` import" in item for item in results), results

        # Reject: ``from ..services import clickhouse_service`` (symbol form).
        (worker / "task.py").write_text(
            "from app.services import clickhouse_service\n", encoding="utf-8"
        )
        results = check(root)
        assert any("imports the retired clickhouse_service" in item for item in results), results

    print("retired-lane boundary guard self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    violations = check(args.root)
    if violations:
        print("Retired ClickHouse lane leaked into the runtime import graph:")
        for item in violations:
            print(" - " + item)
        return 1
    print(f"Retired-lane boundary guard passed ({len(RUNTIME_TREES)} runtime tree(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
