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
    "BLAST_INDEX_BUILD_TASK",
    "BLAST_BUILD_INDEX_TASK",
    "BUILD_STATIC_PAGES_TASK",
    "EXPORT_VARIANTS_TASK",
    "GWAS_RUN_TASK",
    "IMPORT_ADAPTER_TASK",
    "IMPORT_EXPRESSION_TASK",
    "IMPORT_HOMOLOG_TASK",
    "IMPORT_FASTA_TASK",
    "IMPORT_GFF3_TASK",
    "IMPORT_VCF_TASK",
    "IMPORT_BLAST_DB_TASK",
    "IMPORT_SEED_TASK",
    "PAGE_BUILDER_PUBLISH_TASK",
    "PAYLOAD_VERSION",
    "QUEUE_ANALYSES",
    "QUEUE_BLAST",
    "QUEUE_CLEANUP",
    "QUEUE_DEFAULT",
    "QUEUE_EXPORT",
    "QUEUE_INGEST",
    "QUEUE_STATS",
    "SEED_REQUEST_EMAIL_TASK",
    "RELEASE_POINTER_CHANGED_TASK",
    "STATIC_PUBLISH_TASK",
    "TASK_QUEUE_MAP",
]


def _ensure_jobs_package() -> None:
    """Make ``soymutdb_jobs`` importable from the monorepo checkout.

    The monorepo source is **preferred over an installed copy**: the shared
    package is part of this repository, so a stale installation (for
    example one left in a developer environment before the package gained
    a module) must not shadow the source that the rest of the checkout
    actually runs.  In a container image the checkout is copied before the
    dependencies are installed, so both paths point at the same files.
    """
    src = Path(__file__).resolve().parents[4] / "packages" / "jobs-py" / "src"
    if src.is_dir():
        src_str = str(src)
        if src_str not in sys.path:
            sys.path.insert(0, src_str)


_ensure_jobs_package()

from soymutdb_jobs.contract import (  # noqa: E402
    ANALYSIS_FASTP_TASK,
    ANALYSIS_SCANPY_TASK,
    BLAST_BUILD_INDEX_TASK,
    BLAST_INDEX_BUILD_TASK,
    BLAST_RUN_TASK,
    BUILD_STATIC_PAGES_TASK,
    EXPORT_VARIANTS_TASK,
    GWAS_RUN_TASK,
    IMPORT_ADAPTER_TASK,
    IMPORT_BLAST_DB_TASK,
    IMPORT_EXPRESSION_TASK,
    IMPORT_FASTA_TASK,
    IMPORT_GFF3_TASK,
    IMPORT_HOMOLOG_TASK,
    IMPORT_SEED_TASK,
    IMPORT_VCF_TASK,
    PAGE_BUILDER_PUBLISH_TASK,
    PAYLOAD_VERSION,
    QUEUE_ANALYSES,
    QUEUE_BLAST,
    QUEUE_CLEANUP,
    QUEUE_DEFAULT,
    QUEUE_EXPORT,
    QUEUE_INGEST,
    QUEUE_STATS,
    RELEASE_POINTER_CHANGED_TASK,
    SEED_REQUEST_EMAIL_TASK,
    STATIC_PUBLISH_TASK,
    TASK_QUEUE_MAP,
)
