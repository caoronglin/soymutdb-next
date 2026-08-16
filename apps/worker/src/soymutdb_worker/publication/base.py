"""Publication adapter base types, protocol, and shared helpers (Phase 3).

Each adapter implements the same three-step lifecycle:

1. ``stage``   — materialise the immutable artifact at the target staging
   area (copy / upload), returning a :class:`DeploymentRef` handle.
2. ``verify``  — validate the staged deployment (manifest digest, files).
3. ``promote`` — atomically make the staged deployment the live pointer,
   returning a remote deployment identifier.
4. ``rollback``— restore a previously verified remote deployment.

Adapters MUST be free of API ORM imports; credentials come from
worker-side ``SOYMUTDB_*`` env config via ``soymutdb_worker.config``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class DeploymentRef:
    """Handle to a staged deployment on a target."""

    target: str
    #: Opaque target-specific location/identifier for the staged artifact.
    ref: str
    #: Expected manifest digest (SHA-256 hex) of ``manifest.json``.
    manifest_digest: str
    #: Local path to the immutable artifact directory (if staged locally).
    artifact_path: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationEvidence:
    """Evidence collected by ``verify``."""

    ok: bool
    digest_verified: bool
    error: str | None = None
    detail: dict = field(default_factory=dict)


class PublicationAdapter(Protocol):
    """Protocol implemented by local / github_pages / cloudflare_pages."""

    target: str

    def stage(self, publication_id: int, artifact: Path) -> DeploymentRef:
        """Materialise *artifact* at the target staging area."""
        ...

    def verify(self, deployment: DeploymentRef) -> ValidationEvidence:
        """Validate the staged deployment's manifest digest and files."""
        ...

    def promote(self, deployment: DeploymentRef) -> str:
        """Atomically promote the staged deployment; return remote id."""
        ...

    def rollback(self, remote_id: str) -> str:
        """Restore a previously verified deployment; return new remote id."""
        ...


def manifest_digest_of_file(manifest_path: Path) -> str:
    """Return the SHA-256 of a manifest.json's immutable content.

    The digest is computed over manifest metadata + ``files``, EXCLUDING the
    wall-clock ``generated_at`` field, so a manifest produced from the same
    source always hashes identically (deterministic manifests — see
    ``static_publish_impl.build_manifest``).
    """
    raw = manifest_path.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8"))
        parsed.pop("generated_at", None)
        canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    except (ValueError, UnicodeDecodeError):
        canonical = raw.decode("utf-8", "replace")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_manifest(artifact: Path, expected_digest: str) -> ValidationEvidence:
    """Verify the artifact's manifest digest and per-file content hashes."""
    manifest_path = artifact / MANIFEST_NAME
    if not manifest_path.is_file():
        return ValidationEvidence(
            ok=False, digest_verified=False, error="missing manifest.json"
        )
    actual = manifest_digest_of_file(manifest_path)
    digest_ok = actual == expected_digest
    detail: dict = {"digest": actual}
    try:
        parsed = json.loads(manifest_path.read_text("utf-8"))
        files = dict(parsed.get("files", {}))
        mismatched: list[str] = []
        missing: list[str] = []
        for rel, expected_hash in files.items():
            p = artifact / rel
            if not p.is_file():
                missing.append(rel)
                continue
            if _sha256_file(p) != expected_hash:
                mismatched.append(rel)
        detail["missing_files"] = missing
        detail["hash_mismatches"] = mismatched
        if missing or mismatched:
            return ValidationEvidence(
                ok=False,
                digest_verified=digest_ok,
                error=f"integrity failure: {len(missing)} missing, {len(mismatched)} mismatched",
                detail=detail,
            )
    except (ValueError, OSError):
        detail["parse_error"] = True
        return ValidationEvidence(ok=False, digest_verified=digest_ok, detail=detail)
    return ValidationEvidence(ok=digest_ok, digest_verified=digest_ok, detail=detail)


__all__ = [
    "DeploymentRef",
    "MANIFEST_NAME",
    "PublicationAdapter",
    "ValidationEvidence",
    "manifest_digest_of_file",
    "verify_manifest",
]
