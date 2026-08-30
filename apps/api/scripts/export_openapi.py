#!/usr/bin/env python
"""Export the SoyMutDB FastAPI OpenAPI schema to a JSON file.

Usage (from anywhere)::

    PYTHONPATH=/path/to/repo apps/api/.venv/bin/python \
        apps/api/scripts/export_openapi.py --output /tmp/openapi.json

The output file is the source of truth for the generated TypeScript
client (``packages/api-client/src/generated/openapi.d.ts``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make both the repo root (for the `tools` package) and apps/api (for the
# `app` package) importable regardless of the current working directory.
REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = Path(__file__).resolve().parents[1]
for path in (str(API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="openapi.json",
        help="Destination JSON file (default: ./openapi.json)",
    )
    parser.add_argument(
        "--error-codes-output",
        help="Optional destination for the generated error-code catalog JSON.",
    )
    args = parser.parse_args()

    from app.main import app

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    output.write_text(json.dumps(schema, indent=2))
    print(f"openapi exported -> {output}")

    if args.error_codes_output:
        from app.core.exceptions import error_code_catalog

        error_codes_output = Path(args.error_codes_output)
        error_codes_output.parent.mkdir(parents=True, exist_ok=True)
        error_codes_output.write_text(json.dumps(error_code_catalog(), indent=2, sort_keys=True) + "\n")
        print(f"error-code catalog exported -> {error_codes_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
