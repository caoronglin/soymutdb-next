"""Names shared by API dispatchers and Celery task registrations.

The canonical definitions moved to the shared contract package
(``packages/jobs-py`` → ``soymutdb_jobs.contract``) so the worker no longer
imports API source code.  This module re-exports them to keep existing API
importers (``from app.core.task_contract import BLAST_RUN_TASK``) working.
"""

from __future__ import annotations

import sys
from pathlib import Path

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


def _ensure_jobs_package() -> None:
    """Make ``soymutdb_jobs`` importable from the monorepo checkout.

    The API image does not install ``soymutdb-jobs`` yet; when the package is
    not importable we fall back to the monorepo source directory.
    """
    try:
        import soymutdb_jobs  # noqa: F401
        return
    except ImportError:
        pass
    src = Path(__file__).resolve().parents[4] / "packages" / "jobs-py" / "src"
    if src.is_dir():
        sys.path.insert(0, str(src))


_ensure_jobs_package()

from soymutdb_jobs.contract import (  # noqa: E402
    ANALYSIS_FASTP_TASK,
    ANALYSIS_SCANPY_TASK,
    BLAST_RUN_TASK,
    BUILD_STATIC_PAGES_TASK,
    EXPORT_VARIANTS_TASK,
    IMPORT_EXPRESSION_TASK,
    IMPORT_HOMOLOG_TASK,
    PAYLOAD_VERSION,
    QUEUE_ANALYSES,
    QUEUE_BLAST,
    QUEUE_CLEANUP,
    QUEUE_DEFAULT,
    QUEUE_EXPORT,
    QUEUE_INGEST,
    QUEUE_STATS,
    TASK_QUEUE_MAP,
)
