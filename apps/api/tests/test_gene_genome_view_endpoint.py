"""Pre-rendered genome-view endpoint: window maths, caching and input guards.

These are unit tests on purpose. The endpoint's value is its *contract* — a
cacheable image with a correct window — and that contract is fully exercised by
calling the handler with the repository layer stubbed out. The repository
behaviour it depends on is covered by the gene and preview suites, which need a
real PostgreSQL and therefore Docker.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.api.v1 import genes as genes_module
from app.schemas.genomic import GeneDetail, Strand, TranscriptResponse


class _FakeRequest:
    """Only `headers.get` is used by the handler."""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}


def _gene(**overrides: Any) -> GeneDetail:
    payload: dict[str, Any] = {
        "gene_id": "Glyma.01G066600.Wm82.a6.v1",
        "assembly_name": "Gmax_880_v6.0",
        "chromosome": "Gm01",
        "start": 10685338,
        "end": 10694003,
        "start_pos": 10685338,
        "end_pos": 10694003,
        "strand": Strand.PLUS,
    }
    payload.update(overrides)
    return GeneDetail(**payload)


@pytest.fixture
def stub_gene(monkeypatch: pytest.MonkeyPatch):
    """Replace the repository layer; no database is involved."""

    def install(gene: GeneDetail, sites: list[Any] | None = None) -> None:
        async def fake_get_gene(*_args: Any, **_kwargs: Any) -> GeneDetail:
            return gene

        async def fake_sites(*_args: Any, **_kwargs: Any) -> list[Any]:
            return sites or []

        monkeypatch.setattr(genes_module.service, "get_gene", fake_get_gene)

        import app.services.local_test_preview_service as preview

        monkeypatch.setattr(preview, "list_preview_mutation_sites_for_gene", fake_sites)

    return install


async def _call(**overrides: Any):
    kwargs: dict[str, Any] = {
        "gene_id": "Glyma.01G066600.Wm82.a6.v1",
        "request": _FakeRequest(),
        "db": None,
        "release_context": None,
        "assembly_id": None,
        "width": 900,
        "start": None,
        "end": None,
        "include": "all",
    }
    kwargs.update(overrides)
    return await genes_module.get_gene_genome_view(**kwargs)


async def test_serves_svg_with_cache_headers(stub_gene) -> None:
    stub_gene(_gene())
    response = await _call()

    assert response.status_code == 200
    assert response.media_type == "image/svg+xml"
    assert response.headers["cache-control"] == genes_module.GENOME_VIEW_CACHE_CONTROL
    assert response.headers["x-content-type-options"] == "nosniff"
    # The picture must never be treated as a document by a browser.
    assert "sandbox" in response.headers["content-security-policy"]
    body = response.body.decode("utf-8")
    assert body.startswith("<svg")
    assert body.endswith("</svg>")


async def test_default_window_pads_the_gene_by_a_quarter_span(stub_gene) -> None:
    """The window must frame the gene rather than cut at its edges."""
    gene = _gene()
    stub_gene(gene)
    response = await _call()

    span = gene.end_pos - gene.start_pos
    expected_flank = int(span * genes_module.GENOME_VIEW_FLANK_FRACTION + 0.5)
    start = gene.start_pos - expected_flank
    end = gene.end_pos + expected_flank

    body = response.body.decode("utf-8")
    label = f"Gm01:{start:,}-{end:,}"
    assert label in body, f"expected aria-label window {label}"


async def test_explicit_window_overrides_the_default(stub_gene) -> None:
    stub_gene(_gene())
    response = await _call(start=10690000, end=10691000)

    body = response.body.decode("utf-8")
    assert "Gm01:10,690,000-10,691,000" in body


async def test_inverted_window_is_rejected(stub_gene) -> None:
    stub_gene(_gene())
    with pytest.raises(Exception) as excinfo:
        await _call(start=2000, end=1000)
    assert getattr(excinfo.value, "status_code", None) == 422


async def test_etag_short_circuits_to_304(stub_gene) -> None:
    """A repeat visitor must get a 304 instead of a re-rendered picture."""
    stub_gene(_gene())
    first = await _call()
    etag = first.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"')

    second = await _call(request=_FakeRequest({"if-none-match": etag}))
    assert second.status_code == 304
    assert second.headers["etag"] == etag


async def test_etag_changes_with_the_window(stub_gene) -> None:
    stub_gene(_gene())
    a = await _call()
    b = await _call(start=10690000, end=10692000)
    assert a.headers["etag"] != b.headers["etag"]


async def test_track_selection_is_honoured(stub_gene) -> None:
    stub_gene(_gene())
    gene_only = (await _call(include="gene")).body.decode("utf-8")
    sites_only = (await _call(include="sites")).body.decode("utf-8")

    assert "Mutation sites" not in gene_only
    assert "Mutation sites" in sites_only
    assert "Glyma.01G066600.Wm82.a6.v1 (+)" not in sites_only
    assert "Glyma.01G066600.Wm82.a6.v1 (+)" in gene_only


async def test_transcripts_get_their_own_lane_only_when_plural(stub_gene) -> None:
    transcripts = [
        TranscriptResponse(
            id="T1", gene_id="Glyma.01G066600.Wm82.a6.v1", name="T1",
            start=10685338, end=10694003, strand=Strand.PLUS, is_canonical=True,
        ),
        TranscriptResponse(
            id="T2", gene_id="Glyma.01G066600.Wm82.a6.v1", name="T2",
            start=10686000, end=10693000, strand=Strand.PLUS,
        ),
    ]
    stub_gene(_gene(transcripts=transcripts))
    body = (await _call()).body.decode("utf-8")
    assert "转录本" in body

    stub_gene(_gene(transcripts=transcripts[:1]))
    single = (await _call()).body.decode("utf-8")
    assert "转录本" not in single


async def test_render_failure_to_load_sites_still_serves_the_gene(stub_gene, monkeypatch) -> None:
    """An absent preview dataset must not cost the user the gene body."""
    stub_gene(_gene())

    import app.services.local_test_preview_service as preview

    async def boom(*_args: Any, **_kwargs: Any):
        raise RuntimeError("preview dataset not imported")

    monkeypatch.setattr(preview, "list_preview_mutation_sites_for_gene", boom)

    response = await _call()
    assert response.status_code == 200
    body = response.body.decode("utf-8")
    assert "Glyma.01G066600.Wm82.a6.v1" in body


async def test_hostile_gene_label_cannot_escape_the_svg(stub_gene) -> None:
    """Escaping is a security boundary, not cosmetics."""
    stub_gene(_gene(gene_id='</svg><script>alert(1)</script>'))
    body = (await _call()).body.decode("utf-8")

    assert "<script>" not in body
    assert "&lt;/svg&gt;" in body
