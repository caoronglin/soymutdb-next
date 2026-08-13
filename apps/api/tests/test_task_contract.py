"""Task-name contract tests shared by the API and Celery worker."""

from __future__ import annotations

import sys
from pathlib import Path


def test_api_blast_task_name_is_registered_by_worker() -> None:
    """The API's BLAST task name must resolve in the worker registry."""
    project_root = Path(__file__).resolve().parents[3]
    api_root = project_root / "apps" / "api"
    worker_src = project_root / "apps" / "worker" / "src"
    sys.path[:0] = [str(api_root), str(worker_src)]

    from soymutdb_worker.main import celery_app

    from app.core.task_contract import BLAST_RUN_TASK

    # Import only the module whose task contract is under test.  Importing the
    # whole worker eagerly pulls optional SSG dependencies (e.g. dominate).
    celery_app.loader.import_task_module("soymutdb_worker.tasks.blast")

    assert BLAST_RUN_TASK in celery_app.tasks
    assert celery_app.conf.task_routes["soymutdb_worker.tasks.blast.*"]["queue"] == "blast"
