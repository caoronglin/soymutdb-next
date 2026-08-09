"""Tests for the shared dominate-based :mod:`html_report` builder and its
consumers (SSG gene pages, GWAS Manhattan/QQ report).

Covers:

- :class:`HTMLReport` structure: doctype, single title, inline CSS,
  escaping of dynamic text,
- table rendering (headers, rows, ``None`` cells, empty-state),
- :func:`embed_json` script-injection safety,
- ``static_pages._render_gene_html`` and ``gwas.render_report_html`` output
  parseability (``html.parser``) with the expected key nodes.
"""

from __future__ import annotations

import html.parser
from typing import Any

from dominate.tags import em

from soymutdb_worker.tasks import gwas as gwas_module
from soymutdb_worker.tasks.static_pages import _render_gene_html
from soymutdb_worker.utils.html_report import HTMLReport, embed_json


class _NodeCollector(html.parser.HTMLParser):
    """Collect tags, ids and decoded text from an HTML document."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.ids: list[str] = []
        self.texts: list[str] = []
        self._skip_text = 0  # >0 inside <style>/<script> raw-text elements

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        attr_map = dict(attrs)
        if "id" in attr_map and attr_map["id"] is not None:
            self.ids.append(attr_map["id"])
        if tag in {"style", "script"}:
            self._skip_text += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"} and self._skip_text > 0:
            self._skip_text -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_text == 0:
            self.texts.append(data)


def _parse(html_str: str) -> _NodeCollector:
    collector = _NodeCollector()
    collector.feed(html_str)
    return collector


# ---------------------------------------------------------------------------
# HTMLReport basics
# ---------------------------------------------------------------------------


def test_report_has_doctype_and_single_title() -> None:
    report = HTMLReport("My <report>")
    out = report.render()
    assert out.startswith("<!DOCTYPE html>")
    assert out.count("<title>") == 1
    assert "My &lt;report&gt;" in out
    assert out.count("</title>") == 1


def test_report_inlines_default_css() -> None:
    out = HTMLReport("t").render()
    assert "<style>" in out and "</style>" in out
    # CSS must not be HTML-entity-escaped (style is a raw-text element).
    assert "HarmonyOS Sans SC" in out
    assert "&quot;" not in out


def test_report_escapes_dynamic_text() -> None:
    report = HTMLReport("t")
    report.add_heading("a <b> & 'c'")
    report.add_paragraph("<script>alert(1)</script>")
    out = report.render()
    assert "a &lt;b&gt; &amp; 'c'" in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    # No raw dynamic markup leaked into the body.
    assert "alert(1)</script>" not in out


def test_report_custom_css_override() -> None:
    out = HTMLReport("t", css="body { color: red; }").render()
    assert "body { color: red; }" in out
    assert "HarmonyOS" not in out


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def test_table_renders_headers_rows_and_none_cells() -> None:
    report = HTMLReport("t")
    report.add_table(["A", "B"], [[1, None], ["<x>", 2.5]])
    out = report.render()
    assert "<th>A</th>" in out and "<th>B</th>" in out
    assert "<td>1</td>" in out
    assert "<td>—</td>" in out  # None placeholder
    assert "<td>&lt;x&gt;</td>" in out


def test_table_empty_renders_empty_state() -> None:
    report = HTMLReport("t")
    result = report.add_table(["A"], [], empty_text="No data available.")
    assert result is None
    out = report.render()
    assert "No data available." in out
    assert "<table" not in out


def test_table_accepts_dominate_tag_cells() -> None:
    report = HTMLReport("t")
    report.add_table(["Species"], [[em("G. max")]])
    out = report.render()
    # dominate pretty-prints nested tags across lines.
    assert "<em>G. max</em>" in out


# ---------------------------------------------------------------------------
# Chart containers / footer
# ---------------------------------------------------------------------------


def test_chart_div_and_footer() -> None:
    report = HTMLReport("t")
    report.add_chart_div("manhattan")
    report.add_footer()
    out = report.render()
    assert '<div class="plot" id="manhattan"></div>' in out
    assert "<footer>" in out
    assert "SoyMutDB — Soybean Mutation Database" in out


def test_header_brand_and_back_link() -> None:
    report = HTMLReport("t")
    report.add_header()
    out = report.render()
    assert "<header>" in out
    assert 'href="https://soymutdb.com/"' in out
    assert 'class="back-link"' in out


# ---------------------------------------------------------------------------
# embed_json safety
# ---------------------------------------------------------------------------


def test_embed_json_neutralises_script_close() -> None:
    payload = {"snp": '</script><script>alert(1)</script>', "p": 0.01}
    embedded = embed_json(payload)
    assert "</script>" not in embedded
    assert embedded.count("<") == 0
    # Round-trips to the original JS value.
    import json

    assert json.loads(embedded)["snp"] == payload["snp"]


def test_embed_json_keeps_plain_data() -> None:
    assert '"chromosomes"' in embed_json({"chromosomes": ["1", "2"]})


# ---------------------------------------------------------------------------
# SSG gene page (static_pages)
# ---------------------------------------------------------------------------


def _gene_info(description: str = "A <description>") -> dict[str, Any]:
    return {
        "gene_id": "Glyma.01G000100",
        "gene_name": "geneA",
        "biotype": "protein_coding",
        "chromosome": "Gm01",
        "start": 1234,
        "end": 5678,
        "strand": "+",
        "description": description,
    }


def test_gene_html_has_expected_structure() -> None:
    html_str = _render_gene_html(
        gene_info=_gene_info(),
        expressions=[
            {"library_name": "lib<1>", "tissue": "leaf", "treatment": None,
             "fpkm": 12.34, "tpm": 9.5, "raw_count": 100},
        ],
        total_expression_count=1,
        homologs=[
            {"homolog_species": "Arabidopsis <thaliana>", "homolog_gene_id": "AT1G1",
             "homolog_type": "ortholog", "source": "OMA"},
        ],
        generated_at="2026-08-09T00:00:00+00:00",
    )
    parsed = _parse(html_str)
    # Key structure nodes.
    assert "html" in parsed.tags and "head" in parsed.tags and "body" in parsed.tags
    assert "Glyma.01G000100" in parsed.ids or "Glyma.01G000100" in " ".join(parsed.texts)
    assert "header" in parsed.tags and "footer" in parsed.tags
    # Escaping: dynamic text must be escaped in the raw output.
    assert "&lt;description&gt;" in html_str
    assert "&lt;1&gt;" in html_str
    assert "<em>Arabidopsis &lt;thaliana&gt;</em>" in html_str
    # Empty variant table shows the empty-state text.
    assert "No variant data included in this pre-generated page." in html_str
    # Position line is formatted with comma grouping.
    assert "Gm01:1,234-5,678 (+)" in html_str


def test_gene_html_without_chromosome_uses_dash() -> None:
    info = _gene_info()
    info["chromosome"] = None
    html_str = _render_gene_html(
        gene_info=info,
        expressions=[],
        total_expression_count=0,
        homologs=[],
        generated_at="2026-08-09T00:00:00+00:00",
    )
    assert "—" in html_str
    assert "No expression data available for this gene." in html_str
    assert "No homolog data available for this gene." in html_str


# ---------------------------------------------------------------------------
# GWAS report (gwas)
# ---------------------------------------------------------------------------


def _gwas_rows() -> list[dict]:
    return [
        {"snp": 'snp"<x>', "chr": "1", "pos": 10, "p": 1e-8},
        {"snp": "snp2", "chr": "1", "pos": 20, "p": 0.01},
    ]


def test_gwas_html_has_expected_structure_and_escaped_data() -> None:
    mh = gwas_module.manhattan_data(_gwas_rows())
    qq = gwas_module.qq_data(_gwas_rows())
    html_str = gwas_module.render_report_html(mh, qq, "emmax")

    parsed = _parse(html_str)
    # Chart containers preserved.
    assert "manhattan" in parsed.ids
    assert "qq" in parsed.ids
    # Plotly CDN script still present.
    assert "https://cdn.plot.ly/plotly-2.35.2.min.js" in html_str
    # Data injection preserved, but script-breaking strings neutralised.
    assert "const MANHATTAN = " in html_str
    assert "const QQ = " in html_str
    assert '"chromosomes"' in html_str
    assert "</script>" not in embed_json(mh)
    assert "<x>" not in html_str.replace("\\u003c", "")


def test_gwas_html_does_not_leak_raw_snp_into_script() -> None:
    mh = gwas_module.manhattan_data(_gwas_rows())
    qq = gwas_module.qq_data([])
    html_str = gwas_module.render_report_html(mh, qq, "emmax")
    # The raw `<x>` never appears in the document; `<` is embedded as the
    # JSON escape \u003c so the script block cannot be broken out of.
    assert 'snp"<x>' not in html_str
    assert "\\u003cx>" in html_str


def test_gwas_html_title_and_heading() -> None:
    html_str = gwas_module.render_report_html(
        gwas_module.manhattan_data(_gwas_rows()),
        gwas_module.qq_data(_gwas_rows()),
        "emmax",
    )
    assert "<title>SoyMutDB GWAS report (emmax)</title>" in html_str
    # dominate pretty-prints headings across lines.
    assert "<h1>" in html_str and "GWAS — emmax" in html_str
