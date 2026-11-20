"""Single-use, short-lived tickets for the job-status SSE stream (D5).

The browser ``EventSource`` API cannot set an ``Authorization`` header, so the
stream URL has to carry a credential of its own.  That credential must not be
the access token: the edge proxy logs ``$request`` -- query string included --
so a token in the URL becomes a live session credential in an access log
(``infra/nginx/nginx.conf``).  A ticket is instead:

* opaque -- ``secrets.token_urlsafe``, never a JWT, so it carries no claims,
  no subject and no signature to diagnose;
* issued only by ``POST /api/v1/jobs/sse-ticket`` to an authenticated caller;
* bound server-side to the requesting user id (Redis, TTL
  :data:`SSE_TICKET_TTL_SECONDS`);
* single-use -- redemption is one atomic ``GETDEL``, so a replay finds nothing.

The store is the disposable cache tier: when Redis is unavailable the exchange
fails closed with 503 and the portal keeps its polling fallback, rather than
degrading to a reusable or long-lived URL credential.

No ticket, token, or signing diagnostic is included in an error message or a
log line.
"""

from __future__ import annotations

import re
import secrets
from uuid import UUID

from structlog import get_logger

from ..core.database import get_redis
from ..core.exceptions import ServiceUnavailableError

logger = get_logger(__name__)

#: Ticket lifetime in seconds.  The stream opens immediately after the
#: exchange, so a narrow window is enough; the contract ceiling is 60 seconds.
SSE_TICKET_TTL_SECONDS = 30

_TICKET_KEY_PREFIX = "sse:ticket:"

# ``secrets.token_urlsafe(32)`` is 43 URL-safe characters.  Anything else never
# reaches Redis: a caller-supplied string with an unbounded alphabet would
# otherwise become a cache-key injection surface, and a malformed ticket is not
# a store lookup at all.
_TICKET_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def _store(redis=None):
    return redis if redis is not None else get_redis()


async def issue_ticket(user_id: UUID, *, redis=None) -> str:
    """Store a fresh ticket bound to *user_id* and return it."""
    ticket = secrets.token_urlsafe(32)
    try:
        await _store(redis).set(
            f"{_TICKET_KEY_PREFIX}{ticket}",
            str(user_id),
            ex=SSE_TICKET_TTL_SECONDS,
        )
    except Exception as exc:
        # Fail closed: without the binding store there is no single-use
        # guarantee, so no ticket is handed out.
        logger.warning("sse_ticket_store_unavailable", exc_info=True)
        raise ServiceUnavailableError("SSE tickets are temporarily unavailable") from exc
    return ticket


async def redeem_ticket(ticket: str, *, redis=None) -> UUID | None:
    """Consume *ticket* and return the user id it was issued to.

    Returns ``None`` for a malformed, unknown, expired, or already redeemed
    ticket.  The caller cannot distinguish those cases and does not need to: a
    replay is simply absent, because ``GETDEL`` removed the entry the first
    time it was redeemed.
    """
    if not _TICKET_RE.match(ticket or ""):
        return None
    try:
        value = await _store(redis).getdel(f"{_TICKET_KEY_PREFIX}{ticket}")
    except Exception as exc:
        logger.warning("sse_ticket_store_unavailable", exc_info=True)
        raise ServiceUnavailableError("SSE tickets are temporarily unavailable") from exc
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


__all__ = ["SSE_TICKET_TTL_SECONDS", "issue_ticket", "redeem_ticket"]
