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
  ``user_id IS NULL`` jobs only (public/system jobs).  A bearer token may be
  passed either via the ``Authorization`` header or the ``access_token``
  query parameter, because the browser ``EventSource`` API cannot set
  headers.  The token is short-lived and request logs never record query
  strings, but prefer the header for non-browser clients.
- The stream terminates when the client disconnects (checked every poll
  cycle; the generator is also cancelled by the ASGI server).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import String, cast, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from ...core.database import get_db
from ...models.analysis_job import AnalysisJob
from ...models.auth import User
from ...models.blast import BlastJob
from ...models.gwas import GwasJob
from .deps import get_current_user

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


def _blast_updated_at():
    """Blast rows carry no ``updated_at`` column (no TimestampMixin) — use
    the most recent lifecycle timestamp as the update marker."""
    return func.coalesce(
        BlastJob.completed_at, BlastJob.started_at, BlastJob.submitted_at
    )


async def get_optional_sse_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Resolve the bearer token from ``Authorization`` or ``?access_token=``.

    Returns ``None`` when no token is supplied (anonymous stream); raises
    :class:`AuthenticationError` (401) when a supplied token is invalid.
    """
    token: str | None = None
    auth_header = request.headers.get("Authorization")
    if auth_header:
        scheme, _, value = auth_header.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            token = value.strip()
    if token is None:
        token = request.query_params.get("access_token")
    if not token:
        return None
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return await get_current_user(db=db, credentials=credentials)


async def _recent_job_updates(
    db: AsyncSession, user: User | None
) -> list[dict]:
    """Return the user's jobs updated in the trailing 30s window.

    Three tables (``blast_jobs`` / ``analysis_jobs`` / ``gwas_jobs``) are
    UNIONed and ordered by their update timestamp, newest first.  Anonymous
    callers get ``user_id IS NULL`` jobs only.
    """
    since = datetime.now(timezone.utc) - timedelta(seconds=_UPDATE_WINDOW_SECONDS)  # noqa: UP017

    def user_condition(user_id_column):
        if user is None:
            return user_id_column.is_(None)
        return user_id_column == user.id

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

    async def event_stream() -> AsyncIterator[str]:
        deadline = asyncio.get_running_loop().time() + _MAX_STREAM_SECONDS
        try:
            while asyncio.get_running_loop().time() < deadline:
                if await request.is_disconnected():
                    return
                try:
                    updates = await _recent_job_updates(db, user)
                except Exception:
                    # A transient query failure must not kill the stream;
                    # skip this cycle and try again on the next poll.
                    logger.exception("jobs_events_poll_error")
                    updates = []

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


__all__ = ["get_optional_sse_user", "job_events", "router"]
