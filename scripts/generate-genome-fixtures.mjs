#!/usr/bin/env node
// Generate the small, committed fixtures used by packages/genome-data tests.
//
// The script is dependency-free (Node zlib only) and idempotent: every run
// rewrites identical bytes. It emits:
//   reference.fa.gz / .fai / .gzi   bgzip FASTA + indexes
//   variants.vcf[.gz / .gz.tbi]     tabix VCF
//   features.gff3[.gz / .gz.tbi]    tabix GFF3
//   genes.ix / genes.ixx            Trix text search
//   chrom.sizes                     plain text reference sizes
//   alignment.sam                   SAM source of the committed alignment.bam
//
// alignment.bam / alignment.bam.bai are committed binaries. Rebuild them from
// the emitted SAM with samtools 1.24, run from this fixtures directory:
//
//   samtools view -b -o alignment.bam alignment.sam
//   samtools index alignment.bam
//
// The @PG line in the BAM header records that exact command, so samtools 1.24
// reproduces the committed alignment.bam/.bai byte for byte.
//
// gc_content.bw is a committed BigWig fixture (chr01:0-20 = 0.4,
// chr01:20-40 = 0.6) produced with pyBigWig. This dependency-free script does
// not rewrite it (no offline BigWig writer in Node); the source is:
//
//   import pyBigWig
//   bw = pyBigWig.open("gc_content.bw", "w")
//   bw.addHeader([("chr01", 60), ("chr02", 40)])
//   bw.addEntries("chr01", [0, 20], ends=[20, 40], values=[0.4, 0.6])
//   bw.close()
//
// LIMITATION: BigBed (.bb) has no offline writer in this repo (only the
// @gmod/bbi readers are installed), so no binary BigBed fixture is produced.
//
// Run: node scripts/generate-genome-fixtures.mjs

import { Buffer } from "node:buffer";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { crc32, deflateRawSync } from "node:zlib";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, "../packages/genome-data/test/fixtures");
const MAX_BLOCK = 0xff00;
const TBI_MAGIC = "TBI\u0001";
const GFF_META = "#".charCodeAt(0);
const VCF_FORMAT = 2;

function bgzfBlock(chunk) {
  const deflated = deflateRawSync(chunk);
  const totalSize = 18 + deflated.length + 8;
  const block = Buffer.alloc(totalSize);
  block[0] = 0x1f;
  block[1] = 0x8b;
  block[2] = 8; // CM = deflate
  block[3] = 4; // FLG = FEXTRA
  block.writeUInt32LE(0, 4); // MTIME
  block[8] = 0; // XFL
  block[9] = 0xff; // OS
  block.writeUInt16LE(6, 10); // XLEN
  block[12] = 0x42; // 'B'
  block[13] = 0x43; // 'C'
  block.writeUInt16LE(2, 14); // SLEN
  block.writeUInt16LE(totalSize - 1, 16); // BSIZE
  deflated.copy(block, 18);
  block.writeUInt32LE(crc32(chunk) >>> 0, 18 + deflated.length);
  block.writeUInt32LE(chunk.length, 22 + deflated.length);
  return block;
}

// Encode bytes as a series of BGZF blocks plus the 28-byte EOF marker. Returns
// the compressed buffer and the compressed/uncompressed offsets of every data
// block so callers can build a .gzi or a virtual file offset.
function bgzfEncode(data) {
  const parts = [];
  const dataBlocks = [];
  let compressedOffset = 0;
  let uncompressedOffset = 0;
  for (let i = 0; i < data.length; i += MAX_BLOCK) {
    const chunk = data.subarray(i, Math.min(i + MAX_BLOCK, data.length));
    const block = bgzfBlock(chunk);
    dataBlocks.push({ compressedOffset, uncompressedOffset });
    parts.push(block);
    compressedOffset += block.length;
    uncompressedOffset += chunk.length;
  }
  parts.push(bgzfBlock(Buffer.alloc(0)));
  return { compressed: Buffer.concat(parts), dataBlocks };
}

function virtualOffset(dataBlocks, position) {
  let chosen = dataBlocks[0];
  for (const block of dataBlocks) {
    if (block.uncompressedOffset <= position) chosen = block;
    else break;
  }
  return (BigInt(chosen.compressedOffset) << 16n) | BigInt(position - chosen.uncompressedOffset);
}

function u64(value) {
  const buffer = Buffer.alloc(8);
  buffer.writeBigUInt64LE(BigInt(value));
  return buffer;
}

function buildGzi(dataBlocks) {
  const entries = dataBlocks.slice(1);
  const buffer = Buffer.alloc(8 + entries.length * 16);
  buffer.writeBigUInt64LE(BigInt(entries.length), 0);
  entries.forEach((block, index) => {
    buffer.writeBigUInt64LE(BigInt(block.compressedOffset), 8 + index * 16);
    buffer.writeBigUInt64LE(BigInt(block.uncompressedOffset), 8 + index * 16 + 8);
  });
  return buffer;
}

function firstDataOffset(text) {
  let offset = 0;
  for (const line of text.split("\n")) {
    if (line.length > 0 && !line.startsWith("#")) return offset;
    offset += Buffer.byteLength(line, "utf8") + 1;
  }
  return offset;
}

// Minimal single-chunk tabix index. One bin (0) and a one-entry linear index
// point at every data byte, and gmod's getLines filters the real rows by
// overlap, so a tiny fixture never needs a full binning index.
function buildTbi(options) {
  const { data, dataBlocks, refNames, format, colSeq, colBeg, colEnd } = options;
  const text = Buffer.isBuffer(data) ? data.toString("utf8") : data;
  const minv = virtualOffset(dataBlocks, firstDataOffset(text));
  const maxv = virtualOffset(dataBlocks, data.length - 1);
  const names = Buffer.concat(
    refNames.map((refName) => Buffer.concat([Buffer.from(refName, "utf8"), Buffer.from([0])])),
  );

  const chunks = [];
  chunks.push(Buffer.from(TBI_MAGIC, "latin1"));
  const header = Buffer.alloc(32);
  header.writeInt32LE(refNames.length, 0);
  header.writeInt32LE(format, 4);
  header.writeInt32LE(colSeq, 8);
  header.writeInt32LE(colBeg, 12);
  header.writeInt32LE(colEnd, 16);
  header.writeInt32LE(GFF_META, 20);
  header.writeInt32LE(0, 24); // skip
  header.writeInt32LE(names.length, 28);
  chunks.push(header, names);

  for (let i = 0; i < refNames.length; i += 1) {
    const refHeader = Buffer.alloc(4);
    refHeader.writeInt32LE(1, 0); // n_bin
    const bin = Buffer.alloc(4 + 4 + 16);
    bin.writeUInt32LE(0, 0); // bin
    bin.writeInt32LE(1, 4); // n_chunk
    u64(minv).copy(bin, 8);
    u64(maxv).copy(bin, 16);
    const linear = Buffer.alloc(4 + 8);
    linear.writeInt32LE(1, 0); // n_intv
    u64(minv).copy(linear, 4);
    chunks.push(refHeader, bin, linear);
  }
  chunks.push(u64(0)); // n_no_coor
  return Buffer.concat(chunks);
}

function bgzipText(text) {
  return bgzfEncode(Buffer.from(text, "utf8"));
}

function write(name, data) {
  writeFileSync(resolve(OUT, name), data);
}

function generateFasta() {
  const records = [
    { name: "chr01", sequence: "ACGT".repeat(15) },
    { name: "chr02", sequence: "TTTTGGGGCCCCAAAATTTTGGGGCCCCAAAATTTTGGGG" },
  ];
  const wrap = 20;
  const parts = [];
  const fai = [];
  let offset = 0;
  for (const record of records) {
    const header = ">" + record.name + "\n";
    parts.push(header);
    offset += Buffer.byteLength(header, "utf8");
    const firstBaseOffset = offset;
    for (let i = 0; i < record.sequence.length; i += wrap) {
      const line = record.sequence.slice(i, i + wrap) + "\n";
      parts.push(line);
      offset += Buffer.byteLength(line, "utf8");
    }
    fai.push(
      [record.name, record.sequence.length, firstBaseOffset, wrap, wrap + 1].join("\t"),
    );
  }
  const text = parts.join("");
  const { compressed, dataBlocks } = bgzipText(text);
  write("reference.fa.gz", compressed);
  write("reference.fa.gz.fai", fai.join("\n") + "\n");
  write("reference.fa.gz.gzi", buildGzi(dataBlocks));
  write(
    "chrom.sizes",
    records.map((record) => record.name + "\t" + record.sequence.length).join("\n") + "\n",
  );
  return text;
}

const VCF_TEXT = [
  "##fileformat=VCFv4.2",
  "##contig=<ID=chr01,length=60>",
  "##contig=<ID=chr02,length=40>",
  '##INFO=<ID=END,Number=1,Type=Integer,Description="End position">',
  '##INFO=<ID=SVTYPE,Number=1,Type=String,Description="SV type">',
  '##INFO=<ID=DP,Number=1,Type=Integer,Description="Total depth">',
  "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
  "chr01\t1\trs1\tA\tT\t50\tPASS\tDP=10",
  "chr01\t5\t.\tACGT\tA\t40\tPASS\tDP=7",
  "chr01\t10\t.\tA\tAT\t30\tPASS\t.",
  "chr01\t15\t.\tACGT\tAGGT\t20\tPASS\t.",
  "chr01\t20\t.\tN\t<DEL>\t.\tPASS\tSVTYPE=DEL;END=40",
  "chr01\t50\t.\tN\tN]chr02:30]\t.\tPASS\tSVTYPE=BND",
  "chr02\t3\trs2\tG\tC\t60\tPASS\tDP=3",
].join("\n") + "\n";

function generateVcf() {
  const data = Buffer.from(VCF_TEXT, "utf8");
  const { compressed, dataBlocks } = bgzfEncode(data);
  write("variants.vcf", data);
  write("variants.vcf.gz", compressed);
  write(
    "variants.vcf.gz.tbi",
    bgzfEncode(
      buildTbi({
        data,
        dataBlocks,
        refNames: ["chr01", "chr02"],
        format: VCF_FORMAT,
        colSeq: 1,
        colBeg: 2,
        colEnd: 0,
      }),
    ).compressed,
  );
}

const GFF_TEXT = [
  "##gff-version 3",
  "chr01\tsrc\tgene\t1\t60\t.\t+\t.\tID=gene01;Name=Gene01",
  "chr01\tsrc\tmRNA\t1\t60\t.\t+\t.\tID=mrna01;Parent=gene01",
  "chr01\tsrc\texon\t1\t20\t.\t+\t.\tID=exon01;Parent=mrna01",
  "chr01\tsrc\tCDS\t5\t20\t.\t+\t0\tID=cds01;Parent=mrna01",
  "chr01\tsrc\texon\t41\t60\t.\t+\t.\tID=exon02;Parent=mrna01",
  "chr02\tsrc\tgene\t1\t40\t.\t-\t.\tID=gene02;Name=Gene%2002",
].join("\n") + "\n";

function generateGff() {
  const data = Buffer.from(GFF_TEXT, "utf8");
  const { compressed, dataBlocks } = bgzfEncode(data);
  write("features.gff3", data);
  write("features.gff3.gz", compressed);
  write(
    "features.gff3.gz.tbi",
    bgzfEncode(
      buildTbi({
        data,
        dataBlocks,
        refNames: ["chr01", "chr02"],
        format: 0,
        colSeq: 1,
        colBeg: 4,
        colEnd: 5,
      }),
    ).compressed,
  );
}

// Trix .ix rows are space-separated "<term> <key,...>"; keys use "|" so they
// never contain a space.
const TRIX_IX = [
  "at1g01010 chr01:1..60|gene:AT1G01010|AT1G01010",
  "at1g01020 chr01:41..60|gene:AT1G01020|AT1G01020",
  "at2g01010 chr02:1..40|gene:AT2G01010|AT2G01010",
  "at3g01010 chr03:1..10|gene:AT3G01010|AT3G01010",
].join("\n") + "\n";

function generateTrix() {
  write("genes.ix", TRIX_IX);
  write("genes.ixx", "a" + "0000000000" + "\n");
}

// SAM source for alignment.bam: four 5M reads with Phred-40 qualities. It is
// written so the committed BAM stays reproducible with samtools (see header).
const ALIGNMENT_SAM = [
  "@HD\tVN:1.6\tSO:coordinate",
  "@SQ\tSN:chr01\tLN:60",
  "@SQ\tSN:chr02\tLN:40",
  "r1\t0\tchr01\t1\t60\t5M\t*\t0\t0\tACGTA\tIIIII",
  "r2\t0\tchr01\t10\t60\t5M\t*\t0\t0\tTTTTT\tIIIII",
  "r3\t16\tchr01\t20\t60\t5M\t*\t0\t0\tCCCCC\tIIIII",
  "r4\t0\tchr02\t5\t60\t5M\t*\t0\t0\tGGGGG\tIIIII",
].join("\n") + "\n";

function generateAlignment() {
  write("alignment.sam", ALIGNMENT_SAM);
}

function main() {
  mkdirSync(OUT, { recursive: true });
  generateFasta();
  generateVcf();
  generateGff();
  generateTrix();
  generateAlignment();
  process.stdout.write("genome fixtures written to " + OUT + "\n");
  process.stdout.write(
    "note: rebuild alignment.bam/.bai with samtools and gc_content.bw with pyBigWig (see header)\n",
  );
}

main();
