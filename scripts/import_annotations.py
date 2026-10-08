#!/usr/bin/env python3
"""Repository-root entry point for the canonical API annotation import CLI.

Use the API virtualenv: apps/api/.venv/bin/python scripts/import_annotations.py
The argument contract is identical to apps/api/scripts/import_gene_annotations.py:
a positional TSV path, --sha256, and optional --dry-run. There is no replacement
or unknown-gene skipping mode: snapshots are immutable and draft-only.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"

if __name__ == "__main__":
    sys.path.insert(0, str(API_ROOT))
    runpy.run_path(str(API_ROOT / "scripts" / "import_gene_annotations.py"), run_name="__main__")
