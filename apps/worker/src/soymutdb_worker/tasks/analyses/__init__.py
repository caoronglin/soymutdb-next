"""Online-analysis task modules (fastp QC, scanpy scRNA-seq, ...).

The analyses queue contract (task names, queue routing in
:mod:`soymutdb_worker.main`, ``QUEUE_ANALYSES`` in ``soymutdb_jobs.contract``)
is owned by the W1-A track; this package only implements the worker-side
execution.

Imported eagerly so ``include=["soymutdb_worker.tasks.analyses", ...]`` in
``main.py`` (added by W1-A) registers the tasks at worker startup.
"""

from . import fastp, scanpy

__all__ = ["fastp", "scanpy"]
