"""Publication target configuration (Phase 3).

Owns the mapping from a :class:`~app.models.publication.PublicationTarget`
to its runtime credentials.  Credentials are read from environment / secret
configuration at request time and are **never** persisted to the database or
returned by API responses — only the target identifier is stored.

Redaction rules:
  - ``redact_targets()`` returns one entry per *configured* target with only
    safe, non-secret fields (identifier, description, configured flag).
  - Anything that looks like a token/secret/password is never included.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.config import get_settings
from ..models.publication import PublicationTarget


@dataclass(frozen=True)
class TargetConfig:
    identifier: str
    description: str
    is_configured: bool
    #: The resolved credential bundle (never serialised by API responses).
    credentials: dict[str, str]


def _github_pages_config() -> TargetConfig:
    settings = get_settings()
    token = settings.github_pages_token
    repo = settings.github_pages_repo or settings.github_repository
    return TargetConfig(
        identifier=PublicationTarget.GITHUB_PAGES.value,
        description="GitHub Pages (gh-pages branch) publication target.",
        is_configured=bool(token and repo),
        credentials={
            "token": token,
            "repository": repo,
            "api_origin": settings.github_api_origin,
        },
    )


def _cloudflare_pages_config() -> TargetConfig:
    settings = get_settings()
    token = settings.cloudflare_pages_api_token
    project = settings.cloudflare_pages_project
    return TargetConfig(
        identifier=PublicationTarget.CLOUDFLARE_PAGES.value,
        description="Cloudflare Pages upload + promote publication target.",
        is_configured=bool(token and project),
        credentials={
            "api_token": token,
            "account_id": settings.cloudflare_pages_account_id,
            "project_name": project,
        },
    )


def _local_config() -> TargetConfig:
    settings = get_settings()
    root = settings.publication_local_root
    return TargetConfig(
        identifier=PublicationTarget.LOCAL.value,
        description="Local static publication target (symlink + atomic replace).",
        is_configured=bool(root),
        credentials={"root": root},
    )


_CONFIG_FACTORIES = {
    PublicationTarget.LOCAL: _local_config,
    PublicationTarget.GITHUB_PAGES: _github_pages_config,
    PublicationTarget.CLOUDFLARE_PAGES: _cloudflare_pages_config,
}


def get_target_config(target: PublicationTarget) -> TargetConfig:
    """Resolve the runtime configuration for *target*."""
    factory = _CONFIG_FACTORIES[target]
    return factory()


def list_target_configs() -> list[TargetConfig]:
    """Return every target's configuration (resolved fresh from settings)."""
    return [factory() for factory in _CONFIG_FACTORIES.values()]


def redacted_targets() -> list[dict[str, object]]:
    """Return API-safe target descriptions (no credentials)."""
    return [
        {
            "target": cfg.identifier,
            "description": cfg.description,
            "is_configured": cfg.is_configured,
        }
        for cfg in list_target_configs()
    ]


__all__ = [
    "TargetConfig",
    "get_target_config",
    "list_target_configs",
    "redacted_targets",
]
