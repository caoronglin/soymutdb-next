"""Artifact identity for variant exports (one owner for API and worker).

The export artifact has two identities that must never drift apart:

* the **file name** shown to the user, and
* the **object key** under which the file is stored.

The worker writes the object and records its key; the API later signs a
short-lived download URL for that same key.  If the two sides derived the key
independently, a download would 404 — so the derivation lives here, in the
package both sides already import.

The key is bucket-relative: the bucket itself is deployment configuration
(``S3_EXPORT_BUCKET`` on the worker, ``s3_export_bucket`` in the API).
"""

from __future__ import annotations

__all__ = [
    "EXPORT_ARTIFACT_PREFIX",
    "EXPORT_FORMATS",
    "build_export_artifact_key",
    "build_export_filename",
]

#: Key prefix of every export artifact inside the export bucket.
EXPORT_ARTIFACT_PREFIX = "exports"

#: Formats the export pipeline can produce (worker-side contract).
EXPORT_FORMATS = frozenset({"vcf", "tsv", "csv", "json", "bed"})


def build_export_filename(export_id: str, export_format: str, compress: bool) -> str:
    """Return the artifact file name for *export_id*."""
    if export_format not in EXPORT_FORMATS:
        raise ValueError(
            f"Unsupported export format: {export_format!r}. "
            f"Allowed: {sorted(EXPORT_FORMATS)}"
        )
    filename = f"soymutdb_export_{export_id}.{export_format}"
    return f"{filename}.gz" if compress else filename


def build_export_artifact_key(export_id: str, filename: str) -> str:
    """Return the bucket-relative object key for an export artifact."""
    return f"{EXPORT_ARTIFACT_PREFIX}/{export_id}/{filename}"
