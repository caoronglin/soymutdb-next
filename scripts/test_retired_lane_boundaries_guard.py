"""Regression tests for the retired-lane import-boundary guard entry point.

The guard itself is exercised by ``scripts/check_retired_lane_boundaries.py
--self-test``; these tests drive the same functions against a synthetic tree so
a future refactor of the matcher cannot silently stop matching.
"""
from pathlib import Path

import pytest

from scripts import check_retired_lane_boundaries as guard


@pytest.fixture
def tree(tmp_path):
    api = tmp_path / "apps/api/app"
    worker = tmp_path / "apps/worker/src/soymutdb_worker"
    (api / "services").mkdir(parents=True)
    (api / "api/v1").mkdir(parents=True)
    worker.mkdir(parents=True)
    (api / "services/clickhouse_service.py").write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from clickhouse_connect.driver.asyncclient import AsyncClient\n",
        encoding="utf-8",
    )
    return tmp_path, api, worker


def put(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_clean_tree_passes(tree):
    root, api, worker = tree
    put(api / "api/v1/variants.py", "from ...services.variant_service import V\n")
    put(
        worker / "task.py",
        "def run():\n    import clickhouse_connect\n    return clickhouse_connect\n",
    )
    assert guard.check(root) == []


def test_missing_runtime_tree_fails(tmp_path):
    assert any("runtime tree is missing" in item for item in guard.check(tmp_path))


@pytest.mark.parametrize(
    "source",
    [
        "from ...services.clickhouse_service import ClickHouseService\n",
        "from app.services.clickhouse_service import ClickHouseService\n",
        "from app.services import clickhouse_service\n",
        "import app.services.clickhouse_service\n",
    ],
)
def test_retired_service_import_is_rejected(tree, source):
    root, api, _ = tree
    put(api / "api/v1/stats.py", source)
    results = guard.check(root)
    assert any("imports the retired clickhouse_service" in item for item in results), results


@pytest.mark.parametrize(
    "source",
    [
        "import clickhouse_connect\n",
        "from clickhouse_connect import get_client\n",
        "from clickhouse_connect.driver.asyncclient import AsyncClient\n",
        "if True:\n    import clickhouse_connect\n",
    ],
)
def test_module_scope_driver_import_is_rejected(tree, source):
    root, api, worker = tree
    put(api / "api/v1/stats.py", source)
    assert any("module-scope" in item for item in guard.check(root))
    put(api / "api/v1/stats.py", "ok = 1\n")
    put(worker / "task.py", source)
    assert any("module-scope" in item for item in guard.check(root))


def test_function_local_driver_import_is_allowed(tree):
    root, api, _ = tree
    put(
        api / "core.py",
        "async def client():\n"
        "    import clickhouse_connect\n"
        "    return await clickhouse_connect.get_async_client()\n",
    )
    assert guard.check(root) == []


def test_retired_module_may_still_name_the_driver(tree):
    root, _, _ = tree
    assert guard.check(root) == []
