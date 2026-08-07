"""External search source adapters."""

from __future__ import annotations

from .base import BaseAdapter
from .ebi import EBIAdapter
from .ensembl import EnsemblAdapter
from .ncbi import NCBIAdapter
from .uniprot import UniProtAdapter

__all__ = [
    "BaseAdapter",
    "NCBIAdapter",
    "UniProtAdapter",
    "EnsemblAdapter",
    "EBIAdapter",
]
