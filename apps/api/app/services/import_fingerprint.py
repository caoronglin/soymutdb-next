"""Stable semantic fingerprint for an import (ADR-0005 / P2-2).

The fingerprint is the exactly-once dedup key for a logical import. It MUST
cover every input that can change the output facts, and MUST exclude
non-semantic fields (filename, upload time) so that re-uploading the same
bytes under a different name is recognised as the same logical import.
"""

from __future__ import annotations

import hashlib


def compute_import_fingerprint(
    *,
    source_sha256: str,
    release_id: int,
    assembly_id: int,
    importer_version: str,
    schema_version: str,
    normalization_version: str,
    config_hash: str,
) -> str:
    """Return a 64-char hex fingerprint over the semantic import inputs.

    Any change to a semantic input changes the fingerprint; changes to
    non-semantic inputs (not passed here) do not.
    """
    payload = "|".join(
        [
            source_sha256,
            str(int(release_id)),
            str(int(assembly_id)),
            importer_version,
            schema_version,
            normalization_version,
            config_hash,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
