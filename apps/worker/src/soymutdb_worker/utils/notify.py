"""Desktop notification via plyer — optional worker channel (D2).

Gated behind ``SOYMUTDB_DESKTOP_NOTIFY=true`` (any of
``1/true/yes``): when enabled the worker tries to import ``plyer`` and
show an OS-native notification on the host (useful for desktop
deployments of the worker).  plyer is an optional dependency
(``pip install soymutdb-worker[notify]``) — when it is missing, or when
the flag is off, the call is a silent no-op (warn on import failure).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: Env flag enabling the plyer desktop channel.
_ENV_FLAG = "SOYMUTDB_DESKTOP_NOTIFY"


def _enabled() -> bool:
    value = os.environ.get(_ENV_FLAG, "false")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def desktop_notify(
    title: str,
    message: str,
    *,
    app_name: str = "SoyMutDB",
    timeout: int = 10,
) -> bool:
    """Show an OS-native desktop notification via plyer.

    Returns ``True`` when a notification was actually shown.  Disabled via
    ``SOYMUTDB_DESKTOP_NOTIFY``, missing plyer, or any platform error are
    handled gracefully (warn + ``False``) — desktop notifications must
    never break job execution.
    """
    if not _enabled():
        return False
    try:
        from plyer import notification
    except Exception as exc:  # ImportError and friends (no qt/gtk deps)
        logger.warning(
            "desktop_notify: plyer unavailable (%s); skipping OS notification",
            exc,
        )
        return False
    try:
        notification.notify(
            title=title,
            message=message,
            app_name=app_name,
            timeout=timeout,
        )
        return True
    except Exception as exc:  # Platform backends can fail at notify time
        logger.warning("desktop_notify: plyer notify failed (%s)", exc)
        return False
