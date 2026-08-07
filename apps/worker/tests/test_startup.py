"""Celery worker startup smoke tests."""

from __future__ import annotations


def test_worker_startup_registers_tasks_and_all_runtime_queues() -> None:
    """Importing the worker app must register tasks for every routed queue."""
    from soymutdb_worker.main import celery_app

    celery_app.loader.import_default_modules()

    assert "soymutdb_worker.tasks.blast.run_blast" in celery_app.tasks
    assert set(celery_app.conf.task_routes) >= {
        "soymutdb_worker.tasks.ingest.*",
        "soymutdb_worker.tasks.export.*",
        "soymutdb_worker.tasks.stats.*",
        "soymutdb_worker.tasks.cleanup.*",
        "soymutdb_worker.tasks.blast.*",
    }
