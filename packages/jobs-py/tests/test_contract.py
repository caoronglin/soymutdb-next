"""Tests for task name / queue constants shared with the API and worker."""

from __future__ import annotations

from soymutdb_jobs.contract import (
    BLAST_RUN_TASK,
    BUILD_STATIC_PAGES_TASK,
    EXPORT_VARIANTS_TASK,
    IMPORT_EXPRESSION_TASK,
    IMPORT_HOMOLOG_TASK,
    PAYLOAD_VERSION,
    TASK_QUEUE_MAP,
)


def test_task_names_match_worker_module_layout() -> None:
    assert BLAST_RUN_TASK == "soymutdb_worker.tasks.blast.run_blast"
    assert BUILD_STATIC_PAGES_TASK == "soymutdb_worker.tasks.static_pages.build_static_pages"
    assert EXPORT_VARIANTS_TASK == "soymutdb_worker.tasks.export.export_variants"
    assert IMPORT_EXPRESSION_TASK == "soymutdb_worker.tasks.expression.import_expression_csv"
    assert IMPORT_HOMOLOG_TASK == "soymutdb_worker.tasks.homolog.import_homolog_csv"


def test_every_task_has_a_queue_route() -> None:
    for task_name in (
        BLAST_RUN_TASK,
        BUILD_STATIC_PAGES_TASK,
        EXPORT_VARIANTS_TASK,
        IMPORT_EXPRESSION_TASK,
        IMPORT_HOMOLOG_TASK,
    ):
        assert task_name in TASK_QUEUE_MAP


def test_queue_routes_match_worker_routing() -> None:
    assert TASK_QUEUE_MAP[BLAST_RUN_TASK] == "blast"
    assert TASK_QUEUE_MAP[BUILD_STATIC_PAGES_TASK] == "stats"
    assert TASK_QUEUE_MAP[EXPORT_VARIANTS_TASK] == "export"
    assert TASK_QUEUE_MAP[IMPORT_EXPRESSION_TASK] == "ingest"
    assert TASK_QUEUE_MAP[IMPORT_HOMOLOG_TASK] == "ingest"


def test_payload_version_is_positive_and_current() -> None:
    assert isinstance(PAYLOAD_VERSION, int)
    assert PAYLOAD_VERSION >= 1
