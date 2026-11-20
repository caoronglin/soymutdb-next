"""Wire contract for comparative genomics.

Three rules shape every model here:

* a relationship type is stated per row and never inferred from sequence
  similarity (``blast_hit`` is not on this axis at all -- see
  :func:`app.services.comparative_service.homology_evidence`);
* a species with no member is reported as ``state="no_data"``, not as an empty
  member list;
* an alignment or tree is a job with a frozen input hash, not a value the API
  can produce inline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .gene_evidence import EvidenceTag

#: Membership relationship types, in the order the UI ranks them.
RELATIONSHIP_TYPES = ("one_to_one", "one_to_many", "many_to_many")

#: Presence of comparative data for one scope.
#:
#: ``no_data`` is reserved for "the source has no rows for this species/scope".
#: It is deliberately distinct from ``empty``: an empty family (rows exist, this
#: species contributes none) would be a claim that the species has no member,
#: which the platform cannot make from absence alone.
COMPARATIVE_STATES = ("available", "no_data", "not_imported")


class FamilyMemberResponse(BaseModel):
    gene_accession: str
    species: str
    relationship_type: Literal[RELATIONSHIP_TYPES]  # type: ignore[valid-type]
    method: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: dict | None = None


class SpeciesCoverageResponse(BaseModel):
    """Per-species presence in one family.

    ``state`` is what the client renders. ``member_count`` is ``None`` whenever
    no member row exists -- never 0 with ``state="available"``, because that
    would turn "not imported/not present" into a measured zero.
    """

    species: str
    state: Literal[COMPARATIVE_STATES]  # type: ignore[valid-type]
    member_count: int | None = Field(default=None, ge=0)


class FamilyResponse(BaseModel):
    family_id: int
    level: Literal["gene_family", "gene_subfamily"]
    external_id: str
    name: str
    method: str
    method_version: str | None = None
    source_name: str
    source_version: str
    source_url: str
    release_id: int
    assembly_id: int
    member_count: int = Field(default=0, ge=0)
    #: Evidence class of the grouping itself. Always ``predicted`` or
    #: ``imported`` in practice; never ``experimental``.
    evidence: EvidenceTag


class FamilyListResponse(BaseModel):
    items: list[FamilyResponse] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = 1
    page_size: int = 20


class FamilyDetailResponse(FamilyResponse):
    """A family with its members and per-species coverage.

    ``coverage`` names every species the release knows about for this family,
    including species with no row (``state="no_data"``), so a presence/absence
    view can be drawn without the client inventing the missing species.
    """

    members: list[FamilyMemberResponse] = Field(default_factory=list)
    coverage: list[SpeciesCoverageResponse] = Field(default_factory=list)
    relationship_types: list[str] = Field(default_factory=list)


class MemberComparisonResponse(BaseModel):
    """Two families side by side: shared and unique members.

    ``shared`` is set intersection of gene accessions; ``only_left`` /
    ``only_right`` are the differences. Species coverage is reported per side so
    a species missing from one family is visible as ``no_data``, not as "absent
    from the comparison".
    """

    left: FamilyResponse
    right: FamilyResponse
    shared: list[FamilyMemberResponse] = Field(default_factory=list)
    only_left: list[FamilyMemberResponse] = Field(default_factory=list)
    only_right: list[FamilyMemberResponse] = Field(default_factory=list)
    coverage: list[SpeciesCoverageResponse] = Field(default_factory=list)


class OrthologRecord(BaseModel):
    """One directional ortholog/paralog assertion.

    ``similarity`` deliberately does not appear: a BLAST hit is a similarity
    measurement, not an orthology assignment, and this record exists only for
    rows the source itself classified.
    """

    gene_accession: str
    counterpart_species: str | None = None
    counterpart_gene_id: str
    homolog_type: Literal["ortholog", "paralog"]
    relationship_type: Literal[RELATIONSHIP_TYPES]  # type: ignore[valid-type]
    method: str | None = None
    source: str | None = None
    release_id: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: EvidenceTag


class OrthologResponse(BaseModel):
    gene_id: str
    assembly_id: int
    release_id: int
    state: Literal[COMPARATIVE_STATES]  # type: ignore[valid-type]
    records: list[OrthologRecord] = Field(default_factory=list)


class ArtifactResponse(BaseModel):
    """An asynchronous alignment or tree, identified by its job."""

    artifact_type: Literal["msa", "tree"]
    job_id: UUID
    state: Literal["pending", "running", "succeeded", "failed"]
    method: str
    #: Hash over the ordered member set; a finished artifact is only ever shown
    #: next to this input.
    input_sha256: str
    input_member_ids: list[str] = Field(default_factory=list)
    #: Pre-signed download URL, present only once the artifact succeeded.
    download_url: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class ArtifactRequest(BaseModel):
    """Request to compute an alignment or tree for a family."""

    family_id: int = Field(..., gt=0)
    artifact_type: Literal["msa", "tree"]
    #: Pipeline to run. The API refuses anything not on the worker's allowlist;
    #: an unknown method never reaches the queue.
    method: str = Field(..., min_length=1, max_length=64)
    assembly_id: int | None = None


__all__ = [
    "COMPARATIVE_STATES",
    "RELATIONSHIP_TYPES",
    "ArtifactRequest",
    "ArtifactResponse",
    "FamilyDetailResponse",
    "FamilyListResponse",
    "FamilyMemberResponse",
    "FamilyResponse",
    "MemberComparisonResponse",
    "OrthologRecord",
    "OrthologResponse",
    "SpeciesCoverageResponse",
]
