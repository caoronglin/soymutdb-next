/**
 * Unit tests for the pure-frontend primer design module.
 * Runs in vitest node env (apps/web).
 */
import { describe, expect, it } from "vitest";
import {
  calcGC,
  calcTm,
  calcTmWallace,
  designPrimerPair,
  hasGcClamp,
  hasHomopolymerRun,
  normaliseTemplate,
  parseFasta,
  reverseComplement,
  scorePrimer,
} from "../primer-design";

describe("reverseComplement", () => {
  it("complements and reverses", () => {
    expect(reverseComplement("ATGC")).toBe("GCAT");
  });

  it("handles lowercase and Ns", () => {
    expect(reverseComplement("atgn")).toBe("NCAT");
  });

  it("is an involution", () => {
    const seq = "ACGTACGTNNATGC";
    expect(reverseComplement(reverseComplement(seq))).toBe(seq);
  });
});

describe("calcGC", () => {
  it("computes percentages over ACGT only", () => {
    expect(calcGC("ATGC")).toBe(50);
    expect(calcGC("AAAA")).toBe(0);
    expect(calcGC("GCGC")).toBe(100);
  });

  it("ignores non-ACGT bases", () => {
    expect(calcGC("ATGCXYZ")).toBe(50);
  });

  it("returns 0 for empty/degenerate input", () => {
    expect(calcGC("")).toBe(0);
    expect(calcGC("NNNN")).toBe(0);
  });
});

describe("calcTm", () => {
  it("matches the Wallace rule for short oligos", () => {
    expect(calcTmWallace("ATGC")).toBe(12);
    expect(calcTmWallace("AAAA")).toBe(8);
    expect(calcTmWallace("GGGG")).toBe(16);
  });

  it("falls back to Wallace for degenerate sequences", () => {
    expect(calcTm("AT")).toBe(calcTmWallace("AT"));
    expect(calcTm("GGGG")).toBe(calcTmWallace("GGGG"));
  });

  it("computes a sane range for 20mers", () => {
    const tm = calcTm("ACGTACGTACGTACGTACGT");
    expect(tm).toBeGreaterThan(50);
    expect(tm).toBeLessThan(70);
  });
});

describe("hasGcClamp", () => {
  it("detects 3-prime GC clamp", () => {
    expect(hasGcClamp("ACGTACGTACGTGC")).toBe(true);
    expect(hasGcClamp("ACGTACGTACGTTT")).toBe(false);
  });
});

describe("hasHomopolymerRun", () => {
  it("detects long runs", () => {
    expect(hasHomopolymerRun("ACGTAAAAACGT")).toBe(true);
    expect(hasHomopolymerRun("ACGTACGT")).toBe(false);
  });
});

describe("scorePrimer", () => {
  it("rewards GC clamp and penalises extremes", () => {
    const good = scorePrimer("ACGTACGTACGTACGTACGT");
    const poor = scorePrimer("AAAAAAAAAAAAAAAAAAAA");
    expect(good).toBeGreaterThan(poor);
    expect(good).toBeGreaterThanOrEqual(0);
    expect(good).toBeLessThanOrEqual(100);
  });
});

describe("normaliseTemplate", () => {
  it("uppercases and strips non-ACGTN", () => {
    expect(normaliseTemplate("acgt-rn\n123")).toBe("ACGTN");
    expect(normaliseTemplate("ACGT")).toBe("ACGT");
  });
});

describe("designPrimerPair", () => {
  // A GC-rich 300 bp template with a balanced composition: alternating
  // ACGT blocks that should yield valid candidates.
  const block = "ACGTACGTACGTACGTACGT";
  const template = Array.from({ length: 15 }, () => block).join(""); // 300 bp

  it("returns at least one valid pair for a good template", () => {
    const pairs = designPrimerPair(template);
    expect(pairs.length).toBeGreaterThan(0);
    expect(pairs.length).toBeLessThanOrEqual(3);
  });

  it("produces syntactically valid candidates", () => {
    const pairs = designPrimerPair(template);
    for (const pair of pairs) {
      expect(pair.forward.seq.length).toBeGreaterThanOrEqual(18);
      expect(pair.forward.seq.length).toBeLessThanOrEqual(25);
      expect(pair.forward.tm).toBeGreaterThanOrEqual(55);
      expect(pair.forward.tm).toBeLessThanOrEqual(65);
      expect(pair.forward.gc).toBeGreaterThanOrEqual(40);
      expect(pair.forward.gc).toBeLessThanOrEqual(60);
      expect(pair.reverse.seq.length).toBe(pair.reverse.length);
      expect(pair.productLen).toBeGreaterThan(0);
      // The reverse candidate is the reverse complement of the 3' region.
      expect(pair.reverse.start).toBeGreaterThan(pair.forward.end);
    }
  });

  it("ranks pairs by score descending", () => {
    const pairs = designPrimerPair(template);
    for (let i = 1; i < pairs.length; i += 1) {
      expect(pairs[i]!.score).toBeLessThanOrEqual(pairs[i - 1]!.score);
    }
  });

  it("respects maxPairs", () => {
    const pairs = designPrimerPair(template, { maxPairs: 1 });
    expect(pairs.length).toBeLessThanOrEqual(1);
  });

  it("returns [] for templates too short to design", () => {
    expect(designPrimerPair("ACGTACGT")).toEqual([]);
  });

  it("returns [] for low-complexity templates (homopolymer / extreme GC)", () => {
    expect(designPrimerPair("A".repeat(300))).toEqual([]);
    expect(designPrimerPair("GC".repeat(150))).toEqual([]);
  });

  it("is deterministic for the same input", () => {
    const a = designPrimerPair(template);
    const b = designPrimerPair(template);
    expect(a).toEqual(b);
  });
});

describe("parseFasta", () => {
  it("parses multi-record FASTA", () => {
    const records = parseFasta(">seq1\nACGT\nACGT\n>seq2\nTTTT\n");
    expect(records).toHaveLength(2);
    expect(records[0]).toEqual({ header: "seq1", sequence: "ACGTACGT" });
    expect(records[1]).toEqual({ header: "seq2", sequence: "TTTT" });
  });

  it("handles empty input", () => {
    expect(parseFasta("")).toEqual([]);
  });
});
