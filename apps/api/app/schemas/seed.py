"""Pydantic v2 schemas for seed inventory and seed request management."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from ..core.compat import StrEnum


class SeedAvailability(StrEnum):
    AVAILABLE = "available"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"
    PENDING_HARVEST = "pending_harvest"


class SeedRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    SHIPPED = "shipped"
    COMPLETED = "completed"
    REJECTED = "rejected"


class SeedInventoryResponse(BaseModel):
    """Public seed-inventory projection.

    ``seed_lot`` is the public locator (the lot label the collection uses) and
    ``mutant_line_public_id`` is the line's public identifier. The inventory row
    id and the mutant line's internal key are persistence details and are not
    part of the external contract.
    """

    mutant_line_public_id: str
    seed_lot: str
    quantity_grams: float
    location: str | None = None
    harvest_date: date | None = None
    viability_pct: float | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SeedRequestCreate(BaseModel):
    #: Public mutant-line identifier (e.g. ``SM7K3ZQ9P2AX``). Resolved to the
    #: line's internal key server-side inside the published release; a numeric
    #: or otherwise internal value is rejected.
    mutant_line_public_id: str
    quantity_grams: float = Field(..., gt=0.0, le=500.0)
    requester_name: str = Field(..., min_length=1, max_length=255)
    requester_email: EmailStr
    requester_institution: str = Field(..., min_length=1, max_length=500)
    purpose: str = Field(..., min_length=10, max_length=5000)
    agrees_to_terms: bool

    @field_validator("agrees_to_terms")
    @classmethod
    def _must_agree(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must agree to the terms and conditions")
        return v


class SeedRequestResponse(BaseModel):
    """Public seed-request projection: the line is identified publicly.

    ``id`` is the request's own opaque UUID (it is the requester's tracking
    handle), never the line's internal key.
    """

    id: str
    mutant_line_public_id: str
    status: SeedRequestStatus
    quantity_requested: float | None = None
    requester_name: str
    requester_email: str
    requester_institution: str
    purpose: str
    tracking_number: str | None = None
    notes: str | None = None
    created_at: datetime
    reviewed_at: datetime | None = None

    model_config = {"from_attributes": True}


class SeedRequestUpdate(BaseModel):
    status: SeedRequestStatus
    tracking_number: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=5000)
