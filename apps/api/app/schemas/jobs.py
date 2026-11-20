"""Pydantic schemas for the job-status push endpoints (D5).

Contract:
- ``POST /api/v1/jobs/sse-ticket`` -> :class:`SseTicketResponse`
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SseTicketResponse(BaseModel):
    """A single-use credential for one SSE subscription.

    The ticket is opaque and bound server-side to the authenticated caller. It
    is presented as ``?ticket=`` on ``GET /api/v1/jobs/events`` and stops
    working after its first use or after ``expires_in`` seconds.
    """

    ticket: str = Field(
        ...,
        description=(
            "Opaque single-use ticket for the `ticket` query parameter of the job event stream."
        ),
    )
    expires_in: int = Field(
        ...,
        description=(
            "Seconds until the ticket expires (at most 60); it is also "
            "invalidated by its first use."
        ),
    )


__all__ = ["SseTicketResponse"]
