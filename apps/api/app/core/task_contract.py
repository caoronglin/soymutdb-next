"""Names shared by API dispatchers and Celery task registrations."""

from __future__ import annotations

BLAST_RUN_TASK = "soymutdb_worker.tasks.blast.run_blast"
BUILD_STATIC_PAGES_TASK = "soymutdb_worker.tasks.static_pages.build_static_pages"
EXPORT_VARIANTS_TASK = "soymutdb_worker.tasks.export.export_variants"
IMPORT_EXPRESSION_TASK = "soymutdb_worker.tasks.expression.import_expression_csv"
IMPORT_HOMOLOG_TASK = "soymutdb_worker.tasks.homolog.import_homolog_csv"

__all__ = [
    "BLAST_RUN_TASK",
    "BUILD_STATIC_PAGES_TASK",
    "EXPORT_VARIANTS_TASK",
    "IMPORT_EXPRESSION_TASK",
    "IMPORT_HOMOLOG_TASK",
]
