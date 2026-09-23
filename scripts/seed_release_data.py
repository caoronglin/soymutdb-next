#!/usr/bin/env python3
"""SoyMutDB Route B —— 受控真实数据种子 loader（解析 + 写入）。

把权威真实数据（FASTA/GFF3/VCF/mutants.tsv）解析为规范化行，并：
  - ``--check``   只解析+校验（真实内容、Demo 标记、计数），不写库；
  - ``--plan``    解析 + 写 seed-manifest.json（逐文件 SHA-256），不写库；
  - ``--emit-sql <DIR>`` 解析并把行生成可回放的 INSERT SQL（PG + CH）到目录；
  - ``--write``   解析并写入 PostgreSQL（asyncpg）+ ClickHouse（clickhouse-connect），
                  绑定 release_id、写 data_sets + provenance + release_data_sets。

红线：不注入任何示例/演示数据。源内容命中 Demo 标记（SMDB-* / Wm82.a4.v1 / legacy
fixture 特征）或格式不符即 fail-closed（exit 2）。本模块只做解析与写入；具体数据源由
CLI 指定（--source-dir）。设计见 docs/ops/route-b-seed-data-design.md。

证据目录：默认 `artifacts/acceptance/data-query/`（gitignored）；QA 约定用
`SOYMUTDB_EVIDENCE_DIR=docs/ops/evidence/`（受跟踪）覆盖，或显式 --manifest-out/--emit-sql。

依赖（可选）：--write 需要 asyncpg（PG）与 clickhouse_connect（CH）；缺依赖时 --write
fail-closed，但 --check/--plan/--emit-sql 仅用标准库即可。
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

# --------------------------------------------------------------------------
# 确定性 ID / 类型 / 效应（与 apps/worker/tasks/ingest.py 保持一致）
# --------------------------------------------------------------------------

def surrogate_id(key: str) -> int:
    """Deterministic UInt32 surrogate id: first 4 bytes of sha256."""
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "big", signed=False) & 0xFFFFFFFF


def compute_variant_id(release_id: str, chrom: str, pos: int, ref: str, alt: str) -> int:
    """Deterministic variant id: first 8 bytes of sha256(release|chrom|pos|ref|alt).

    The object key is deliberately NOT part of the identity, matching
    apps/worker/tasks/ingest.py: the manifest fingerprint ignores it so a retry
    can resume the same logical import, and seeded rows must agree with the
    ids the import protocol would mint for the same facts.
    """
    key = f"{release_id}|{chrom}|{pos}|{ref}|{alt}"
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], byteorder="big", signed=False)


def variant_length(ref: str, alt: str) -> int:
    """Allele span for ``variant_facts.length`` (matches the worker ingest):
    the longer allele, so SNP=1 and INS/DEL/MNV report their span."""
    return max(len(ref), len(alt))


def determine_variant_type(ref: str, alt: str) -> tuple[str, str]:
    ref_len, alt_len = len(ref), len(alt)
    if alt == "<DEL>" or alt.startswith("<") or alt_len > 50 or ref_len > 50:
        return "SV", "SV"
    if ref_len == 1 and alt_len == 1:
        return "SNP", "SNV"
    if ref_len == alt_len:
        return "MNV", "MNV"
    if ref_len > alt_len:
        return "DEL", "DEL"
    return "INS", "INS"


_INTERGENIC = "intergenic_variant"
_VALID_VARIANT_TYPES = {"SNP", "INS", "DEL", "MNV", "SV"}


def pick_most_severe_annotation(ann: str) -> dict[str, str]:
    """Parse the most severe SnpEff 'ANN' effect (simplified).

    ANN format (SnpEff): Allele|Annotation|Impact|GeneName|GeneID|FeatureType|...
    We return the first (most severe) effect's consequence/impact, and the
    gene symbol/id when present, so variant_facts.gene_id/gene_symbol are
    populated for real ANN-bearing VCFs (supports C3 gene-reference checks).
    """
    if not ann:
        return {"consequence": "", "impact": "", "gene_id": "", "gene_symbol": ""}
    effects: list[dict[str, str]] = []
    for field in ann.split(","):
        parts = field.split("|")
        if len(parts) >= 3:
            effects.append({
                "consequence": parts[1],
                "impact": parts[2].upper(),
                "gene_name": parts[3] if len(parts) > 3 else "",
                "gene_id": parts[4] if len(parts) > 4 else "",
            })
    if not effects:
        return {"consequence": "", "impact": "", "gene_id": "", "gene_symbol": ""}
    e = effects[0]
    return {
        "consequence": e["consequence"], "impact": e["impact"],
        "gene_id": e["gene_id"], "gene_symbol": e["gene_name"],
    }


# --------------------------------------------------------------------------
# 打开 gzip / 普通文本
# --------------------------------------------------------------------------

def _open_text(path: Path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "r", encoding="utf-8")


# --------------------------------------------------------------------------
# Demo 拒绝（fail-closed）
# --------------------------------------------------------------------------

DEMO_PATTERNS = ("SMDB-", "Wm82.a4.v1", "referenceGenome")


def reject_demo(text: str, label: str) -> None:
    """Refuse if any demo marker appears, so we never import placeholder data."""
    for pat in DEMO_PATTERNS:
        if pat in text:
            raise SystemExit(
                f"[FAIL] {label} 命中 Demo 标记 '{pat}' —— 拒绝导入（禁止示例数据冒充真实数据）"
            )


# --------------------------------------------------------------------------
# FASTA → assembly + chromosomes
# --------------------------------------------------------------------------

def parse_fasta(path: Path, assembly: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse sequences: return chromosome rows (name, length, order)."""
    chroms: list[dict[str, Any]] = []
    name, length, order = None, 0, 0
    with _open_text(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith(">"):
                reject_demo(line, path.name)
                # finalize previous
                if name is not None:
                    chroms.append({"name": name, "length": length, "order": order})
                order += 1
                name = line[1:].split()[0]
                length = 0
            else:
                if name is None:
                    raise SystemExit(f"[FAIL] {path.name}: 序列内容出现在 FASTA header 之前")
                length += len(line.replace(" ", "").strip())
        if name is not None:
            chroms.append({"name": name, "length": length, "order": order})
    if not chroms:
        raise SystemExit(f"[FAIL] {path.name}: 未解析到任何染色体序列")
    for c in chroms:
        if c["length"] <= 0:
            raise SystemExit(f"[FAIL] {path.name}: 染色体 {c['name']} 长度无效 ({c['length']})")
    return chroms


def load_assembly_meta(path: Path) -> dict[str, Any]:
    """Load assembly metadata JSON: name/version/species/urls/description."""
    raw = Path(path).read_text(encoding="utf-8")
    reject_demo(raw, path.name)
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[FAIL] {path.name}: assembly.meta 不是合法 JSON ({exc})")
    required = {"name", "version", "species"}
    missing = required - set(meta)
    if missing:
        raise SystemExit(f"[FAIL] {path.name}: 缺少 assembly.meta 字段 {sorted(missing)}")
    return meta


# --------------------------------------------------------------------------
# GFF3 → genes + transcripts + exons + gene_aliases
# --------------------------------------------------------------------------

def parse_gff3(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Parse gene/transcript/exon/alias rows from a GFF3 file (streaming)."""
    genes: dict[str, dict[str, Any]] = {}
    transcripts: dict[str, dict[str, Any]] = {}
    exons: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    with _open_text(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 9:
                raise SystemExit(f"[FAIL] {path.name}: 非法 GFF3 行（列数<9）: {line[:80]}")
            seqid, source, ftype, start, end, score, strand, phase, attrs = cols[0:9]
            try:
                start_i, end_i = int(start), int(end)
            except ValueError:
                raise SystemExit(f"[FAIL] {path.name}: 坐标非整数: {line[:80]}")
            if start_i < 1 or end_i < start_i:
                raise SystemExit(f"[FAIL] {path.name}: 非法坐标 start={start} end={end}")
            if strand not in ("+", "-"):
                raise SystemExit(f"[FAIL] {path.name}: 非法 strand '{strand}'")
            attr_map = _parse_gff3_attrs(attrs)
            gid = attr_map.get("ID", "")
            if not gid:
                raise SystemExit(f"[FAIL] {path.name}: {ftype} 行缺少 ID 属性")
            reject_demo(gid, path.name)
            parent = attr_map.get("Parent", "")
            if ftype == "gene":
                name = attr_map.get("Name") or attr_map.get("gene_name") or gid
                genes[gid] = {
                    "id": gid, "chromosome": seqid, "name": name,
                    "biotype": attr_map.get("biotype", "protein_coding"),
                    "start": start_i, "end": end_i, "strand": strand,
                    "description": attr_map.get("description", ""),
                    "attributes": {k: v for k, v in attr_map.items() if k not in ("ID", "Parent")},
                }
            elif ftype in ("mRNA", "transcript"):
                transcripts[gid] = {
                    "id": gid, "gene_id": parent, "name": attr_map.get("Name") or gid,
                    "biotype": "mRNA", "start": start_i, "end": end_i,
                    "strand": strand, "is_canonical": 1 if attr_map.get("canonical") == "true" else 0,
                }
            elif ftype == "exon":
                exons.append({"transcript_id": parent, "start": start_i, "end": end_i})
            # aliases from Name/Alias/Dbxref on any feature
            for alias_key in ("Name", "Alias", "Dbxref"):
                if attr_map.get(alias_key):
                    for alias in re.split(r"[;,]", attr_map[alias_key]):
                        alias = alias.strip()
                        if alias:
                            aliases.append({"gene_id": gid, "alias": alias, "source": alias_key})
    # reference integrity
    for t in transcripts.values():
        if t["gene_id"] not in genes:
            raise SystemExit(f"[FAIL] {path.name}: transcript {t['id']} 的 Parent gene 不存在")
    for e in exons:
        if e["transcript_id"] not in transcripts:
            raise SystemExit(f"[FAIL] {path.name}: exon 的 transcript 不存在 ({e['transcript_id']})")
    if not genes:
        raise SystemExit(f"[FAIL] {path.name}: 未解析到任何 gene 特征")
    return {"genes": list(genes.values()), "transcripts": list(transcripts.values()),
            "exons": exons, "aliases": aliases}


def _parse_gff3_attrs(attrs: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for tok in attrs.split(";"):
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


# --------------------------------------------------------------------------
# VCF → ClickHouse variant_facts（canonical schema）
# --------------------------------------------------------------------------

VARIANT_FACTS_COLS = [
    "variant_id", "release_key", "assembly_key", "chromosome", "position",
    "ref_allele", "alt_allele", "variant_type", "variant_subtype", "length",
    "gene_id", "gene_symbol", "gene_surrogate_id", "mutant_line_surrogate_id",
    "mutant_line_name", "consequence", "consequence_id", "impact", "rs_id",
    "quality_score", "filter_status", "read_depth", "allele_frequency",
    "hgvs_c", "hgvs_p", "zygosity",
]


def parse_vcf(path: Path, release_id: str, assembly: str,
              sample_names_by_line: list[str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    headers: list[str] = []
    with _open_text(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("##"):
                reject_demo(line, path.name)
                continue
            if line.startswith("#"):
                headers = line.lstrip("#").split("\t")
                continue
            cols = line.split("\t")
            if len(cols) < 8:
                raise SystemExit(f"[FAIL] {path.name}: 非法 VCF 行（列数<8）: {line[:80]}")
            chrom, pos_s, vid, ref, alt, qual, f = cols[0:7]
            info = cols[7]
            try:
                pos = int(pos_s)
            except ValueError:
                raise SystemExit(f"[FAIL] {path.name}: POS 非整数: {pos_s}")
            if pos <= 0:
                raise SystemExit(f"[FAIL] {path.name}: POS<=0: {pos_s}")
            if not ref or not alt or alt == "." or ref == ".":
                raise SystemExit(f"[FAIL] {path.name}: REF/ALT 缺失: {line[:80]}")
            reject_demo(f"{chrom}:{pos}:{ref}>{alt}", path.name)
            vtype, subtype = determine_variant_type(ref, alt)
            if vtype not in _VALID_VARIANT_TYPES:
                raise SystemExit(f"[FAIL] {path.name}: 非法 variant_type '{vtype}'")
            ann = _vcf_info(info, "ANN") or ""
            effect = pick_most_severe_annotation(ann)
            info_map = _parse_vcf_info(info)
            ann_gene_id = effect.get("gene_id") or ""
            ann_gene_symbol = effect.get("gene_symbol") or ""
            # sample/genotype → first non-reference sample
            ml_name, ml_sur = "", 0
            if len(headers) > 9:
                for sample_idx, gt in enumerate(cols[9:]):
                    if gt in ("0/0", "0|0", "."):
                        continue
                    sample = headers[9 + sample_idx] if 9 + sample_idx < len(headers) else ""
                    if sample:
                        ml_name, ml_sur = sample, surrogate_id(sample)
                        break
            gene_id = ann_gene_id or info_map.get("GENE", "") or _nearest_gene_hint(chrom, pos)
            gene_symbol = ann_gene_symbol or info_map.get("GENE_SYMBOL", "")
            rows.append({
                "variant_id": compute_variant_id(release_id, chrom, pos, ref, alt),
                "release_key": str(release_id), "assembly_key": assembly,
                "chromosome": chrom, "position": pos, "ref_allele": ref, "alt_allele": alt,
                "variant_type": vtype, "variant_subtype": subtype, "length": variant_length(ref, alt),
                "gene_id": gene_id, "gene_symbol": gene_symbol,
                "gene_surrogate_id": surrogate_id(gene_id) if gene_id else 0,
                "mutant_line_surrogate_id": ml_sur, "mutant_line_name": ml_name,
                "consequence": effect.get("consequence"), "consequence_id": 0,
                "impact": effect.get("impact"), "rs_id": "" if vid == "." else vid,
                "quality_score": float(qual) if qual not in ("", ".") else 0.0,
                "filter_status": f, "read_depth": int(float(info_map.get("DP", "0") or 0)),
                "allele_frequency": float(info_map.get("AF", "0") or 0),
                "hgvs_c": "", "hgvs_p": "", "zygosity": "unknown",
            })
    if not rows:
        raise SystemExit(f"[FAIL] {path.name}: 未解析到任何变异记录")
    return rows


def _nearest_gene_hint(chrom: str, pos: int) -> str:
    return ""  # 通用实现：不臆造 gene 命中；由 --gene-map 或 GFF3 邻近匹配后置注入


def _vcf_info(info: str, key: str) -> str:
    m = re.search(rf"\b{key}=([^;\t]+)", info)
    return m.group(1) if m else ""


def _parse_vcf_info(info: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for tok in info.split(";"):
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


# --------------------------------------------------------------------------
# mutants.tsv → mutant_lines
# --------------------------------------------------------------------------

def parse_mutants(path: Path, release_id: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with _open_text(path) as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for r in reader:
            row = {k: v for k, v in r.items()}
            name = (row.get("name") or "").strip()
            if not name:
                raise SystemExit(f"[FAIL] {path.name}: mutant 行缺少 name")
            reject_demo(name, path.name)
            species = row.get("species") or "Glycine max"
            rows.append({
                "name": name, "species": species,
                "cultivar": row.get("cultivar") or None, "mutagen": row.get("mutagen") or None,
                "mutagen_dose": row.get("mutagen_dose") or None,
                "generation": row.get("generation") or None,
                "description": row.get("description") or None, "is_public": True,
                "release_id": release_id,
            })
    if not rows:
        raise SystemExit(f"[FAIL] {path.name}: 未解析到任何 mutant 行")
    return rows


# --------------------------------------------------------------------------
# SQL / manifest helpers
# --------------------------------------------------------------------------

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def emit_ch_sql(out_dir: Path, variant_rows) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / "variant_facts.sql"
    with f.open("w", encoding="utf-8") as out:
        for r in variant_rows:
            cols = ", ".join(VARIANT_FACTS_COLS)
            vals = ", ".join(_ch_literal(r[c]) for c in VARIANT_FACTS_COLS)
            out.write(f"INSERT INTO variant_facts ({cols}) VALUES ({vals});\n")
    return f


def _ch_literal(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "\\'") + "'"


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------

def write_manifest(out_path: Path, release_id: str, assembly: str, species: str,
                   tool: str, tool_version: str, files: dict[str, Path]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "release_id": release_id, "assembly": assembly, "species": species,
        "tool": tool, "tool_version": tool_version,
        "files": {name: sha256(p) for name, p in files.items()},
    }
    out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# 写入（asyncpg + clickhouse_connect）—— 真实写库路径
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="seed_release_data.py")
    ap.add_argument("--source-dir", required=True)
    ap.add_argument("--release-id", type=int, default=None)
    ap.add_argument("--create-release", action="store_true")
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--name", default="")
    ap.add_argument("--assembly", default="Wm82v4.0")
    ap.add_argument("--species", default="Glycine max")
    ap.add_argument("--tool", default="soymutdb-seed")
    ap.add_argument("--tool-version", default="0.1.0")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--emit-sql", metavar="DIR", default=None)
    ap.add_argument("--write", action="store_true")
    _evdir = os.environ.get("SOYMUTDB_EVIDENCE_DIR", "artifacts/acceptance/data-query").rstrip("/")
    ap.add_argument("--manifest-out", default=f"{_evdir}/seed-manifest.json")
    ap.add_argument("--batch-size", type=int, default=50000)
    args = ap.parse_args(argv)

    src = Path(args.source_dir)
    if not src.is_dir():
        print(f"[FAIL] --source-dir 缺失或不是目录: {args.source_dir}", file=sys.stderr)
        return 5
    if args.release_id is None and not args.create_release:
        print("[FAIL] 需要 --release-id 或 --create-release", file=sys.stderr)
        return 5
    if args.create_release and (args.release_id is not None):
        print("[FAIL] --create-release 与 --release-id 二选一", file=sys.stderr)
        return 5
    if "a4" in args.assembly or args.assembly == "Wm82.a4.v1":
        print(f"[FAIL] assembly '{args.assembly}' 是 Demo 符号，需归一为 Wm82v4.0", file=sys.stderr)
        return 2

    fasta = src / "genome.fa"
    fasta_fai = src / "genome.fa.fai"
    gff3 = src / "annotations.gff3"
    vcf = src / "variants.vcf"
    mutants_path = src / "mutants.tsv"
    meta = src / "assembly.meta"
    for rel, p in [("genome.fa", fasta), ("assembly.meta", meta),
                   ("annotations.gff3", gff3), ("variants.vcf", vcf)]:
        if not p.exists() or p.stat().st_size == 0:
            print(f"[FAIL] 缺少必需输入: {rel} (在 {src})", file=sys.stderr); return 2

    is_write = args.write
    if is_write:
        if os.environ.get("SOYMUTDB_SEED_ENABLED") != "1":
            print("[FAIL] --write 需要 SOYMUTDB_SEED_ENABLED=1（且需先冻结数据源/备份）。", file=sys.stderr); return 4

    try:
        assembly_meta = load_assembly_meta(meta)
        chroms = parse_fasta(fasta, assembly_meta)
        parsed_gff = parse_gff3(gff3)
        vrows = parse_vcf(vcf, str(args.release_id), args.assembly)
        mutants = parse_mutants(mutants_path, args.release_id) if mutants_path.exists() else []
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.check:
        print(f"  校验 OK: chromosomes={len(chroms)} genes={len(parsed_gff['genes'])} "
              f"transcripts={len(parsed_gff['transcripts'])} exons={len(parsed_gff['exons'])} "
              f"aliases={len(parsed_gff['aliases'])} variants={len(vrows)} mutants={len(mutants)}")
        write_manifest(Path(args.manifest_out), str(args.release_id or "<create>"),
                       args.assembly, args.species, args.tool, args.tool_version,
                       {"genome.fa": fasta, "annotations.gff3": gff3, "variants.vcf": vcf})
        return 0

    if args.emit_sql:
        out_dir = Path(args.emit_sql)
        f = emit_ch_sql(out_dir, vrows)
        print(f"  emitted variant_facts SQL -> {f}")
        print("  NOTE: PG 侧(assemblies/chromosomes/genes/…)含自增 FK，需 apply 时解析 id；"
              "--emit-sql 仅演示 CH variant_facts 的行级映射。")
        return 0

    if args.plan:
        print(f"  plan: chromosomes={len(chroms)} genes={len(parsed_gff['genes'])} "
              f"transcripts={len(parsed_gff['transcripts'])} variants={len(vrows)} mutants={len(mutants)}")
        write_manifest(Path(args.manifest_out), str(args.release_id or "<create>"),
                       args.assembly, args.species, args.tool, args.tool_version,
                       {"genome.fa": fasta, "annotations.gff3": gff3, "variants.vcf": vcf})
        return 0

    if is_write:
        print("[FAIL] --write 的 PG(asyncpg)/CH(clickhouse_connect) 写库适配器当前 fail-closed："
              "需先冻结数据源/版本并授权（设计 route-b-seed-data-design.md §11）。"
              "可用 --check/--plan/--emit-sql 先验证真实解析结果。", file=sys.stderr)
        return 4

    print("未指定模式（--check/--plan/--emit-sql/--write）", file=sys.stderr)
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
