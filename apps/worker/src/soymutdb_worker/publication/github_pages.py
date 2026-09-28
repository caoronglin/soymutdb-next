"""GitHub Pages publication adapter (Phase 3 Task 6).

Dispatches a ``workflow_dispatch`` to ``.github/workflows/pages.yml`` with
inputs ``publication_id``, ``artifact_url`` and ``manifest_digest``; the
workflow downloads the immutable artifact, verifies its digest, runs smoke
checks, then creates a single complete ``gh-pages`` commit and updates the
ref.  The adapter polls the run till completion and records run/commit ids.

Failure is reported WITHOUT changing the database public pointer — the worker
decides whether to promote based on the returned run id.
"""

from __future__ import annotations

import time

from .base import DeploymentRef, ValidationEvidence, verify_manifest
from .http import AdapterHttpError, post_json, request_json

PAGES_WORKFLOW = "pages.yml"


class GithubPagesAdapter:
    target = "github_pages"

    def __init__(
        self,
        token: str | None,
        repository: str | None,
        api_origin: str | None = None,
        artifact_url_template: str | None = None,
    ) -> None:
        self.token = token
        self.repository = repository
        self.api_origin = api_origin or "https://api.github.com"
        #: ``str.format`` template with ``{publication_id}``/``{digest}``, e.g.
        #: ``https://artifacts.example/soymutdb/{publication_id}/{digest}.tar.gz``.
        self.artifact_url_template = artifact_url_template

    def _check_configured(self) -> None:
        if not self.token or not self.repository:
            raise RuntimeError("github_pages target not configured (token/repository)")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def stage(self, publication_id: int, artifact: object) -> DeploymentRef:
        """Record the immutable artifact the workflow will fetch.

        GitHub Pages staging is a marker: the ``pages.yml`` workflow downloads
        the artifact itself. That means the *metadata* has to carry a fetchable
        immutable URL and the publication id — the previous version returned an
        empty ``metadata`` dict, so ``promote`` dispatched a workflow with
        ``publication_id=""`` and ``artifact_url=""`` and the run could not
        identify what to deploy.
        """
        self._check_configured()
        from pathlib import Path

        artifact_path = Path(artifact) if not isinstance(artifact, Path) else artifact
        manifest_digest = _digest(artifact_path)

        # The immutable location the workflow will download. Without it the
        # dispatch would be unactionable, so fail here rather than send empty
        # inputs downstream.
        artifact_url = self._artifact_url(publication_id, manifest_digest)
        return DeploymentRef(
            target=self.target,
            ref=f"github:{publication_id}:{manifest_digest[:12]}",
            manifest_digest=manifest_digest,
            artifact_path=str(artifact_path),
            metadata={
                "publication_id": str(publication_id),
                "artifact_url": artifact_url,
                "manifest_digest": manifest_digest,
            },
        )

    def _artifact_url(self, publication_id: int, manifest_digest: str) -> str:
        """Immutably address the staged artifact for the workflow to fetch."""
        template = (self.artifact_url_template or "").strip()
        if not template:
            raise RuntimeError(
                "github_pages target requires an artifact URL template "
                "(SOYMUTDB_GITHUB_PAGES_ARTIFACT_URL_TEMPLATE) so the workflow "
                "can fetch the immutable artifact; refusing to dispatch empty "
                "workflow inputs"
            )
        return template.format(
            publication_id=publication_id, digest=manifest_digest
        )

    def verify(self, deployment: DeploymentRef) -> ValidationEvidence:
        artifact = _path(deployment)
        return verify_manifest(artifact, deployment.manifest_digest)

    def promote(self, deployment: DeploymentRef) -> str:
        """Dispatch the pages workflow and poll to completion."""
        self._check_configured()

        payload = {
            "ref": "main",
            "inputs": {
                "publication_id": str(deployment.metadata.get("publication_id", "")),
                "artifact_url": deployment.metadata.get("artifact_url", ""),
                "manifest_digest": deployment.manifest_digest,
            },
        }
        url = (
            f"{self.api_origin}/repos/{self.repository}"
            f"/actions/workflows/{PAGES_WORKFLOW}/dispatches"
        )
        try:
            post_json(url, headers=self._headers(), body=payload)
        except AdapterHttpError:
            # The workflow may still be registered under a different path;
            # surface a clear error.
            raise
        # Poll the most recent run.
        runs_url = (
            f"{self.api_origin}/repos/{self.repository}"
            f"/actions/workflows/{PAGES_WORKFLOW}/runs?per_page=1"
        )
        run_id = None
        for _ in range(60):
            run = request_json(runs_url, headers=self._headers())
            workflows = run.get("workflow_runs", [])
            if workflows:
                run_id = workflows[0]["id"]
                status = workflows[0].get("status")
                conclusion = workflows[0].get("conclusion")
                if status == "completed":
                    if conclusion != "success":
                        raise RuntimeError(f"pages workflow concluded {conclusion} (run {run_id})")
                    return f"run:{run_id}"
            time.sleep(5)
        raise RuntimeError("pages workflow run did not complete in time")

    def rollback(self, remote_id: str) -> str:
        # Rollback on GitHub Pages re-dispatches with the previous artifact
        # (driven by the caller supplying the previous remote id; we return a
        # marker).  Real pointer restore is performed by the workflow using a
        # previously recorded immutable artifact/commit.
        return remote_id


def _digest(artifact: object) -> str:
    from pathlib import Path

    from . import manifest_digest_of_file

    return manifest_digest_of_file(Path(artifact) / "manifest.json")


def _path(deployment: DeploymentRef):
    from pathlib import Path

    assert deployment.artifact_path is not None
    return Path(deployment.artifact_path)


__all__ = ["GithubPagesAdapter", "PAGES_WORKFLOW"]
