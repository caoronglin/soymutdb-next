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
#: Asynchronous, worker-only construction of an immutable NCBI BLAST index
#: (staging -> makeblastdb -> validation -> atomic publication). HTTP handlers
#: enqueue this through the transactional outbox and never invoke makeblastdb
#: themselves; it runs on the `blast` queue, never inside a request.
BLAST_BUILD_INDEX_TASK: Final[str] = "soymutdb_worker.tasks.blast_index.build_index"
#: The lifecycle-owning build task (staging -> makeblastdb -> validation ->
#: catalog publication). `BLAST_BUILD_INDEX_TASK` above is the legacy single-shot
#: builder that predates the catalog state machine; new work is queued through
#: this one, and both are registered so redelivered legacy messages still run.
BLAST_INDEX_BUILD_TASK: Final[str] = (
    "soymutdb_worker.tasks.blast_index_tasks.build_blast_index"
)
BUILD_STATIC_PAGES_TASK: Final[str] = "soymutdb_worker.tasks.static_pages.build_static_pages"
EXPORT_VARIANTS_TASK: Final[str] = "soymutdb_worker.tasks.export.export_variants"
IMPORT_ADAPTER_TASK: Final[str] = "soymutdb_worker.tasks.ingest.run_import_adapter"
IMPORT_EXPRESSION_TASK: Final[str] = "soymutdb_worker.tasks.expression.import_expression_csv"
IMPORT_HOMOLOG_TASK: Final[str] = "soymutdb_worker.tasks.homolog.import_homolog_csv"
IMPORT_FASTA_TASK: Final[str] = "soymutdb_worker.tasks.ingest.import_fasta"
IMPORT_GFF3_TASK: Final[str] = "soymutdb_worker.tasks.ingest.import_gff3"
IMPORT_VCF_TASK: Final[str] = "soymutdb_worker.tasks.ingest.import_vcf"
IMPORT_BLAST_DB_TASK: Final[str] = "soymutdb_worker.tasks.ingest.import_blast_db"
IMPORT_SEED_TASK: Final[str] = "soymutdb_worker.tasks.ingest.import_seed"
ANALYSIS_FASTP_TASK: Final[str] = "soymutdb_worker.tasks.analyses.run_fastp"
ANALYSIS_SCANPY_TASK: Final[str] = "soymutdb_worker.tasks.analyses.run_scanpy"
GWAS_RUN_TASK: Final[str] = "soymutdb_worker.tasks.gwas.run_gwas"
#: Email dispatch for contact-style modules (seed requests).  Runs on the
#: ``default`` queue (no task_routes entry needed).
SEED_REQUEST_EMAIL_TASK: Final[str] = (
    "soymutdb_worker.tasks.email.send_seed_request_email"
)
#: Cache/notification refresh after the active release pointer changes.
STATIC_PUBLISH_TASK: Final[str] = "soymutdb_worker.tasks.static_publish.build_static_release"
PAGE_BUILDER_PUBLISH_TASK: Final[str] = (
    "soymutdb_worker.tasks.page_builder_publish.publish_definition"
)
RELEASE_POINTER_CHANGED_TASK: Final[str] = (
    "soymutdb_worker.tasks.release.refresh_release_pointer"
)

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
    BLAST_INDEX_BUILD_TASK: QUEUE_BLAST,
    BLAST_BUILD_INDEX_TASK: QUEUE_BLAST,
    BUILD_STATIC_PAGES_TASK: QUEUE_STATS,
    STATIC_PUBLISH_TASK: QUEUE_STATS,
    PAGE_BUILDER_PUBLISH_TASK: QUEUE_DEFAULT,
    EXPORT_VARIANTS_TASK: QUEUE_EXPORT,
    IMPORT_ADAPTER_TASK: QUEUE_INGEST,
    IMPORT_EXPRESSION_TASK: QUEUE_INGEST,
    IMPORT_HOMOLOG_TASK: QUEUE_INGEST,
    ANALYSIS_FASTP_TASK: QUEUE_ANALYSES,
    ANALYSIS_SCANPY_TASK: QUEUE_ANALYSES,
    GWAS_RUN_TASK: QUEUE_ANALYSES,
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
    "BLAST_INDEX_BUILD_TASK",
    "BLAST_BUILD_INDEX_TASK",
    "GWAS_RUN_TASK",
    "BUILD_STATIC_PAGES_TASK",
    "EXPORT_VARIANTS_TASK",
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
    "SEED_REQUEST_EMAIL_TASK",
    "RELEASE_POINTER_CHANGED_TASK",
    "STATIC_PUBLISH_TASK",
    "QUEUE_BLAST",
    "QUEUE_CLEANUP",
    "QUEUE_DEFAULT",
    "QUEUE_EXPORT",
    "QUEUE_INGEST",
    "QUEUE_STATS",
    "TASK_QUEUE_MAP",
]
