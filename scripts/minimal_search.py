"""Run a loopback-only, read-only search preview for local unpublished test data.

The service deliberately reads the supplied reference and annotation files in
place. It creates no database, does not write to the source directory, and does
not publish these records. TSV rows are test sites, not complete variants.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

ASSEMBLY = "Gmax_880_v6.0"
ANNOTATION = "Wm82.a6.v1"
PUBLICATION_STATUS = "unpublished_test_data"
MAX_PAGE_SIZE = 100
MAX_PAGE = 1_000_000
MAX_QUERY_LENGTH = 256

TSV_COLUMNS = {
    "line_id": "株系",
    "test_site_id": "突变体系（株系母+位置）",
    "chromosome": "染色体号",
    "position": "位点",
    "confidence": "可信度（高/中/低）",
    "gene_id": "基因号",
    "feature": "特征",
    "available": "可获得",
}


class DatasetError(ValueError):
    """An input file is malformed or inconsistent with the other source files."""


@dataclass(frozen=True)
class Gene:
    gene_id: str
    name: str
    chromosome: str
    start: int
    end: int
    strand: str


@dataclass(frozen=True)
class TestSite:
    source_row: int
    test_site_id: str
    line_id: str
    chromosome: str
    position: int
    confidence: str
    gene_id: str
    feature: str
    available: bool
    gene_start: int
    gene_end: int
    gene_span_relation: str


def _parse_attributes(raw: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for item in raw.split(";"):
        if not item:
            continue
        key, separator, value = item.partition("=")
        if not separator or not key or key in attributes:
            raise DatasetError("Malformed or duplicate GFF3 attribute")
        # Gene identifiers in this source are plain ASCII. Rejecting malformed
        # encodings is safer than silently changing an identity during decoding.
        attributes[key] = value
    return attributes


def _read_fai(path: Path) -> dict[str, int]:
    chromosomes: dict[str, int] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            fields = raw.rstrip("\r\n").split("\t")
            if len(fields) < 5 or not fields[0]:
                raise DatasetError(f"{path.name}:{line_number}: expected a five-column FAI row")
            name = fields[0]
            if name in chromosomes:
                raise DatasetError(f"{path.name}:{line_number}: duplicate sequence name {name}")
            try:
                length, offset, line_bases, line_width = map(int, fields[1:5])
            except ValueError as exc:
                raise DatasetError(f"{path.name}:{line_number}: non-integer FAI field") from exc
            if length < 1 or offset < 0 or line_bases < 1 or line_width < line_bases:
                raise DatasetError(f"{path.name}:{line_number}: invalid FAI dimensions")
            chromosomes[name] = length
    if not chromosomes:
        raise DatasetError(f"{path.name}: no reference sequences found")
    return chromosomes


def _read_genes(path: Path, chromosomes: dict[str, int]) -> tuple[list[Gene], dict[str, Gene]]:
    genes: list[Gene] = []
    genes_by_id: dict[str, Gene] = {}
    assembly_version: str | None = None
    annotation_version: str | None = None
    with path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if raw.startswith("##assembly-version "):
                value = raw.rstrip("\r\n").partition(" ")[2]
                if assembly_version is not None and assembly_version != value:
                    raise DatasetError(f"{path.name}:{line_number}: conflicting assembly version")
                assembly_version = value
                continue
            if raw.startswith("##annot-version "):
                value = raw.rstrip("\r\n").partition(" ")[2]
                if annotation_version is not None and annotation_version != value:
                    raise DatasetError(f"{path.name}:{line_number}: conflicting annotation version")
                annotation_version = value
                continue
            if raw.startswith("#") or not raw.strip():
                continue
            fields = raw.rstrip("\r\n").split("\t")
            if len(fields) != 9:
                raise DatasetError(f"{path.name}:{line_number}: expected nine GFF3 fields")
            chromosome, _source, feature_type, start_raw, end_raw, _score, strand, _phase, raw_attrs = fields
            if chromosome not in chromosomes:
                raise DatasetError(
                    f"{path.name}:{line_number}: sequence {chromosome!r} is absent from the FAI"
                )
            try:
                start, end = int(start_raw), int(end_raw)
            except ValueError as exc:
                raise DatasetError(f"{path.name}:{line_number}: non-integer GFF3 coordinates") from exc
            if not 1 <= start <= end <= chromosomes[chromosome]:
                raise DatasetError(f"{path.name}:{line_number}: coordinates outside {chromosome}")
            if feature_type != "gene":
                continue
            attributes = _parse_attributes(raw_attrs)
            gene_id = attributes.get("ID", "").strip()
            if not gene_id:
                raise DatasetError(f"{path.name}:{line_number}: gene feature has no ID attribute")
            if gene_id in genes_by_id:
                raise DatasetError(f"{path.name}:{line_number}: duplicate gene ID {gene_id}")
            if strand not in {"+", "-", ".", "?"}:
                raise DatasetError(f"{path.name}:{line_number}: invalid gene strand")
            gene = Gene(
                gene_id=gene_id,
                name=attributes.get("Name", gene_id),
                chromosome=chromosome,
                start=start,
                end=end,
                strand=strand,
            )
            genes.append(gene)
            genes_by_id[gene_id] = gene
    if assembly_version != "v6.0" or annotation_version != ANNOTATION:
        raise DatasetError(
            f"{path.name}: expected ##assembly-version v6.0 and ##annot-version {ANNOTATION}"
        )
    if not genes:
        raise DatasetError(f"{path.name}: no gene features found")
    return genes, genes_by_id


def _read_test_sites(
    path: Path,
    chromosomes: dict[str, int],
    genes_by_id: dict[str, Gene],
) -> list[TestSite]:
    sites: list[TestSite] = []
    seen_site_ids: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        headers = reader.fieldnames or []
        missing = [column for column in TSV_COLUMNS.values() if column not in headers]
        if missing:
            raise DatasetError(f"{path.name}: missing TSV columns: {', '.join(missing)}")
        for source_row, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise DatasetError(f"{path.name}:{source_row}: row width does not match the header")
            line_id = row[TSV_COLUMNS["line_id"]].strip()
            site_id = row[TSV_COLUMNS["test_site_id"]].strip()
            chromosome = row[TSV_COLUMNS["chromosome"]].strip()
            gene_id = row[TSV_COLUMNS["gene_id"]].strip()
            feature = row[TSV_COLUMNS["feature"]].strip()
            confidence = row[TSV_COLUMNS["confidence"]].strip()
            availability = row[TSV_COLUMNS["available"]].strip()
            position_raw = row[TSV_COLUMNS["position"]].strip()

            if not line_id or not site_id or not gene_id or not feature:
                raise DatasetError(f"{path.name}:{source_row}: line, test-site, gene and feature are required")
            if site_id in seen_site_ids:
                raise DatasetError(f"{path.name}:{source_row}: duplicate test-site ID {site_id}")
            seen_site_ids.add(site_id)
            if chromosome not in chromosomes:
                raise DatasetError(f"{path.name}:{source_row}: chromosome {chromosome!r} is absent from FAI")
            try:
                position = int(position_raw)
            except ValueError as exc:
                raise DatasetError(f"{path.name}:{source_row}: position is not an integer") from exc
            if not 1 <= position <= chromosomes[chromosome]:
                raise DatasetError(f"{path.name}:{source_row}: position is outside {chromosome}")
            if confidence not in {"H", "M", "L"}:
                raise DatasetError(f"{path.name}:{source_row}: confidence must be H, M or L")
            if availability not in {"Y", "N"}:
                raise DatasetError(f"{path.name}:{source_row}: availability must be Y or N")
            gene = genes_by_id.get(gene_id)
            if gene is None:
                raise DatasetError(
                    f"{path.name}:{source_row}: gene ID {gene_id!r} has no exact GFF3 match"
                )
            if gene.chromosome != chromosome:
                raise DatasetError(
                    f"{path.name}:{source_row}: {gene_id} is on {gene.chromosome}, not {chromosome}"
                )
            # The feature column may describe a nearby/upstream/downstream site.
            # Coordinates outside the gene span are therefore valid when the
            # sequence and same-assembly gene annotation checks above pass.
            sites.append(
                TestSite(
                    source_row=source_row,
                    test_site_id=site_id,
                    line_id=line_id,
                    chromosome=chromosome,
                    position=position,
                    confidence=confidence,
                    gene_id=gene_id,
                    feature=feature,
                    available=availability == "Y",
                    gene_start=gene.start,
                    gene_end=gene.end,
                    gene_span_relation=(
                        "within_annotated_gene_span"
                        if gene.start <= position <= gene.end
                        else "outside_annotated_gene_span"
                    ),
                )
            )
    if not sites:
        raise DatasetError(f"{path.name}: no test-site rows found")
    return sites


class SearchIndex:
    """In-memory index over the supplied read-only annotation and test-site files."""

    def __init__(self, data_dir: Path):
        annotation_dir = data_dir / "01_annot"
        mutation_path = data_dir / "02_mut-infor" / "mu-infor_Gmax_880_Wm82-test.txt"
        gff_path = annotation_dir / "Gmax_880_Wm82.a6.v1.gene.gff3"
        fai_path = annotation_dir / "Gmax_880_v6.0.fa.fai"
        absent = [path.name for path in (mutation_path, gff_path, fai_path) if not path.is_file()]
        if absent:
            raise DatasetError(f"Required source file(s) missing: {', '.join(absent)}")

        self.source_files = {
            "reference_index": fai_path.name,
            "gene_annotation": gff_path.name,
            "test_sites": mutation_path.name,
        }
        self.chromosome_lengths = _read_fai(fai_path)
        self.genes, self.genes_by_id = _read_genes(gff_path, self.chromosome_lengths)
        self.test_sites = _read_test_sites(mutation_path, self.chromosome_lengths, self.genes_by_id)
        chromosome_order = {name: index for index, name in enumerate(self.chromosome_lengths)}
        self.genes.sort(key=lambda gene: (chromosome_order[gene.chromosome], gene.start, gene.gene_id))
        self.test_sites.sort(
            key=lambda site: (chromosome_order[site.chromosome], site.position, site.source_row)
        )

    def search_genes(
        self,
        query: str,
        chromosome: str,
        start: int | None,
        end: int | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        folded = query.casefold()
        matches = [
            gene
            for gene in self.genes
            if (not chromosome or gene.chromosome == chromosome)
            and (not folded or folded in gene.gene_id.casefold() or folded in gene.name.casefold())
            and (start is None or gene.end >= start)
            and (end is None or gene.start <= end)
        ]
        return _page(matches, page, page_size)

    def search_test_sites(
        self,
        chromosome: str,
        start: int,
        end: int,
        gene_id: str,
        line_id: str,
        confidence: str,
        available: str,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        folded_gene = gene_id.casefold()
        folded_line = line_id.casefold()
        matches = [
            site
            for site in self.test_sites
            if site.chromosome == chromosome
            and start <= site.position <= end
            and (not folded_gene or folded_gene in site.gene_id.casefold())
            and (not folded_line or folded_line in site.line_id.casefold())
            and (not confidence or site.confidence == confidence)
            and (not available or site.available == (available == "Y"))
        ]
        return _page(matches, page, page_size)


def _page(items: list[Any], page: int, page_size: int) -> dict[str, Any]:
    offset = (page - 1) * page_size
    return {
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "total_pages": (len(items) + page_size - 1) // page_size,
        "items": [asdict(item) for item in items[offset : offset + page_size]],
    }


PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SoyMutDB 本地测试检索</title>
<style>
:root{font:16px/1.55 system-ui,sans-serif;color:#17372b;background:#f6f8f5}body{max-width:1100px;margin:2rem auto;padding:0 1rem}
header,section,.provenance{background:white;border:1px solid #d6e0d9;border-radius:12px;padding:1rem 1.25rem;margin:1rem 0}
h1,h2{margin:.2rem 0 .6rem}h1{color:#176343}.badge{display:inline-block;background:#fff0d0;color:#684700;padding:.15rem .55rem;border-radius:999px;font-weight:600}
form{display:flex;gap:.55rem;flex-wrap:wrap;align-items:center;margin:.8rem 0}input,select,button{font:inherit;padding:.55rem .65rem;border:1px solid #aebdb4;border-radius:7px;background:white}button{background:#176343;color:white;border-color:#176343;cursor:pointer}button:disabled{opacity:.45;cursor:default}
.help,.meta{color:#4d6257}.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.35rem 1rem}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;background:white}th,td{padding:.55rem .65rem;border-bottom:1px solid #e0e7e2;text-align:left;white-space:nowrap}th{background:#edf3ef}#status{min-height:1.6em;font-weight:600}nav{display:flex;align-items:center;gap:.6rem;margin:.8rem 0}.sources{overflow-wrap:anywhere}
</style></head><body>
<header><h1>SoyMutDB 本地检索</h1><span class="badge">未发布 · 测试数据</span>
<p>参考组装 <strong id="assembly">Gmax_880_v6.0</strong>；基因注释 <strong id="annotation">Wm82.a6.v1</strong>。本页面只展示测试文件中的基因注释和测试位点，不代表已发布公共记录。</p>
<p class="help">位点文件没有 REF/ALT 等位信息，结果不是完整变异记录。所有输入文件以只读方式加载。</p>
<div class="meta" id="meta"></div></header>
<section><h2>基因 ID 检索</h2><form id="gene-form">
<label>基因 ID 或名称 <input name="query" maxlength="256" placeholder="Glyma.01G000100.Wm82.a6.v1" aria-label="基因 ID 或名称"></label>
<label>染色体 <select name="chromosome" aria-label="染色体"><option value="">全部</option></select></label>
<label>起点 <input name="start" type="number" min="1" aria-label="基因起点筛选"></label><label>终点 <input name="end" type="number" min="1" aria-label="基因终点筛选"></label>
<button type="submit">检索基因</button></form></section>
<section><h2>物理位置检索</h2><p class="help">检索 TSV 测试位点，可按基因 ID、株系、可信度和可获得状态筛选。GFF3 基因跨度外的邻近位点按源文件原注释保留。</p>
<form id="site-form">
<label>染色体 <select name="chromosome" required aria-label="染色体"><option value="">选择染色体</option></select></label>
<label>起点 <input name="start" type="number" min="1" required aria-label="位置起点"></label><label>终点 <input name="end" type="number" min="1" required aria-label="位置终点"></label>
<label>基因 ID <input name="gene_id" maxlength="256" aria-label="位点基因 ID"></label><label>株系 <input name="line_id" maxlength="256" aria-label="株系"></label>
<label>可信度 <select name="confidence" aria-label="可信度"><option value="">全部</option><option value="H">H</option><option value="M">M</option><option value="L">L</option></select></label>
<label>可获得 <select name="available" aria-label="可获得"><option value="">全部</option><option value="Y">是</option><option value="N">否</option></select></label>
<button type="submit">检索测试位点</button></form></section>
<p id="status" role="status" aria-live="polite"></p><div class="table-wrap"><table id="results"></table></div><nav id="pages" aria-label="结果分页"></nav>
<section class="provenance"><h2>来源与口径</h2><p id="sources" class="sources"></p><p>坐标按 1-based inclusive（起止位置均包含）解释。基因 ID、染色体和坐标在启动时与同一组装版本的 GFF3/FAI 交叉检查。若 ID 缺失、染色体不符或坐标超出参考序列，服务拒绝启动并报告 TSV 行号。位点不要求落在所标注基因区间内；结果会标出是否在该区间内，并保留 TSV 的原始 gene_id 和 feature，不自动重分配基因。</p></section>
<script src="/app.js" defer></script></body></html>"""


APP_JS = r"""'use strict';
const byId = id => document.getElementById(id);
const state = { kind: null, params: null, page: 1, pageSize: 20 };
const labels = {
  genes: [['gene_id','基因 ID'],['name','名称'],['chromosome','染色体'],['start','起点'],['end','终点'],['strand','链']],
  sites: [['test_site_id','测试位点 ID'],['line_id','株系'],['chromosome','染色体'],['position','位置'],['confidence','可信度'],['gene_id','基因 ID'],['feature','源特征'],['gene_start','基因起点'],['gene_end','基因终点'],['gene_span_relation','相对标注基因区间'],['available','可获得'],['source_row','TSV 行号']]
};
function addCell(row, text, heading=false) {
  const cell = document.createElement(heading ? 'th' : 'td');
  cell.textContent = String(text ?? '');
  row.append(cell);
}
function displayValue(key, value) {
  if (key === 'available') return value ? '是' : '否';
  if (key === 'gene_span_relation') return value === 'within_annotated_gene_span' ? '位于区间内' : '位于所标注基因区间外';
  return value;
}
function setStatus(message) { byId('status').textContent = message; }
async function loadMeta() {
  const response = await fetch('/api/meta');
  if (!response.ok) throw new Error('元数据加载失败');
  const meta = await response.json();
  byId('assembly').textContent = meta.assembly;
  byId('annotation').textContent = meta.annotation;
  const summary = document.createDocumentFragment();
  for (const [label, value] of [['基因数',meta.gene_count],['测试位点数',meta.test_site_count],['参考序列数',meta.chromosomes.length],['状态',meta.publication_status]]) {
    const item = document.createElement('div'); item.textContent = `${label}：${value}`; summary.append(item);
  }
  byId('meta').replaceChildren(summary);
  for (const select of document.querySelectorAll('select[name="chromosome"]')) {
    for (const chromosome of meta.chromosomes) {
      const option = document.createElement('option'); option.value = chromosome.name;
      option.textContent = `${chromosome.name} (${chromosome.length.toLocaleString()} bp)`; select.append(option);
    }
  }
  byId('sources').textContent = '文件：' + Object.values(meta.source_files).join('；');
}
async function search() {
  if (!state.kind) return;
  const params = new URLSearchParams(state.params);
  params.set('page', String(state.page)); params.set('page_size', String(state.pageSize));
  try {
    const response = await fetch(`/api/${state.kind}?${params}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || '检索失败');
    const table = byId('results');
    const heading = document.createElement('tr');
    for (const [key, label] of labels[state.kind]) addCell(heading, label, true);
    table.replaceChildren(heading);
    for (const item of payload.items) {
      const row = document.createElement('tr');
      for (const [key] of labels[state.kind]) addCell(row, displayValue(key, item[key]));
      table.append(row);
    }
    setStatus(`共 ${payload.total} 条，第 ${payload.page} / ${payload.total_pages || 1} 页`);
    const nav = byId('pages'); nav.replaceChildren();
    const previous = document.createElement('button'); previous.type = 'button'; previous.textContent = '上一页';
    previous.disabled = payload.page <= 1; previous.addEventListener('click', () => { state.page--; search(); });
    const next = document.createElement('button'); next.type = 'button'; next.textContent = '下一页';
    next.disabled = payload.page >= payload.total_pages; next.addEventListener('click', () => { state.page++; search(); });
    nav.append(previous, next);
  } catch (error) { setStatus(error.message); }
}
function formParams(form, requiredRange) {
  const values = new FormData(form), params = {};
  for (const [key, raw] of values) { const value = String(raw).trim(); if (value) params[key] = value; }
  if (requiredRange && (!params.start || !params.end)) throw new Error('请填写起点和终点');
  if (params.start && params.end && Number(params.end) < Number(params.start)) throw new Error('终点必须不小于起点');
  if (requiredRange && !params.chromosome) throw new Error('选择染色体后再填写物理位置范围');
  if (!requiredRange && (params.start || params.end) && !params.chromosome) throw new Error('基因坐标筛选需要先选择染色体');
  return params;
}
byId('gene-form').addEventListener('submit', event => {
  event.preventDefault();
  try { state.kind = 'genes'; state.params = formParams(event.currentTarget, false); state.page = 1; search(); }
  catch (error) { setStatus(error.message); }
});
byId('site-form').addEventListener('submit', event => {
  event.preventDefault();
  try { state.kind = 'test-sites'; state.params = formParams(event.currentTarget, true); state.page = 1; search(); }
  catch (error) { setStatus(error.message); }
});
loadMeta().catch(error => setStatus(error.message));
"""


SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def make_handler(index: SearchIndex) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "SoyMutDBLocalSearch"
        sys_version = ""

        def log_message(self, _format: str, *_args: Any) -> None:
            # Do not write raw queries to a log; parameters are user supplied.
            return

        def do_GET(self) -> None:
            if len(self.path) > 8192:
                self._json(414, {"error": "Request URL is too long"})
                return
            url = urlsplit(self.path)
            if url.path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            if url.path == "/app.js":
                self._send(200, APP_JS.encode("utf-8"), "text/javascript; charset=utf-8")
                return
            if url.path not in {"/api/meta", "/api/genes", "/api/test-sites"}:
                self._json(404, {"error": "Not found"})
                return
            try:
                params = self._parse_params(url.query)
                if url.path == "/api/meta":
                    self._require_params(params, set())
                    payload = {
                        "assembly": ASSEMBLY,
                        "annotation": ANNOTATION,
                        "coordinate_system": "1-based-inclusive",
                        "publication_status": PUBLICATION_STATUS,
                        "record_kind": "test_site",
                        "has_ref_alt": False,
                        "source_files": index.source_files,
                        "chromosomes": [
                            {"name": name, "length": length}
                            for name, length in index.chromosome_lengths.items()
                        ],
                        "gene_count": len(index.genes),
                        "test_site_count": len(index.test_sites),
                    }
                elif url.path == "/api/genes":
                    self._require_params(params, {"query", "chromosome", "start", "end", "page", "page_size"})
                    query = self._text_param(params, "query")
                    chromosome = self._chromosome_param(params, index, optional=True)
                    start, end = self._range_params(params, index, chromosome, optional=True)
                    page, page_size = self._page_params(params)
                    payload = index.search_genes(query, chromosome, start, end, page, page_size)
                else:
                    self._require_params(
                        params,
                        {"chromosome", "start", "end", "gene_id", "line_id", "confidence", "available", "page", "page_size"},
                    )
                    chromosome = self._chromosome_param(params, index, optional=False)
                    start, end = self._range_params(params, index, chromosome, optional=False)
                    page, page_size = self._page_params(params)
                    gene_id = self._text_param(params, "gene_id")
                    line_id = self._text_param(params, "line_id")
                    confidence = self._enum_param(params, "confidence", {"H", "M", "L"})
                    available = self._enum_param(params, "available", {"Y", "N"})
                    payload = index.search_test_sites(
                        chromosome, start, end, gene_id, line_id, confidence, available, page, page_size
                    )
                payload.update(
                    assembly=ASSEMBLY,
                    annotation=ANNOTATION,
                    coordinate_system="1-based-inclusive",
                    publication_status=PUBLICATION_STATUS,
                )
                self._json(200, payload)
            except (ValueError, OverflowError) as exc:
                self._json(400, {"error": str(exc)})

        def do_POST(self) -> None:
            self._json(405, {"error": "Method not allowed"}, extra_headers={"Allow": "GET"})

        def do_PUT(self) -> None:
            self.do_POST()

        def do_DELETE(self) -> None:
            self.do_POST()

        def do_OPTIONS(self) -> None:
            self.do_POST()

        def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
            safe_messages = {400: "Bad request", 501: "Method not implemented"}
            self._json(code, {"error": safe_messages.get(code, "Request rejected")})

        def _parse_params(self, query: str) -> dict[str, str]:
            try:
                parsed = parse_qs(query, keep_blank_values=True, strict_parsing=True, max_num_fields=20)
            except ValueError as exc:
                raise ValueError("Malformed query parameters") from exc
            if any(len(values) != 1 for values in parsed.values()):
                raise ValueError("Each query parameter may appear only once")
            return {key: values[0] for key, values in parsed.items()}

        @staticmethod
        def _require_params(params: dict[str, str], allowed: set[str]) -> None:
            unknown = set(params) - allowed
            if unknown:
                raise ValueError("Unknown query parameter")

        @staticmethod
        def _text_param(params: dict[str, str], name: str) -> str:
            value = params.get(name, "").strip()
            if len(value) > MAX_QUERY_LENGTH or any(ord(char) < 32 for char in value):
                raise ValueError(f"Invalid {name}")
            return value

        @staticmethod
        def _enum_param(params: dict[str, str], name: str, allowed: set[str]) -> str:
            value = params.get(name, "").strip()
            if value and value not in allowed:
                raise ValueError(f"Invalid {name}")
            return value

        @staticmethod
        def _chromosome_param(
            params: dict[str, str], index: SearchIndex, optional: bool
        ) -> str:
            value = params.get("chromosome", "").strip()
            if not value and optional:
                return ""
            if value not in index.chromosome_lengths:
                raise ValueError("Unknown chromosome")
            return value

        @staticmethod
        def _page_params(params: dict[str, str]) -> tuple[int, int]:
            def read(name: str, default: str) -> int:
                raw = params.get(name, default)
                if not re.fullmatch(r"[0-9]+", raw):
                    raise ValueError(f"Invalid {name}")
                return int(raw)

            page = read("page", "1")
            page_size = read("page_size", "20")
            if not 1 <= page <= MAX_PAGE or not 1 <= page_size <= MAX_PAGE_SIZE:
                raise ValueError("page must be 1..1000000 and page_size must be 1..100")
            return page, page_size

        @staticmethod
        def _range_params(
            params: dict[str, str], index: SearchIndex, chromosome: str, optional: bool
        ) -> tuple[int | None, int | None]:
            start_raw, end_raw = params.get("start", ""), params.get("end", "")
            if optional and not start_raw and not end_raw:
                return None, None
            if not start_raw or not end_raw:
                raise ValueError("Both start and end are required")
            if not chromosome:
                raise ValueError("A chromosome is required with start and end")
            if not re.fullmatch(r"[0-9]+", start_raw) or not re.fullmatch(r"[0-9]+", end_raw):
                raise ValueError("Coordinates must be positive integers")
            start, end = int(start_raw), int(end_raw)
            if start < 1 or end < start:
                raise ValueError("Invalid coordinate range")
            if end > index.chromosome_lengths[chromosome]:
                raise ValueError("Coordinate exceeds chromosome length")
            return start, end

        def _json(
            self, status: int, value: dict[str, Any], extra_headers: dict[str, str] | None = None
        ) -> None:
            self._send(
                status,
                json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                "application/json; charset=utf-8",
                extra_headers,
            )

        def _send(
            self,
            status: int,
            body: bytes,
            content_type: str,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in SECURITY_HEADERS.items():
                self.send_header(name, value)
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True, help="directory containing 01_annot and 02_mut-infor")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    try:
        index = SearchIndex(args.data_dir)
    except (OSError, UnicodeError, csv.Error, DatasetError) as exc:
        print(f"Dataset validation failed: {exc}", file=sys.stderr)
        return 2

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(index))
    server.daemon_threads = True
    host, port = server.server_address[:2]
    print(
        f"Loaded {len(index.genes):,} genes and {len(index.test_sites):,} test sites; "
        f"{ASSEMBLY} / {ANNOTATION}; {PUBLICATION_STATUS}; http://{host}:{port}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping local test search service.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
