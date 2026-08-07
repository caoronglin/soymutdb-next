"""Celery task modules.

All tasks are auto-discovered by :mod:`soymutdb_worker.main`.
"""

from . import blast, cleanup, export, expression, homolog, ingest, static_pages, stats

__all__ = [
    "blast",
    "cleanup",
    "export",
    "expression",
    "homolog",
    "ingest",
    "static_pages",
    "stats",
]
