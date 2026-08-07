"""EMBL-EBI Search adapter (EBI Search REST API).

Docs: https://www.ebi.ac.uk/ebisearch/documentation/rest-api
Endpoint: https://www.ebi.ac.uk/ebisearch/ws/rest/

We target the ``embl-cds`` (coding sequences) and ``ensemblPlants``
domains and accept soy / glycine max queries (default species).
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote_plus

import httpx

from ..models import SearchHit, SearchSource
from .base import BaseAdapter

EBI_BASE = "https://www.ebi.ac.uk/ebisearch/ws/rest"
DOMAINS = ["ensemblPlants", "embl-cds", "uniprotkb"]


class EBIAdapter(BaseAdapter):
    source: ClassVar[SearchSource] = SearchSource.EBI
    base_url: ClassVar[str] = "https://www.ebi.ac.uk"

    rate_per_second: float = 5.0
    rate_burst: int = 10

    async def do_search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[SearchHit]:
        hits: list[SearchHit] = []
        per_domain = max(1, limit // len(DOMAINS) + 1)
        for domain in DOMAINS:
            if len(hits) >= limit:
                break
            try:
                hits.extend(await self._search_domain(client, domain, query, per_domain))
            except httpx.HTTPStatusError as e:
                # Ignore 404s per-domain.
                if e.response.status_code != 404:
                    raise
        return hits[:limit]

    async def _search_domain(
        self, client: httpx.AsyncClient, domain: str, query: str, limit: int
    ) -> list[SearchHit]:
        # Boost default-species (soybean) hits when possible by appending glycine max.
        q = f"({query}) AND glycine max"
        params: dict[str, Any] = {
            "query": q,
            "size": min(limit, 15),
            "format": "json",
            "fields": "id,name,description,source_scientific,author,publication",
        }
        url = f"{EBI_BASE}/{quote_plus(domain)}"
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        entries = data.get("entries", []) or []
        hits: list[SearchHit] = []
        for entry in entries:
            eid = entry.get("id", "")
            fields = entry.get("fields", {}) or {}
            title = _first(fields.get("name")) or _first(fields.get("description")) or eid
            desc = _first(fields.get("description")) or ""
            org = _first(fields.get("source_scientific")) or ""
            snippet_parts = [p for p in (desc, org, domain) if p]
            hits.append(
                SearchHit(
                    source=SearchSource.EBI,
                    id=eid,
                    title=title[:200],
                    url=self._entry_url(domain, eid),
                    snippet=" — ".join(snippet_parts)[:240],
                    extra={"domain": domain, "organism": org},
                )
            )
        return hits

    @staticmethod
    def _entry_url(domain: str, eid: str) -> str:
        if domain == "uniprotkb":
            return f"https://www.uniprot.org/uniprotkb/{eid}"
        if domain.startswith("ensembl"):
            return f"https://plants.ensembl.org/id/{eid}"
        if domain == "embl-cds":
            return f"https://www.ebi.ac.uk/ena/browser/view/{eid}"
        return f"https://www.ebi.ac.uk/ebisearch/search.ebi?db={quote_plus(domain)}&query={quote_plus(eid)}"


def _first(val: Any) -> str:
    """EBI fields can be strings or lists of strings; return first string."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return str(val[0]) if val else ""
    return str(val)
