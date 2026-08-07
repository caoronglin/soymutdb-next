"""UniProt REST API adapter.

Docs: https://rest.uniprot.org/
We search against ``uniprotkb`` and prefer reviewed (Swiss-Prot) entries for
the default species, soybean (taxonomy 3847).  The REST endpoint returns JSON
with a ``results`` array.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from ..models import SearchHit, SearchSource
from .base import BaseAdapter

UNIPROT_BASE = "https://rest.uniprot.org"


class UniProtAdapter(BaseAdapter):
    source: ClassVar[SearchSource] = SearchSource.UNIPROT
    base_url: ClassVar[str] = "https://www.uniprot.org"

    rate_per_second: float = 5.0
    rate_burst: int = 10

    async def do_search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[SearchHit]:
        # Boost default-species (soybean, taxonomy 3847) results first, then fall back to any.
        tax_query = f"({query}) AND (taxonomy_id:3847)"
        hits = await self._search(client, tax_query, limit=limit)
        if not hits:
            hits = await self._search(client, query, limit=limit)
        return hits[:limit]

    async def _search(self, client: httpx.AsyncClient, q: str, limit: int) -> list[SearchHit]:
        params: dict[str, Any] = {
            "query": q,
            "size": min(limit, 25),
            "fields": "accession,id,protein_name,gene_names,organism_name,length,reviewed",
            "format": "json",
        }
        r = await client.get(f"{UNIPROT_BASE}/uniprotkb/search", params=params)
        r.raise_for_status()
        data = r.json()
        results: list[dict[str, Any]] = data.get("results", [])
        hits: list[SearchHit] = []
        for entry in results:
            acc = entry.get("primaryAccession", "")
            uni_id = entry.get("uniProtkbId", acc)
            protein = entry.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {})
            protein_name = protein.get("value", "") if isinstance(protein, dict) else str(protein)
            genes = entry.get("genes", [])
            gene_names: list[str] = []
            for g in genes:
                gn = g.get("geneName", {}).get("value")
                if gn:
                    gene_names.append(gn)
            organism = entry.get("organism", {}).get("scientificName", "")
            reviewed = entry.get("entryType", "").lower().startswith("uniprotkb_reviewed")
            snippet_parts: list[str] = []
            if protein_name:
                snippet_parts.append(protein_name)
            if gene_names:
                snippet_parts.append(f"Genes: {', '.join(gene_names[:3])}")
            if organism:
                snippet_parts.append(organism)
            tag = "Swiss-Prot" if reviewed else "TrEMBL"
            snippet_parts.append(tag)
            hits.append(
                SearchHit(
                    source=SearchSource.UNIPROT,
                    id=acc,
                    title=f"{uni_id} ({acc})",
                    url=f"https://www.uniprot.org/uniprotkb/{acc}",
                    snippet=" — ".join(snippet_parts)[:240],
                    extra={
                        "accession": acc,
                        "gene_names": gene_names,
                        "organism": organism,
                        "reviewed": reviewed,
                    },
                )
            )
        return hits
