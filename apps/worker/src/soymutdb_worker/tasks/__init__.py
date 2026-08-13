"""Celery task modules.

All tasks are auto-discovered by :mod:`soymutdb_worker.main`.
"""

__all__ = [
    # Task modules are imported explicitly by Celery.  Keep this package
    # lightweight so importing one task does not require every optional
    # worker runtime dependency.
]
