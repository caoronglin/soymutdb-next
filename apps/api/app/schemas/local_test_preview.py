"""Response schemas for the loopback-only, unpublished local test preview."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PreviewAssembly(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["Gmax_880_v6.0"] = "Gmax_880_v6.0"
    version: Literal["v6.0"] = "v6.0"
    species: Literal["Glycine max"] = "Glycine max"
    status: Literal["unpublished"] = "unpublished"


class PreviewChromosome(BaseModel):
    name: str
    length: int


class PreviewGeneItem(BaseModel):
    gene_id: str
    gene_symbol: str | None
    chromosome: str
    start_pos: int
    end_pos: int
    strand: Literal["+", "-"]
    biotype: str
    mutation_site_count: int = Field(ge=0)


class PreviewGeneSearchResponse(BaseModel):
    preview: Literal[True] = True
    publication_status: Literal["unpublished"] = "unpublished"
    assembly: PreviewAssembly
    annotation_version: Literal["Wm82.a6.v1"] = "Wm82.a6.v1"
    query: str
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    items: list[PreviewGeneItem]


class PreviewMutationSiteItem(BaseModel):
    source_site_key: str
    mutant_line_name: str
    chromosome: str
    position: int = Field(ge=1)
    confidence: Literal["H", "L"]
    gene_id: str
    feature: str
    #: Operator-editable from the admin console; the import carries the stored
    #: value forward rather than resetting it.
    available: bool
    #: Homolog accessions from the same source row (W82_V2 / W82_V4 / DN53_V1).
    #: Absent when the source row leaves that column empty.
    gene_v2: str | None = None
    gene_v4: str | None = None
    gene_dn53: str | None = None


class PreviewMutationSiteUpdate(BaseModel):
    """Operator-editable fields of one source mutation-site row."""

    available: bool


class PreviewMutationSiteSearchResponse(BaseModel):
    preview: Literal[True] = True
    publication_status: Literal["unpublished"] = "unpublished"
    coordinate_system: Literal["1-based-inclusive"] = "1-based-inclusive"
    assembly: PreviewAssembly
    annotation_version: Literal["Wm82.a6.v1"] = "Wm82.a6.v1"
    chromosome: str
    start: int = Field(ge=1)
    end: int = Field(ge=1)
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=1000)
    items: list[PreviewMutationSiteItem]


class PreviewDatasetSource(BaseModel):
    key: Literal["03_soymut-a6-test"] = "03_soymut-a6-test"
    source_file: str
    source_sha256: str
    row_count: int = Field(ge=0)
    annotation_file: str
    annotation_sha256: str
    annotation_gene_count: int = Field(ge=0)


class LocalTestPreviewMeta(BaseModel):
    preview: Literal[True] = True
    publication_status: Literal["unpublished"] = "unpublished"
    coordinate_system: Literal["1-based-inclusive"] = "1-based-inclusive"
    dataset: PreviewDatasetSource
    assembly: PreviewAssembly
    annotation_version: Literal["Wm82.a6.v1"] = "Wm82.a6.v1"
    chromosomes: list[PreviewChromosome]


__all__ = [
    "LocalTestPreviewMeta",
    "PreviewAssembly",
    "PreviewChromosome",
    "PreviewDatasetSource",
    "PreviewGeneItem",
    "PreviewGeneSearchResponse",
    "PreviewMutationSiteItem",
    "PreviewMutationSiteSearchResponse",
    "PreviewMutationSiteUpdate",
]
