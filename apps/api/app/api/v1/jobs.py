"""Job status push endpoint (SSE) — D5 pilot.

``GET /api/v1/jobs/events`` streams ``job_update`` events for the
authenticated user's jobs (blast / analysis / gwas).  The server polls
PostgreSQL every 2 seconds for jobs updated in the trailing 30-second window
(three tables UNIONed by their update timestamp) and pushes any changes;
when there is nothing to push it emits a ``: ping`` heartbeat comment line so
proxies keep the connection open.

Design notes:
- Polling PostgreSQL (not Redis pub/sub) keeps the pilot dependency-free:
  no channel plumbing, no extra failure modes.  If the endpoint graduates,
  the poll can be replaced by a Redis pub/sub subscriber fed by the worker
  (or outbox dispatcher) with zero wire-format changes — the SSE frame shape
  below is the contract.
- Auth is optional on purpose: anonymous clients receive updates for
  ``user_id IS NULL`` jobs only (public/system jobs).  A stream credential is
  supplied either as an ``Authorization: Bearer`` header (non-browser clients)
  or as ``?ticket=`` (browsers: ``EventSource`` cannot set headers).  The
  ticket is a single-use, 30-second, opaque value obtained from
  ``POST /api/v1/jobs/sse-ticket`` -- see :mod:`app.services.sse_ticket`.  The
  access token itself is never accepted in the query string: nginx logs
  ``$request`` including the query string, so a token there is a live session
  credential written to a log file.
- The stream terminates when the client disconnects (checked every poll
  cycle; the generator is also cancelled by the ASGI server).
- **The stream never holds a pooled database connection.**  FastAPI closes
  the request-scoped session only *after* the response body has been
  produced — up to 30 minutes for this endpoint — so polling through that
  session would pin one of the few pooled connections (``db_pool_size`` +
  ``db_max_overflow``; 5 per API worker in production) for the whole
  stream.  Five anonymous ``GET /jobs/events`` connections would then
  exhaust one worker's pool and every other request would block for
  ``db_pool_timeout``.  Every poll cycle therefore opens its own
  short-lived session and closes it again before the stream sleeps, and the
  request-scoped session is released before the stream starts.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import String, cast, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from ...core.database import get_db, get_session_factory
from ...core.exceptions import AuthenticationError
from ...models.analysis_job import AnalysisJob
from ...models.auth import User
from ...models.blast import BlastJob
from ...models.gwas import GwasJob
from ...schemas.jobs import SseTicketResponse
from ...services.sse_ticket import SSE_TICKET_TTL_SECONDS, issue_ticket, redeem_ticket
from .deps import get_current_user, load_active_user

logger = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

#: Server poll interval — how often PostgreSQL is queried for updates.
_POLL_INTERVAL_SECONDS = 2.0
#: Look-back window: jobs updated within the last N seconds are pushed.
_UPDATE_WINDOW_SECONDS = 30
#: Cap on pushed rows per cycle (defensive; one user rarely has more).
_MAX_EVENTS_PER_CYCLE = 100
#: Bound a polling connection so abandoned clients cannot hold a DB task forever.
_MAX_STREAM_SECONDS = 30 * 60
#: Minimum delay between two consecutive poll-error logs.  A database that
#: stays unreachable must not produce one traceback every 2 seconds for the
#: whole 30-minute lifetime of the stream.
_POLL_ERROR_LOG_INTERVAL_SECONDS = 60.0


def _blast_updated_at():
    """Blast rows carry no ``updated_at`` column (no TimestampMixin) — use
    the most recent lifecycle timestamp as the update marker."""
    return func.coalesce(BlastJob.completed_at, BlastJob.started_at, BlastJob.submitted_at)


async def get_optional_sse_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Resolve the stream's credential from ``Authorization`` or ``?ticket=``.

    Returns ``None`` when no credential is supplied (anonymous stream); raises
    :class:`AuthenticationError` (401) when a supplied credential is invalid.

    A raw access token in the query string is rejected outright, header or no
    header: the edge proxy logs the request line, so ``?access_token=`` writes
    a live session credential to ``access.log``.  The only URL credential is
    the single-use ticket from ``POST /api/v1/jobs/sse-ticket``.
    """
    if "access_token" in request.query_params:
        raise AuthenticationError(
            "The access token must not be sent in the query string; exchange it "
            "for a single-use ticket at POST /api/v1/jobs/sse-ticket"
        )

    token: str | None = None
    auth_header = request.headers.get("Authorization")
    if auth_header:
        scheme, _, value = auth_header.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            token = value.strip()
    if token is not None:
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        return await get_current_user(db=db, credentials=credentials)

    ticket = request.query_params.get("ticket")
    if not ticket:
        return None
    user_id = await redeem_ticket(ticket)
    if user_id is None:
        # Malformed, unknown, expired and already-redeemed tickets are one
        # answer on purpose: a replay learns nothing about the others.
        raise AuthenticationError("Invalid or expired SSE ticket")
    return await load_active_user(db, user_id)


@router.post("/sse-ticket", response_model=SseTicketResponse)
async def create_sse_ticket(
    response: Response,
    current_user: User = Depends(get_current_user),
) -> SseTicketResponse:
    """Exchange an authenticated session for one single-use stream ticket.

    ``EventSource`` cannot send an ``Authorization`` header, but the access
    token must not travel in the stream URL (nginx logs the query string).
    This endpoint returns an opaque ticket that ``GET /jobs/events?ticket=``
    accepts exactly once, within :data:`SSE_TICKET_TTL_SECONDS`.
    """
    ticket = await issue_ticket(current_user.id)
    response.headers["Cache-Control"] = "private, no-store"
    return SseTicketResponse(ticket=ticket, expires_in=SSE_TICKET_TTL_SECONDS)


async def _recent_job_updates(db: AsyncSession, user_id: UUID | None) -> list[dict]:
    """Return the user's jobs updated in the trailing 30s window.

    Three tables (``blast_jobs`` / ``analysis_jobs`` / ``gwas_jobs``) are
    UNIONed and ordered by their update timestamp, newest first.  Anonymous
    callers get ``user_id IS NULL`` jobs only.
    """
    since = datetime.now(timezone.utc) - timedelta(seconds=_UPDATE_WINDOW_SECONDS)  # noqa: UP017

    def user_condition(user_id_column):
        if user_id is None:
            return user_id_column.is_(None)
        return user_id_column == user_id

    # `status` has a different physical type per table (varchar on blast_jobs,
    # `analysis_job_status_enum` on analysis_jobs), and PostgreSQL refuses to
    # UNION mismatched types. Casting all three to text keeps the union valid;
    # without it the statement aborts the surrounding transaction, which then
    # poisons every later request on the same pooled connection.
    blast_stmt = (
        select(
            literal("blast").label("job_type"),
            BlastJob.id.label("job_id"),
            cast(BlastJob.status, String).label("status"),
            _blast_updated_at().label("updated_at"),
        )
        .where(user_condition(BlastJob.user_id))
        .where(_blast_updated_at() >= since)
    )
    analysis_stmt = (
        select(
            literal("analysis").label("job_type"),
            AnalysisJob.id.label("job_id"),
            cast(AnalysisJob.status, String).label("status"),
            AnalysisJob.updated_at.label("updated_at"),
        )
        .where(user_condition(AnalysisJob.user_id))
        .where(AnalysisJob.updated_at >= since)
    )
    gwas_stmt = (
        select(
            literal("gwas").label("job_type"),
            GwasJob.id.label("job_id"),
            cast(GwasJob.status, String).label("status"),
            GwasJob.updated_at.label("updated_at"),
        )
        .where(user_condition(GwasJob.user_id))
        .where(GwasJob.updated_at >= since)
    )

    stmt = (
        blast_stmt.union_all(analysis_stmt, gwas_stmt)
        .order_by(text("updated_at DESC"))
        .limit(_MAX_EVENTS_PER_CYCLE)
    )
    rows = (await db.execute(stmt)).all()

    return [
        {
            "job_type": row.job_type,
            "job_id": str(row.job_id),
            "status": row.status,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


async def _rollback_session(session: AsyncSession) -> None:
    """Roll a session's transaction back, ignoring failures.

    An aborted transaction poisons every later request that reuses the
    pooled connection, so the rollback is not optional after a failed
    statement.
    """
    try:
        await session.rollback()
    except Exception:
        logger.warning("jobs_events_rollback_failed", exc_info=True)


async def _poll_job_updates(user_id: UUID | None) -> list[dict]:
    """Return the user's recent job updates for a single poll cycle.

    The SSE response outlives the request that created it: FastAPI closes
    the request-scoped session only *after* the response body has been
    produced — up to 30 minutes for this endpoint — so polling through
    that session would pin one of the few pooled connections
    (``db_pool_size`` + ``db_max_overflow``) for the whole stream.

    Every cycle therefore opens its own short-lived session on the pooled
    engine and closes it again as soon as the query is done: the
    connection is back in the pool before the stream sleeps, and a single
    client never holds more than one connection.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            return await _recent_job_updates(session, user_id)
        except Exception:
            # The failed statement aborted the transaction.  Roll it back
            # so the connection is handed back to the pool in a clean state
            # (an aborted transaction poisons every later request that
            # reuses it).  The session is discarded either way, so the next
            # cycle starts from a fresh, usable transaction.
            await _rollback_session(session)
            raise


async def _release_pooled_connection(db: AsyncSession) -> None:
    """Return the request-scoped session's pooled connection to the pool.

    The optional token lookup reads a user row and therefore checks a
    connection out of the pool.  FastAPI closes the request-scoped session
    only after the response body has been produced — up to 30 minutes for
    an SSE stream — so the connection is released here, before the stream
    starts.  The lookup is read-only, so ending its transaction is safe.
    """
    await _rollback_session(db)


@router.get("/events")
async def job_events(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_sse_user),
) -> StreamingResponse:
    """Stream job status updates as Server-Sent Events.

    Event format (one per updated job)::

        event: job_update
        data: {"job_type": "blast", "job_id": "...", "status": "running",
               "updated_at": "2026-08-09T12:00:00+00:00"}

    When no job changed in the last poll cycle a ``: ping`` heartbeat
    comment line is emitted instead.  The stream ends when the client
    disconnects.
    """

    # The stream polls on its own short-lived sessions; the request-scoped
    # session (used by the optional auth lookup) must not keep its pooled
    # connection while the stream is running.
    # Rollback expires ORM attributes, including the primary key, even with
    # expire_on_commit=False. Carry only the scalar identity into the stream.
    user_id = user.id if user is not None else None
    await _release_pooled_connection(db)

    async def event_stream() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _MAX_STREAM_SECONDS
        failed_cycles = 0
        last_error_log = 0.0
        try:
            while loop.time() < deadline:
                if await request.is_disconnected():
                    return
                try:
                    updates = await _poll_job_updates(user_id)
                except Exception:
                    # A transient query failure must not kill the stream:
                    # the cycle ran on its own session, so the next cycle
                    # starts from a clean transaction and can recover.
                    failed_cycles += 1
                    now = loop.time()
                    if (
                        failed_cycles == 1
                        or now - last_error_log >= _POLL_ERROR_LOG_INTERVAL_SECONDS
                    ):
                        # Rate-limited: a database that stays down would
                        # otherwise log one traceback every 2 seconds for
                        # the whole 30-minute lifetime of the stream.
                        logger.exception(
                            "jobs_events_poll_error",
                            failed_cycles=failed_cycles,
                        )
                        last_error_log = now
                    updates = []
                else:
                    if failed_cycles:
                        logger.info("jobs_events_poll_recovered", failed_cycles=failed_cycles)
                        failed_cycles = 0

                if updates:
                    for update in updates:
                        yield f"event: job_update\ndata: {json.dumps(update)}\n\n"
                else:
                    # Heartbeat comment line (SSE comments are ignored by
                    # EventSource) keeps idle connections alive.
                    yield ": ping\n\n"

                await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            yield 'event: stream_end\ndata: {"reason":"max_lifetime"}\n\n'
        except asyncio.CancelledError:
            # Client disconnected (or server shutting down) — stop cleanly.
            raise

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "private, no-store",
            "Vary": "Authorization",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["create_sse_ticket", "get_optional_sse_user", "job_events", "router"]
