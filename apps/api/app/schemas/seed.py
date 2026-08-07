"""Pydantic v2 schemas for seed inventory and seed request management."""

from __future__ import annotations

from datetime import date, datetime
from ..core.compat import StrEnum

from pydantic import BaseModel, EmailStr, Field, field_validator


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
    id: str
    mutant_line_id: str
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
    mutant_line_id: str
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
    id: str
    mutant_line_id: str
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
