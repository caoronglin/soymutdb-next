"""Best-effort invalidation for the mutable content snapshot cache."""

from __future__ import annotations

from .cache import delete_prefix


async def invalidate_mutable_content_snapshot() -> None:
    """Evict mutable snapshot aliases after a successful content commit.

    Redis is only an accelerator. ``delete_prefix`` swallows cache failures so
    an already committed content mutation remains successful during an outage.
    The prefix covers both the active alias and release/page-version variants.
    """
    await delete_prefix("content:snapshot")


__all__ = ["invalidate_mutable_content_snapshot"]
