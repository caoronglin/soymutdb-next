"""Pydantic schemas for the SeqFetch sequence extraction tool.

Two mutually exclusive request modes:

- ``genes`` – batch extract the genomic span of up to 200 gene IDs from one assembly.
- ``assembly`` + ``region`` – extract a single ``chr:start-end`` interval
  from a named assembly.

Both are public, unauthenticated utilities.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from .genomic import Strand


class SeqFetchRequest(BaseModel):
    """Request body – exactly one of the two modes must be provided."""

    genes: list[str] | None = Field(
        default=None, max_length=200, description="Gene IDs to extract (≤200)."
    )
    assembly: str | None = Field(
        default=None,
        max_length=128,
        description="Assembly name (see /genes/assemblies) for region mode.",
    )
    region: str | None = Field(
        default=None,
        max_length=256,
        description="1-based interval, e.g. 'chr1:1000-2000'.",
    )

    @model_validator(mode="after")
    def _validate_mode(self) -> SeqFetchRequest:
        has_genes = self.genes is not None and len(self.genes) > 0
        has_region = self.region is not None
        has_assembly_only = self.assembly is not None and self.region is None
        if has_genes and has_region:
            raise ValueError("provide either 'genes' or 'assembly'+'region', not both")
        if has_region and self.assembly is None:
            raise ValueError("'assembly' and 'region' must be provided together")
        if has_assembly_only and not has_genes:
            raise ValueError("'assembly' and 'region' must be provided together")
        if not has_genes and not has_region:
            raise ValueError("provide either 'genes' or 'assembly'+'region'")
        if has_genes and self.assembly is None:
            raise ValueError("'assembly' is required with 'genes'")
        if has_genes and self.genes is not None:
            # De-duplicate while preserving request order; an all-empty list
            # (e.g. [""]) falls through to the "provide either" error above.
            seen: set[str] = set()
            self.genes = [g for g in self.genes if not (g in seen or seen.add(g))]
        return self


class SeqFetchResponse(BaseModel):
    """Extraction result.

    Small results return inline FASTA (``sequence``); results larger than
    10 MiB are stored in S3 and returned as a pre-signed ``download_url``
    instead (``sequence`` is ``None`` and ``truncated`` is ``False`` – the
    payload is complete, just delivered out-of-band).
    """

    format: str = "fasta"
    sequence: str | None = Field(
        default=None, description="Inline FASTA text when under the size cap."
    )
    count: int = Field(default=0, ge=0, description="Number of extracted sequences.")
    truncated: bool = Field(
        default=False,
        description="True when the result was capped and delivered as a file.",
    )
    missing: list[str] = Field(
        default_factory=list, description="Requested gene IDs that were not found."
    )
    download_url: str | None = Field(
        default=None, description="Pre-signed download URL for large results."
    )
    expires_in: int | None = Field(
        default=None, description="download_url lifetime in seconds."
    )


__all__ = ["SeqFetchRequest", "SeqFetchResponse", "Strand"]
