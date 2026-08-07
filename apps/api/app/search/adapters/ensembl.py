"""Ensembl Plants REST API adapter.

Docs: https://plants.ensembl.org/info/data/ftp/index.html
REST endpoint: https://plants.ensembl.org/rest/

We use ``/lookup/symbol`` and ``/xrefs/symbol`` for gene lookups and a
simple ``/search`` endpoint-style query against the ``/lookup/symbol``
for exact-ish matches on the default species Glycine max.  Ensembl REST
requires a ``Content-Type: application/json`` header and limits anonymous
clients to 15 req/s — we stay well below that.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from ..models import SearchHit, SearchSource
from .base import BaseAdapter

ENSEMBL_BASE = "https://plants.ensembl.org/rest"
# Default species for Ensembl lookups — extend by adding more species constants.
SOYBEAN_SPECIES = "glycine_max"


class EnsemblAdapter(BaseAdapter):
    source: ClassVar[SearchSource] = SearchSource.ENSEMBL
    base_url: ClassVar[str] = "https://plants.ensembl.org"

    # Ensembl allows 15 req/s for anonymous users.
    rate_per_second: float = 8.0
    rate_burst: int = 12

    async def do_search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[SearchHit]:
        # We don't have a generic text-search endpoint on Ensembl REST;
        # the primary useful lookup is by gene symbol / stable ID prefix.
        # We try: (1) lookup by exact symbol, (2) xrefs/symbol lookup.
        hits: list[SearchHit] = []
        # 1) Direct symbol lookup (returns single object or 404).
        try:
            url = f"{ENSEMBL_BASE}/lookup/symbol/{SOYBEAN_SPECIES}/{query}"
            r = await client.get(url, headers={"Content-Type": "application/json"})
            if r.status_code == 200:
                doc = r.json()
                hits.append(self._hit_from_lookup(doc))
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise

        if len(hits) < limit:
            # 2) POST /lookup/symbol accepts multiple symbols separated by commas
            # or use /xrefs/symbol to find matches. We try a wildcard-style
            # search through the family endpoint isn't available via REST,
            # so we fall back to xrefs/symbol with the raw query.
            try:
                url2 = f"{ENSEMBL_BASE}/xrefs/symbol/{SOYBEAN_SPECIES}/{query}?object_type=gene"
                r2 = await client.get(url2, headers={"Content-Type": "application/json"})
                if r2.status_code == 200:
                    xrefs: list[dict[str, Any]] = r2.json() or []
                    for xref in xrefs[:limit]:
                        hits.append(
                            SearchHit(
                                source=SearchSource.ENSEMBL,
                                id=xref.get("id", ""),
                                title=xref.get("display_id", xref.get("id", "Ensembl record")),
                                url=f"https://plants.ensembl.org/Glycine_max/Gene/Summary?g={xref.get('id','')}",
                                snippet=f"{xref.get('type', 'xref')} — {xref.get('dbname', '')}",
                                extra={"dbname": xref.get("dbname", ""), "object_type": "gene"},
                            )
                        )
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 404:
                    raise
        return hits[:limit]

    @staticmethod
    def _hit_from_lookup(doc: dict[str, Any]) -> SearchHit:
        gid = doc.get("id", "")
        display = doc.get("display_name", "") or gid
        desc = doc.get("description", "") or ""
        region = f"{doc.get('seq_region_name','')}:{doc.get('start','')}-{doc.get('end','')}"
        biotype = doc.get("biotype", "")
        bits = [p for p in (biotype, region) if p]
        return SearchHit(
            source=SearchSource.ENSEMBL,
            id=gid,
            title=display,
            url=f"https://plants.ensembl.org/Glycine_max/Gene/Summary?g={gid}",
            snippet=(desc + (" | " if desc and bits else "") + ", ".join(bits))[:240],
            extra={
                "biotype": biotype,
                "seq_region": doc.get("seq_region_name", ""),
                "start": doc.get("start"),
                "end": doc.get("end"),
                "strand": doc.get("strand"),
            },
        )
