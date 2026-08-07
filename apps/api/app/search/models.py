"""Data models for the external search subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from ..core.compat import StrEnum
from typing import Any


class SearchSource(StrEnum):
    """Supported external search sources."""

    NCBI = "ncbi"
    UNIPROT = "uniprot"
    ENSEMBL = "ensembl"
    EBI = "ebi"
    INTERNAL = "internal"  # SoyMutDB own database (federated in for HTML view)


class SourceStatus(StrEnum):
    """Per-source result status for the aggregator response."""

    OK = "ok"
    EMPTY = "empty"
    TIMEOUT = "timeout"
    ERROR = "error"
    CIRCUIT_OPEN = "circuit_open"
    RATE_LIMITED = "rate_limited"


SOURCE_LABELS: dict[SearchSource, str] = {
    SearchSource.NCBI: "NCBI",
    SearchSource.UNIPROT: "UniProt",
    SearchSource.ENSEMBL: "Ensembl Plants",
    SearchSource.EBI: "EMBL-EBI Search",
    SearchSource.INTERNAL: "SoyMutDB",
}

SOURCE_URLS: dict[SearchSource, str] = {
    SearchSource.NCBI: "https://www.ncbi.nlm.nih.gov/",
    SearchSource.UNIPROT: "https://www.uniprot.org/",
    SearchSource.ENSEMBL: "https://plants.ensembl.org/",
    SearchSource.EBI: "https://www.ebi.ac.uk/",
    SearchSource.INTERNAL: "/",
}


@dataclass
class SearchHit:
    """Normalized result item from any source."""

    source: SearchSource
    title: str
    url: str
    snippet: str = ""
    id: str = ""
    # Optional source-specific metadata (e.g. accession, organism).
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceResult:
    """Aggregated result bundle for a single source."""

    source: SearchSource
    status: SourceStatus
    hits: list[SearchHit] = field(default_factory=list)
    elapsed_ms: float = 0.0
    error_message: str | None = None

    @property
    def label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source.value)

    @property
    def source_url(self) -> str:
        return SOURCE_URLS.get(self.source, "#")


@dataclass
class ExternalSearchResponse:
    """Top-level response returned by the aggregator."""

    query: str
    sources: list[SourceResult]
    elapsed_ms: float = 0.0

    @property
    def total_hits(self) -> int:
        return sum(len(s.hits) for s in self.sources if s.status == SourceStatus.OK)

    @property
    def any_ok(self) -> bool:
        return any(s.status in (SourceStatus.OK, SourceStatus.EMPTY) for s in self.sources)
