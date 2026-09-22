"""Backward-compatible re-export of the shared import fingerprint (Phase A).

The implementation lives in the framework-neutral ``soymutdb_import_protocol``
package so the Celery worker shares the exact identity rule without importing
this API (H4). Keep this import path stable for existing callers/tests.
"""

from __future__ import annotations

from soymutdb_import_protocol import compute_import_fingerprint
from soymutdb_import_protocol.fingerprint import FINGERPRINT_INPUT_FIELDS

__all__ = ["compute_import_fingerprint", "FINGERPRINT_INPUT_FIELDS"]
