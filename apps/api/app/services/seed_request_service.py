"""Seed request contact service — create + admin list/update + email dispatch.

Follows the BLAST / GWAS outbox pattern: the request row and the outbox
event are committed in the **same transaction**; a background dispatcher
forwards the event to the worker, which renders and sends the confirmation
and admin-notification emails (or writes them under ``logs/emails/`` when
SMTP is disabled, so dev is verifiable without a mail server).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.exceptions import NotFoundError, ValidationError
from ..core.task_contract import SEED_REQUEST_EMAIL_TASK
from ..models.seed_request import SeedRequestContact, SeedRequestStatus
from ..schemas.seed_request import (
    SeedRequestCreate,
    SeedRequestListResponse,
    SeedRequestResponse,
    SeedRequestUpdate,
)
from .job_service import build_job_payload
from .outbox_service import create_outbox_event

settings = get_settings()

#: Legal status transitions of the contact lifecycle.  Terminal states
#: (``rejected`` / ``fulfilled``) never transition.
_ALLOWED_TRANSITIONS: dict[SeedRequestStatus, frozenset[SeedRequestStatus]] = {
    SeedRequestStatus.PENDING: frozenset(
        {SeedRequestStatus.APPROVED, SeedRequestStatus.REJECTED}
    ),
    SeedRequestStatus.APPROVED: frozenset(
        {SeedRequestStatus.FULFILLED, SeedRequestStatus.REJECTED}
    ),
    SeedRequestStatus.REJECTED: frozenset(),
    SeedRequestStatus.FULFILLED: frozenset(),
}


class SeedRequestService:
    """Public seed request contacts + admin processing."""

    async def create_request(
        self, db: AsyncSession, payload: SeedRequestCreate
    ) -> SeedRequestResponse:
        """Persist a request and queue its email dispatch via the outbox.

        Business row + outbox event are committed atomically; no Celery
        broker round-trip happens inside this transaction.
        """
        request = SeedRequestContact(
            id=uuid.uuid4(),
            name=payload.name,
            email=payload.email,
            institution=payload.institution,
            country=payload.country,
            gene_ids=list(payload.gene_ids),
            notes=payload.notes,
            status=SeedRequestStatus.PENDING,
        )
        db.add(request)
        await db.flush()

        # The outbox event carries the full versioned JobPayload; the worker
        # validates it with the shared schema before rendering any email.
        job_payload = build_job_payload(
            job_id=request.id,
            task_name=SEED_REQUEST_EMAIL_TASK,
            payload={
                "request_id": str(request.id),
                "name": request.name,
                "email": request.email,
                "institution": request.institution,
                "country": request.country,
                "gene_ids": request.gene_ids,
                "notes": request.notes,
                "status": request.status,
            },
            idempotency_key=f"seed-request-email:{request.id}",
            max_attempts=3,
        )
        await create_outbox_event(
            db,
            aggregate_type="seed_request",
            aggregate_id=str(request.id),
            event_type="seed_request.created",
            payload=job_payload.model_dump(mode="json"),
        )

        await db.commit()
        await db.refresh(request)
        return self._to_response(request)

    async def list_requests(
        self,
        db: AsyncSession,
        *,
        page: int = 1,
        page_size: int = 20,
        status: SeedRequestStatus | None = None,
    ) -> SeedRequestListResponse:
        """Paginated admin listing, newest first, optional status filter."""
        filters = []
        if status is not None:
            filters.append(SeedRequestContact.status == status.value)

        total_result = await db.execute(
            select(func.count())
            .select_from(SeedRequestContact)
            .where(*filters)
        )
        total = int(total_result.scalar() or 0)

        stmt = (
            select(SeedRequestContact)
            .where(*filters)
            .order_by(SeedRequestContact.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await db.execute(stmt)
        items = [self._to_response(row) for row in result.scalars().all()]
        return SeedRequestListResponse(
            items=items, total=total, page=page, page_size=page_size
        )

    async def count_requests_by_gene(
        self,
        db: AsyncSession,
        *,
        gene_ids: list[str],
        max_gene_ids: int = 200,
    ) -> dict[str, int]:
        """Count the seed requests that reference each of *gene_ids*.

        Aggregate only — see ``SeedRequestGeneCount`` for why. The gene IDs on a
        request are the requester's own free text, so this is a literal string
        match against what people typed, **not** a resolution to released
        records; callers must not present it as one.

        ``CROSS JOIN LATERAL`` over ``jsonb_array_elements_text`` counts each
        request once per matching gene without a self-join or a temp table.
        """
        # Ordered de-duplication, so the response is deterministic and a caller
        # cannot widen the query with a huge repeated list.
        wanted = [value for value in dict.fromkeys(gene_ids) if value][:max_gene_ids]
        if not wanted:
            return {}

        stmt = text(
            """
            SELECT g.gene_id AS gene_id, count(*) AS requests
            FROM seed_request_contacts AS c
            CROSS JOIN LATERAL jsonb_array_elements_text(c.gene_ids) AS g(gene_id)
            WHERE g.gene_id = ANY(:ids)
            GROUP BY g.gene_id
            """
        )
        result = await db.execute(stmt, {"ids": wanted})
        return {str(row.gene_id): int(row.requests) for row in result.all()}

    async def total_requests(self, db: AsyncSession) -> int:
        """Count every seed request on record, regardless of gene or status."""
        result = await db.execute(select(func.count()).select_from(SeedRequestContact))
        return int(result.scalar() or 0)

    async def update_status(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        update: SeedRequestUpdate,
        processed_by: uuid.UUID,
    ) -> SeedRequestResponse:
        """Advance a request's status (transition-validated, admin only)."""
        result = await db.execute(
            select(SeedRequestContact).where(SeedRequestContact.id == request_id)
        )
        request = result.scalar_one_or_none()
        if request is None:
            raise NotFoundError(f"Seed request {request_id} not found")

        current = SeedRequestStatus(request.status)
        allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
        if update.status not in allowed:
            raise ValidationError(
                f"Illegal seed request status transition: "
                f"{current.value} -> {update.status.value}"
            )

        request.status = update.status.value
        request.processed_by = processed_by
        request.processed_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(request)
        return self._to_response(request)

    @staticmethod
    def _to_response(request: SeedRequestContact) -> SeedRequestResponse:
        return SeedRequestResponse(
            id=str(request.id),
            name=request.name,
            email=request.email,
            institution=request.institution,
            country=request.country,
            gene_ids=list(request.gene_ids or []),
            notes=request.notes,
            status=SeedRequestStatus(request.status),
            created_at=request.created_at,
            processed_at=request.processed_at,
            processed_by=(
                str(request.processed_by) if request.processed_by else None
            ),
        )


__all__ = ["SeedRequestService"]
