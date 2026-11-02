"""SoyMutDB API application package.

The shared job contract (``packages/jobs-py``) is part of this repository.
Its source directory is put on ``sys.path`` **before** any submodule is
imported, so a stale installed copy of ``soymutdb_jobs`` can never shadow
the source the rest of the checkout runs.  In a container image the
checkout is copied before the dependencies are installed, so the installed
package and this source are the same files.
"""

from __future__ import annotations

import sys
from pathlib import Path

_JOBS_PKG_SRC = Path(__file__).resolve().parents[3] / "packages" / "jobs-py" / "src"
if _JOBS_PKG_SRC.is_dir():
    _src_str = str(_JOBS_PKG_SRC)
    if _src_str not in sys.path:
        sys.path.insert(0, _src_str)
