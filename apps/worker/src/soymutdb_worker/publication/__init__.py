"""Publication adapter registry and shared helpers (Phase 3)."""

from __future__ import annotations

from soymutdb_worker.config import get_setting

from .base import (
    MANIFEST_NAME,
    DeploymentRef,
    PublicationAdapter,
    ValidationEvidence,
    manifest_digest_of_file,
    verify_manifest,
)
from .local import LocalAdapter


def get_adapter(target: str) -> PublicationAdapter:
    """Return the adapter instance for a target identifier."""
    if target == "local":
        return LocalAdapter(get_setting("PUBLICATION_LOCAL_ROOT", None))
    if target == "github_pages":
        from .github_pages import GithubPagesAdapter

        return GithubPagesAdapter(
            token=get_setting("GITHUB_PAGES_TOKEN", None),
            repository=get_setting(
                "GITHUB_PAGES_REPO", get_setting("GITHUB_REPOSITORY", None)
            ),
            api_origin=get_setting("GITHUB_API_ORIGIN", "https://api.github.com"),
        )
    if target == "cloudflare_pages":
        from .cloudflare_pages import CloudflarePagesAdapter

        return CloudflarePagesAdapter(
            api_token=get_setting("CLOUDFLARE_PAGES_API_TOKEN", None),
            account_id=get_setting("CLOUDFLARE_PAGES_ACCOUNT_ID", None),
            project_name=get_setting("CLOUDFLARE_PAGES_PROJECT", None),
        )
    raise ValueError(f"unknown publication target: {target}")


__all__ = [
    "MANIFEST_NAME",
    "DeploymentRef",
    "PublicationAdapter",
    "ValidationEvidence",
    "get_adapter",
    "manifest_digest_of_file",
    "verify_manifest",
]
