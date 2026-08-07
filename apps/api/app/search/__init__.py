"""External search subsystem.

Provides parallel, fault-tolerant federated search across NCBI E-utilities,
UniProt, Ensembl and EMBL-EBI with Redis-backed circuit breakers, caching,
and HTML-fragment rendering (Jinja2 + bleach).
"""

from .aggregator import ExternalSearchAggregator
from .models import ExternalSearchResponse, SearchSource, SourceResult, SourceStatus
from .renderer import render_search_html

__all__ = [
    "ExternalSearchAggregator",
    "ExternalSearchResponse",
    "SearchSource",
    "SourceResult",
    "SourceStatus",
    "render_search_html",
]
