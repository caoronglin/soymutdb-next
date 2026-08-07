"""NCBI E-utilities adapter (ESearch + ESummary).

Targets the Gene database (with ``glycine max`` OR taxid 3847 scoped) plus
PubMed when the query looks like a literature term.  Kept conservative on
rate (3 req/s without an API key is the documented limit).
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from ..models import SearchHit, SearchSource
from .base import BaseAdapter

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class NCBIAdapter(BaseAdapter):
    source: ClassVar[SearchSource] = SearchSource.NCBI
    base_url: ClassVar[str] = "https://www.ncbi.nlm.nih.gov"

    # NCBI allows 3 req/s without API key, 10 req/s with.
    rate_per_second: float = 2.5
    rate_burst: int = 4

    async def do_search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[SearchHit]:
        hits: list[SearchHit] = []
        # 1. Gene search (soybean-scoped).
        gene_term = f"({query}) AND (glycine max[organism] OR txid3847[Organism:noexp])"
        gene_hits = await self._search_gene(client, gene_term, limit=min(limit, 6))
        hits.extend(gene_hits)
        # 2. PubMed search for the raw query (capped to keep response small).
        remaining = limit - len(hits)
        if remaining > 0:
            pubmed_hits = await self._search_pubmed(client, query, limit=remaining)
            hits.extend(pubmed_hits)
        return hits[:limit]

    async def _search_gene(self, client: httpx.AsyncClient, term: str, limit: int) -> list[SearchHit]:
        # ESearch
        params: dict[str, Any] = {"db": "gene", "term": term, "retmax": limit, "retmode": "json"}
        r = await client.get(f"{EUTILS_BASE}/esearch.fcgi", params=params)
        r.raise_for_status()
        data = r.json()
        idlist: list[str] = data.get("esearchresult", {}).get("idlist", [])
        if not idlist:
            return []
        # ESummary
        params2 = {"db": "gene", "id": ",".join(idlist), "retmode": "json"}
        r2 = await client.get(f"{EUTILS_BASE}/esummary.fcgi", params=params2)
        r2.raise_for_status()
        summ = r2.json().get("result", {})
        hits: list[SearchHit] = []
        for uid in idlist:
            doc = summ.get(uid)
            if not doc:
                continue
            name = doc.get("name") or doc.get("description") or uid
            desc = doc.get("description") or doc.get("title") or ""
            org = doc.get("organism", {}).get("scientificname", "")
            snippet_parts = [desc]
            if org:
                snippet_parts.append(f"[{org}]")
            if doc.get("chromosome"):
                snippet_parts.append(f"Chr {doc['chromosome']}")
            maploc = doc.get("maplocation")
            if maploc:
                snippet_parts.append(maploc)
            hits.append(
                SearchHit(
                    source=SearchSource.NCBI,
                    id=uid,
                    title=name,
                    url=f"https://www.ncbi.nlm.nih.gov/gene/{uid}",
                    snippet=" ".join(p for p in snippet_parts if p)[:240],
                    extra={"db": "gene", "organism": org, "symbol": name},
                )
            )
        return hits

    async def _search_pubmed(self, client: httpx.AsyncClient, term: str, limit: int) -> list[SearchHit]:
        params = {"db": "pubmed", "term": term, "retmax": limit, "retmode": "json"}
        r = await client.get(f"{EUTILS_BASE}/esearch.fcgi", params=params)
        r.raise_for_status()
        idlist: list[str] = r.json().get("esearchresult", {}).get("idlist", [])
        if not idlist:
            return []
        r2 = await client.get(
            f"{EUTILS_BASE}/esummary.fcgi",
            params={"db": "pubmed", "id": ",".join(idlist), "retmode": "json"},
        )
        r2.raise_for_status()
        summ = r2.json().get("result", {})
        hits: list[SearchHit] = []
        for uid in idlist:
            doc = summ.get(uid)
            if not doc:
                continue
            title = doc.get("title", "") or uid
            source_j = doc.get("source", "")
            pubdate = doc.get("pubdate", "")
            authors = doc.get("authors", [])
            author_str = ", ".join(a.get("name", "") for a in authors[:3])
            if len(authors) > 3:
                author_str += " et al."
            snippet_bits = [p for p in (author_str, source_j, pubdate) if p]
            hits.append(
                SearchHit(
                    source=SearchSource.NCBI,
                    id=f"pmid:{uid}",
                    title=title,
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                    snippet=" — ".join(snippet_bits)[:240],
                    extra={"db": "pubmed", "journal": source_j, "pubdate": pubdate},
                )
            )
        return hits
