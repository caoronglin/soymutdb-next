"""Tests for task name / queue constants shared with the API and worker."""

from __future__ import annotations

from soymutdb_jobs.contract import (
    ANALYSIS_FASTP_TASK,
    ANALYSIS_SCANPY_TASK,
    BLAST_RUN_TASK,
    BUILD_STATIC_PAGES_TASK,
    EXPORT_VARIANTS_TASK,
    IMPORT_EXPRESSION_TASK,
    IMPORT_HOMOLOG_TASK,
    PAGE_BUILDER_PUBLISH_TASK,
    PAYLOAD_VERSION,
    QUEUE_ANALYSES,
    TASK_QUEUE_MAP,
)


def test_task_names_match_worker_module_layout() -> None:
    assert BLAST_RUN_TASK == "soymutdb_worker.tasks.blast.run_blast"
    assert BUILD_STATIC_PAGES_TASK == "soymutdb_worker.tasks.static_pages.build_static_pages"
    assert EXPORT_VARIANTS_TASK == "soymutdb_worker.tasks.export.export_variants"
    assert IMPORT_EXPRESSION_TASK == "soymutdb_worker.tasks.expression.import_expression_csv"
    assert IMPORT_HOMOLOG_TASK == "soymutdb_worker.tasks.homolog.import_homolog_csv"
    assert ANALYSIS_FASTP_TASK == "soymutdb_worker.tasks.analyses.run_fastp"
    assert ANALYSIS_SCANPY_TASK == "soymutdb_worker.tasks.analyses.run_scanpy"
    assert PAGE_BUILDER_PUBLISH_TASK == (
        "soymutdb_worker.tasks.page_builder_publish.publish_definition"
    )


def test_every_task_has_a_queue_route() -> None:
    for task_name in (
        BLAST_RUN_TASK,
        BUILD_STATIC_PAGES_TASK,
        EXPORT_VARIANTS_TASK,
        IMPORT_EXPRESSION_TASK,
        IMPORT_HOMOLOG_TASK,
        ANALYSIS_FASTP_TASK,
        ANALYSIS_SCANPY_TASK,
        PAGE_BUILDER_PUBLISH_TASK,
    ):
        assert task_name in TASK_QUEUE_MAP


def test_queue_routes_match_worker_routing() -> None:
    assert TASK_QUEUE_MAP[BLAST_RUN_TASK] == "blast"
    assert TASK_QUEUE_MAP[BUILD_STATIC_PAGES_TASK] == "stats"
    assert TASK_QUEUE_MAP[EXPORT_VARIANTS_TASK] == "export"
    assert TASK_QUEUE_MAP[IMPORT_EXPRESSION_TASK] == "ingest"
    assert TASK_QUEUE_MAP[IMPORT_HOMOLOG_TASK] == "ingest"
    assert TASK_QUEUE_MAP[ANALYSIS_FASTP_TASK] == "analyses"
    assert TASK_QUEUE_MAP[ANALYSIS_SCANPY_TASK] == "analyses"
    assert TASK_QUEUE_MAP[PAGE_BUILDER_PUBLISH_TASK] == "default"


def test_analyses_queue_constant() -> None:
    assert QUEUE_ANALYSES == "analyses"
    assert QUEUE_ANALYSES not in ("ingest", "export", "stats", "cleanup", "blast", "default")


def test_payload_version_is_positive_and_current() -> None:
    assert isinstance(PAYLOAD_VERSION, int)
    assert PAYLOAD_VERSION >= 1
