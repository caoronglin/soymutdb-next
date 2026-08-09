"""Import bridge to the shared jobs contract package (``soymutdb_jobs``).

The worker image ships without ``soymutdb-jobs`` installed yet; this module
makes the package importable from the monorepo checkout and re-exports every
symbol worker code needs, so tasks never import API source code.
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = [
    "BLAST_RUN_TASK",
    "BUILD_STATIC_PAGES_TASK",
    "EXPORT_VARIANTS_TASK",
    "GWAS_RUN_TASK",
    "IMPORT_EXPRESSION_TASK",
    "IMPORT_HOMOLOG_TASK",
    "JobPayload",
    "JobRecordStore",
    "JobStatus",
    "JobStatusUpdate",
    "PAYLOAD_VERSION",
    "QUEUE_BLAST",
    "QUEUE_CLEANUP",
    "QUEUE_DEFAULT",
    "QUEUE_EXPORT",
    "QUEUE_INGEST",
    "QUEUE_STATS",
    "SEED_REQUEST_EMAIL_TASK",
    "TASK_QUEUE_MAP",
    "transition_allowed",
]


def _ensure_jobs_package() -> None:
    """Add ``packages/jobs-py/src`` to ``sys.path`` when not importable."""
    try:
        import soymutdb_jobs  # noqa: F401
        return
    except ImportError:
        pass
    src = Path(__file__).resolve().parents[4] / "packages" / "jobs-py" / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


_ensure_jobs_package()

from soymutdb_jobs.contract import (  # noqa: E402
    BLAST_RUN_TASK,
    BUILD_STATIC_PAGES_TASK,
    EXPORT_VARIANTS_TASK,
    GWAS_RUN_TASK,
    IMPORT_EXPRESSION_TASK,
    IMPORT_HOMOLOG_TASK,
    PAYLOAD_VERSION,
    QUEUE_BLAST,
    QUEUE_CLEANUP,
    QUEUE_DEFAULT,
    QUEUE_EXPORT,
    QUEUE_INGEST,
    QUEUE_STATS,
    SEED_REQUEST_EMAIL_TASK,
    TASK_QUEUE_MAP,
)
from soymutdb_jobs.schemas import JobPayload, JobRecordStore, JobStatusUpdate  # noqa: E402
from soymutdb_jobs.status import JobStatus, transition_allowed  # noqa: E402
