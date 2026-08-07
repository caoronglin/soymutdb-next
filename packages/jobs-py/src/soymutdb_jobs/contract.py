"""Task name and queue constants shared by API dispatchers and the worker.

These names were originally defined in ``apps/api/app/core/task_contract.py``;
the API module now re-exports them from this package so the worker no longer
imports API source code.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Task names (must match the ``name=`` argument of the Celery task decorators)
# ---------------------------------------------------------------------------

BLAST_RUN_TASK: Final[str] = "soymutdb_worker.tasks.blast.run_blast"
BUILD_STATIC_PAGES_TASK: Final[str] = "soymutdb_worker.tasks.static_pages.build_static_pages"
EXPORT_VARIANTS_TASK: Final[str] = "soymutdb_worker.tasks.export.export_variants"
IMPORT_EXPRESSION_TASK: Final[str] = "soymutdb_worker.tasks.expression.import_expression_csv"
IMPORT_HOMOLOG_TASK: Final[str] = "soymutdb_worker.tasks.homolog.import_homolog_csv"
ANALYSIS_FASTP_TASK: Final[str] = "soymutdb_worker.tasks.analyses.run_fastp"
ANALYSIS_SCANPY_TASK: Final[str] = "soymutdb_worker.tasks.analyses.run_scanpy"

# ---------------------------------------------------------------------------
# Celery queues (must match ``task_routes`` in the worker application)
# ---------------------------------------------------------------------------

QUEUE_INGEST: Final[str] = "ingest"
QUEUE_BLAST: Final[str] = "blast"
QUEUE_EXPORT: Final[str] = "export"
QUEUE_STATS: Final[str] = "stats"
QUEUE_CLEANUP: Final[str] = "cleanup"
QUEUE_ANALYSES: Final[str] = "analyses"
QUEUE_DEFAULT: Final[str] = "default"

#: Queue used for a given task name (fallback: ``default``).
TASK_QUEUE_MAP: Final[dict[str, str]] = {
    BLAST_RUN_TASK: QUEUE_BLAST,
    BUILD_STATIC_PAGES_TASK: QUEUE_STATS,
    EXPORT_VARIANTS_TASK: QUEUE_EXPORT,
    IMPORT_EXPRESSION_TASK: QUEUE_INGEST,
    IMPORT_HOMOLOG_TASK: QUEUE_INGEST,
    ANALYSIS_FASTP_TASK: QUEUE_ANALYSES,
    ANALYSIS_SCANPY_TASK: QUEUE_ANALYSES,
}

# ---------------------------------------------------------------------------
# Payload versioning
# ---------------------------------------------------------------------------

#: Current ``JobPayload.payload_version``.  Bump when the payload shape
#: changes in a way older workers cannot interpret; workers reject unknown
#: versions instead of guessing.
PAYLOAD_VERSION: Final[int] = 1

__all__ = [
    "ANALYSIS_FASTP_TASK",
    "ANALYSIS_SCANPY_TASK",
    "BLAST_RUN_TASK",
    "BUILD_STATIC_PAGES_TASK",
    "EXPORT_VARIANTS_TASK",
    "IMPORT_EXPRESSION_TASK",
    "IMPORT_HOMOLOG_TASK",
    "PAYLOAD_VERSION",
    "QUEUE_ANALYSES",
    "QUEUE_BLAST",
    "QUEUE_CLEANUP",
    "QUEUE_DEFAULT",
    "QUEUE_EXPORT",
    "QUEUE_INGEST",
    "QUEUE_STATS",
    "TASK_QUEUE_MAP",
]
