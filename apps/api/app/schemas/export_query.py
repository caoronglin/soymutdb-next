"""No-SQL query builder request for the unified download/export centre.

The platform already has one asynchronous export pipeline (outbox -> ``export``
queue -> object storage). The query builder does not add a second retrieval
engine: it accepts a whitelist of filters, verifies that each one maps onto a
filter the existing variant-export worker actually understands, and submits
through that same pipeline.

Filters that have no backing query capability are refused with a 422 rather
than silently ignored. A form that accepts ``go_term`` and then drops it would
let a downloader believe their artifact was narrowed by a GO annotation when
it was not — the same "fake measurement" mistake the rest of the platform
refuses.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from .variant import VariantExportFilters

#: Filters the current variant-export pipeline can actually apply. Each name
#: maps 1:1 onto a ``VariantExportFilters`` field the worker binds in its SQL.
SUPPORTED_QUERY_FILTERS: frozenset[str] = frozenset({
    "assembly", "chromosome", "start", "end", "ref", "alt", "gene_id",
    "variant_type", "consequence", "impact", "min_af", "max_af",
    "mutant_line_public_id",
})

#: Filters the brief asks for that have no product-backed query path yet.
#: They are documented, refused explicitly, and never silently dropped.
UNSUPPORTED_QUERY_FILTERS: frozenset[str] = frozenset({
    "gene_list", "species", "biotype", "go_term", "kegg_term",
    "expression_threshold", "homolog_species",
})


class ExportQueryRequest(BaseModel):
    """A whitelisted filter set for one variant-export artifact.

    ``extra='forbid'`` is the core of the contract: an unknown key is a 422,
    not a parameter that quietly vanishes. Release/assembly are resolved by
    the server from the published release context, never trusted from the
    body as a provenance claim.
    """

    model_config = {"extra": "forbid"}

    format: str = Field(default="tsv", pattern=r"^(vcf|tsv|csv|json|bed)$")
    compress: bool = True
    filters: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_unsupported_filters(self) -> ExportQueryRequest:
        unknown = set(self.filters) - SUPPORTED_QUERY_FILTERS
        if unknown:
            raise ValueError(
                "Unsupported query filter(s): "
                + ", ".join(sorted(unknown))
                + ". Supported: "
                + ", ".join(sorted(SUPPORTED_QUERY_FILTERS))
                + ". Filters with no backing query capability "
                + "(" + ", ".join(sorted(UNSUPPORTED_QUERY_FILTERS)) + ") "
                "are refused rather than silently ignored."
            )
        # Validate values against the real export filter schema so an invalid
        # enum or out-of-range coordinate is refused before an export record
        # and an outbox event are written.
        VariantExportFilters(**self.filters)
        return self


class ExportQueryResponse(BaseModel):
    """The durable export record the query builder submitted."""

    export_id: str
    status: str
    message: str
    format: str
    applied_filters: dict[str, object] = Field(default_factory=dict)
    unsupported_filters: list[str] = Field(default_factory=list)
