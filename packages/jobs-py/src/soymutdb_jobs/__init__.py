"""SoyMutDB shared job contract package.

Versioned, idempotent job payloads plus the canonical status state machine,
task names, and queue names shared by the API and the Celery worker.
"""

from __future__ import annotations

from .contract import (
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
from .protein_fasta import (
    PROTEIN_ALPHABET,
    ProteinFasta,
    ProteinFastaError,
    ProteinFastaRecord,
    parse_protein_fasta,
)
from .schemas import AnalysisJobPayload, JobPayload, JobRecordStore, JobStatusUpdate
from .status import TRANSITION_MATRIX, JobStatus, transition_allowed

__version__ = "0.1.0"

__all__ = [
    "ANALYSIS_FASTP_TASK",
    "ANALYSIS_SCANPY_TASK",
    "AnalysisJobPayload",
    "BLAST_RUN_TASK",
    "BUILD_STATIC_PAGES_TASK",
    "EXPORT_VARIANTS_TASK",
    "IMPORT_EXPRESSION_TASK",
    "IMPORT_HOMOLOG_TASK",
    "JobPayload",
    "JobRecordStore",
    "JobStatus",
    "JobStatusUpdate",
    "PAYLOAD_VERSION",
    "PROTEIN_ALPHABET",
    "ProteinFasta",
    "ProteinFastaError",
    "ProteinFastaRecord",
    "QUEUE_ANALYSES",
    "QUEUE_BLAST",
    "QUEUE_CLEANUP",
    "QUEUE_DEFAULT",
    "QUEUE_EXPORT",
    "QUEUE_INGEST",
    "QUEUE_STATS",
    "TASK_QUEUE_MAP",
    "TRANSITION_MATRIX",
    "parse_protein_fasta",
    "transition_allowed",
]
