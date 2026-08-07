"""Ensure the shared ``soymutdb_jobs`` package is importable.

The API image does not install ``soymutdb-jobs`` yet; when the package is not
importable we fall back to the monorepo source directory.  Importing this
module performs the bootstrap (module-level side effect).
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["ensure_jobs_package"]

_JOBS_SRC = Path(__file__).resolve().parents[4] / "packages" / "jobs-py" / "src"


def ensure_jobs_package() -> None:
    """Add ``packages/jobs-py/src`` to ``sys.path`` when needed."""
    try:
        import soymutdb_jobs  # noqa: F401
        return
    except ImportError:
        pass
    if _JOBS_SRC.is_dir() and str(_JOBS_SRC) not in sys.path:
        sys.path.insert(0, str(_JOBS_SRC))


ensure_jobs_package()
