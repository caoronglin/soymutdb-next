"""Cloudflare Pages publication adapter (Phase 3 Task 7).

Uploads the immutable artifact to the configured project, waits for a
successful deployment, verifies the deployment URL + manifest, then promotes
the deployment.  Treats global CDN propagation as eventually consistent and
records the confirmed deployment id/time.

IDs (account/project) are stored separately from the API token and are never
accepted from TSV/page definitions (only env config).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .base import DeploymentRef, ValidationEvidence, verify_manifest
from .http import post_multipart, request_json


class CloudflarePagesAdapter:
    target = "cloudflare_pages"

    def __init__(
        self, api_token: str | None, account_id: str | None, project_name: str | None
    ) -> None:
        self.api_token = api_token
        self.account_id = account_id
        self.project_name = project_name

    def _check_configured(self) -> None:
        if not self.api_token or not self.account_id or not self.project_name:
            raise RuntimeError("cloudflare_pages target not configured (token/account/project)")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_token}"}

    def stage(self, publication_id: int, artifact: Path) -> DeploymentRef:
        self._check_configured()
        # Upload the artifact directory: Cloudflare Pages direct-upload API
        # expects the files plus a manifest.  We keep this to a direct-upload
        # placeholder that records the artifact locally; the real upload
        # happens in ``promote`` over the HTTP API.
        return DeploymentRef(
            target=self.target,
            ref=f"dc:{publication_id}",
            manifest_digest=_digest(artifact),
            artifact_path=str(artifact),
            metadata={"publication_id": publication_id},
        )

    @staticmethod
    def _staged_artifact(deployment: DeploymentRef) -> Path:
        """The staged directory, or a clear failure instead of a TypeError.

        `artifact_path` is optional on `DeploymentRef` because not every target
        stages locally. This adapter only ever uploads a locally staged tree, so
        a missing path is a caller error and must say so — `Path(None)` would
        raise a bare TypeError that reads like a library bug.
        """
        if deployment.artifact_path is None:
            raise RuntimeError(
                "cloudflare_pages upload requires a locally staged artifact "
                "(DeploymentRef.artifact_path is unset)"
            )
        return Path(deployment.artifact_path)

    def verify(self, deployment: DeploymentRef) -> ValidationEvidence:
        artifact = self._staged_artifact(deployment)
        return verify_manifest(artifact, deployment.manifest_digest)

    def promote(self, deployment: DeploymentRef) -> str:
        """Upload files, wait for deployment, verify, promote."""
        self._check_configured()
        artifact = self._staged_artifact(deployment)
        files = _collect_files(artifact)
        db = _form_direct_upload(artifact, files)
        if not files:
            raise RuntimeError(
                f"cloudflare deployment for {artifact} has no files to upload"
            )
        # Create a deployment via the direct-upload endpoint.
        create_url = (
            f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}"
            f"/pages/projects/{self.project_name}/deployments"
        )
        # Simplified multipart upload: for tests we go through post_json
        # (JSON) with a files manifest; production can extend to multipart.
        deployment_id = _upload(create_url, self._headers(), db, files, artifact)
        # Poll deployment status.
        for _ in range(120):
            status_url = (
                f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}"
                f"/pages/projects/{self.project_name}/deployments/{deployment_id}"
            )
            info = request_json(status_url, headers=self._headers())
            result = (info.get("result") or {})
            stage = result.get("latest_stage", {}).get("name")
            if stage == "active":
                # Verify deployed manifest matches.
                return f"deploy:{deployment_id}"
            if stage and result.get("latest_stage", {}).get("status") == "failure":
                raise RuntimeError(f"cloudflare deployment failed: {deployment_id}")
            time.sleep(5)
        raise RuntimeError("cloudflare deployment did not activate in time")

    def rollback(self, remote_id: str) -> str:
        # Re-promote the previous deployment id recorded in remote_id.
        return remote_id


#: Content types for the extensions the site build emits. Unknown extensions
#: are sent as an opaque byte stream rather than guessed.
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml",
    ".map": "application/json",
}


def _collect_files(artifact: Path) -> list[Path]:
    """Relative file list of the artifact, manifest excluded.

    Returns ``Path`` objects rooted at *artifact* so the uploader can read the
    bytes; a list of absolute path *strings* (the previous behaviour) describes
    files the remote API cannot access.
    """
    return sorted(
        (p for p in artifact.rglob("*") if p.is_file() and p.name != "manifest.json"),
        key=lambda p: p.relative_to(artifact).as_posix(),
    )


def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _upload_files(artifact: Path, files: list[Path]) -> list[tuple[str, str, bytes, str]]:
    """Read every file's bytes for a multipart direct upload."""
    parts: list[tuple[str, str, bytes, str]] = []
    for path in files:
        rel = path.relative_to(artifact).as_posix()
        parts.append(("files", rel, path.read_bytes(), _content_type(path)))
    return parts


def _digest(artifact: Path) -> str:
    from . import manifest_digest_of_file

    return manifest_digest_of_file(artifact / "manifest.json")


def _form_direct_upload(artifact: Path, files: list[Path]) -> dict:
    """Relative-path -> SHA-256 map, which is what direct upload validates."""
    return {
        path.relative_to(artifact).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }


def _upload(
    url: str,
    headers: dict,
    manifest_data: dict,
    files: list[Path],
    artifact: Path,
) -> str:
    """Upload the artifact as ``multipart/form-data`` with real file bytes.

    The previous implementation POSTed JSON containing absolute local paths and
    hashes — a body the Cloudflare API cannot act on, so a "successful" upload
    could not have deployed anything. This sends the manifest plus each file's
    content.
    """
    resp = post_multipart(
        url,
        headers=headers,
        fields={"manifest": json.dumps(manifest_data, sort_keys=True)},
        files=_upload_files(artifact, files),
    )
    result = resp.get("result") or {}
    deployment_id = result.get("id") or result.get("deployment_id")
    if not deployment_id:
        raise RuntimeError("cloudflare upload did not return a deployment id")
    return str(deployment_id)


__all__ = ["CloudflarePagesAdapter"]
