"""SoyMutDB Celery worker package.

The shared job contract (``packages/jobs-py``) is part of this repository.
Its source directory is put on ``sys.path`` **before** any submodule is
imported, so a stale installed copy of ``soymutdb_jobs`` can never shadow
the source the rest of the checkout runs — a broken shared contract would
otherwise keep the whole worker (every queue, not only the broken one)
from booting.
"""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "2.0.0"

_JOBS_PKG_SRC = Path(__file__).resolve().parents[4] / "packages" / "jobs-py" / "src"
if _JOBS_PKG_SRC.is_dir():
    _src_str = str(_JOBS_PKG_SRC)
    if _src_str not in sys.path:
        sys.path.insert(0, _src_str)
