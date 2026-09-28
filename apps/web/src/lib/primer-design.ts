/**
 * Pure-frontend primer design (no Primer3 backend).
 *
 * Simplified primer-pair design over a target template sequence:
 *   - forward candidates slide over the 5' third of the template
 *   - reverse candidates slide over the 3' third (stored as the
 *     reverse complement, i.e. the sequence to synthesize)
 *   - candidates are filtered by length / Tm / GC / homopolymer runs
 *     and ranked by a composite score; the top pairs are returned.
 *
 * Tm uses the salt-adjusted basic formula
 * (64.9 + 41*(GC-16.4)/len - 600/len) with a Wallace fallback for
 * very short sequences. GC% and 3'-GC-clamp are standard heuristics.
 *
 * All functions are pure and unit-tested (vitest, node env).
 */

export const MIN_PRIMER_LEN = 18;
export const MAX_PRIMER_LEN = 25;
export const TM_MIN = 55;
export const TM_MAX = 65;
export const GC_MIN = 40;
export const GC_MAX = 60;
export const MAX_HOMOPOLYMER = 4;
export const CANDIDATES_PER_END = 3;
export const MAX_PAIRS = 3;

export interface PrimerCandidate {
  /** Sequence in synthesis orientation (5' → 3'). */
  seq: string;
  /** 1-based start within the template (forward strand coordinates). */
  start: number;
  /** 1-based end within the template (forward strand coordinates). */
  end: number;
  length: number;
  tm: number;
  gc: number;
  /** 3' terminal GC clamp (last 1-2 bases are G/C). */
  clamp: boolean;
  /** Composite score 0-100 (higher = better). */
  score: number;
}

export interface PrimerPair {
  forward: PrimerCandidate;
  reverse: PrimerCandidate;
  /** Expected amplicon length on the template (bp). */
  productLen: number;
  score: number;
}

const BASE_MAP: Record<string, string> = {
  A: "T",
  T: "A",
  G: "C",
  C: "G",
  N: "N",
};

/** Reverse complement of a DNA sequence (accepts ACGTN, case-insensitive). */
export function reverseComplement(seq: string): string {
  let out = "";
  for (let i = seq.length - 1; i >= 0; i -= 1) {
    const base = seq[i]?.toUpperCase();
    out += base ? (BASE_MAP[base] ?? "N") : "N";
  }
  return out;
}

/** GC content percentage (0-100) over ACGT bases only. */
export function calcGC(seq: string): number {
  let gc = 0;
  let total = 0;
  for (const ch of seq.toUpperCase()) {
    if (ch === "G" || ch === "C") gc += 1;
    if (ch === "G" || ch === "C" || ch === "A" || ch === "T") total += 1;
  }
  if (total === 0) return 0;
  return Math.round((gc / total) * 1000) / 10;
}

/** Wallace rule Tm — adequate for short oligos (≤ 14 nt). */
export function calcTmWallace(seq: string): number {
  let at = 0;
  let gc = 0;
  for (const ch of seq.toUpperCase()) {
    if (ch === "A" || ch === "T") at += 1;
    else if (ch === "G" || ch === "C") gc += 1;
  }
  return 2 * at + 4 * gc;
}

/**
 * Salt-adjusted melting temperature.
 *
 * Oligos in the primer range (≤ 25 nt) use the Wallace rule
 * (2*(A+T) + 4*(G+C)), which is accurate for short oligos; longer
 * sequences fall back to the salt-adjusted basic formula
 * (64.9 + 41*(GC − 16.4)/len − 600/len, 50 mM salt).
 */
export function calcTm(seq: string): number {
  const s = seq.toUpperCase();
  const len = s.length;
  if (len <= 25) return calcTmWallace(s);
  const gc = [...s].filter((c) => c === "G" || c === "C").length;
  if (len < 8 || gc === 0 || gc === len) return calcTmWallace(s);
  return Math.round((64.9 + (41 * (gc - 16.4)) / len - 600 / len) * 10) / 10;
}

/** True when the 3' terminal one or two bases are G/C (GC clamp). */
export function hasGcClamp(seq: string): boolean {
  const tail = seq.slice(-2).toUpperCase();
  return tail.length > 0 && /[GC]/.test(tail[0]!) && /[GC]/.test(tail[tail.length - 1]!);
}

/** True when the sequence contains a homopolymer run ≥ MAX_HOMOPOLYMER. */
export function hasHomopolymerRun(seq: string, max = MAX_HOMOPOLYMER): boolean {
  let run = 1;
  for (let i = 1; i < seq.length; i += 1) {
    run = seq[i] === seq[i - 1] ? run + 1 : 1;
    if (run >= max) return true;
  }
  return false;
}

/** Composite score 0-100: Tm proximity, GC proximity, length, GC clamp. */
export function scorePrimer(seq: string): number {
  const len = seq.length;
  const tm = calcTm(seq);
  const gc = calcGC(seq);

  const tmPenalty = Math.min(1, Math.abs(tm - 60) / 20); // 60°C ideal
  const gcPenalty = Math.min(1, Math.abs(gc - 50) / 30); // 50% ideal
  const lenPenalty =
    len < MIN_PRIMER_LEN || len > MAX_PRIMER_LEN
      ? 1
      : Math.abs(len - 20) / 10; // 20 nt ideal
  const clampBonus = hasGcClamp(seq) ? 0.08 : 0;

  const raw = 1 - (tmPenalty * 0.45 + gcPenalty * 0.3 + lenPenalty * 0.25) + clampBonus;
  return Math.round(Math.max(0, Math.min(1, raw)) * 100);
}

/** Normalise template input: uppercase, keep ACGTN only, strip whitespace. */
export function normaliseTemplate(input: string): string {
  return input
    .toUpperCase()
    .replace(/[^ACGTN]/g, "")
    .replace(/N+/g, "N");
}

function isCandidateOk(seq: string): boolean {
  if (seq.length < MIN_PRIMER_LEN || seq.length > MAX_PRIMER_LEN) return false;
  if (hasHomopolymerRun(seq)) return false;
  const tm = calcTm(seq);
  if (tm < TM_MIN || tm > TM_MAX) return false;
  const gc = calcGC(seq);
  return gc >= GC_MIN && gc <= GC_MAX;
}

function slideCandidates(template: string, from: number, to: number): PrimerCandidate[] {
  const candidates: PrimerCandidate[] = [];
  // Slide over every window length in [MIN, MAX] within [from, to).
  for (let start = from; start + MIN_PRIMER_LEN <= to; start += 1) {
    const maxEnd = Math.min(to, start + MAX_PRIMER_LEN);
    for (let end = start + MIN_PRIMER_LEN; end <= maxEnd; end += 1) {
      const seq = template.slice(start, end);
      if (!isCandidateOk(seq)) continue;
      candidates.push({
        seq,
        start: start + 1,
        end,
        length: seq.length,
        tm: calcTm(seq),
        gc: calcGC(seq),
        clamp: hasGcClamp(seq),
        score: scorePrimer(seq),
      });
    }
  }
  return candidates.sort((a, b) => b.score - a.score);
}

export interface DesignOptions {
  /** Return at most this many pairs. */
  maxPairs?: number;
}

/**
 * Design primer pairs over a template sequence.
 *
 * Forward candidates are chosen from the 5' third, reverse candidates from
 * the 3' third (reverse-complemented for synthesis). Returns the top pairs
 * ranked by combined score, or [] when no valid candidate exists.
 */
export function designPrimerPair(
  input: string,
  opts: DesignOptions = {},
): PrimerPair[] {
  const maxPairs = opts.maxPairs ?? MAX_PAIRS;
  const template = normaliseTemplate(input);
  if (template.length < MIN_PRIMER_LEN * 2 + 10) return [];

  const third = Math.floor(template.length / 3);
  const forwardZone = [0, third] as const;
  const reverseZone = [template.length - third, template.length] as const;

  const forwards = slideCandidates(template, forwardZone[0], forwardZone[1]).slice(
    0,
    CANDIDATES_PER_END,
  );
  const reverseTemplates = slideCandidates(template, reverseZone[0], reverseZone[1]).slice(
    0,
    CANDIDATES_PER_END,
  );
  const reverses = reverseTemplates.map((c) => ({
    ...c,
    seq: reverseComplement(c.seq),
  }));

  if (forwards.length === 0 || reverses.length === 0) return [];

  const pairs: PrimerPair[] = [];
  for (const f of forwards) {
    for (const r of reverses) {
      pairs.push({
        forward: f,
        reverse: r,
        productLen: r.end - f.start + 1,
        score: Math.round((f.score * 0.5 + r.score * 0.5) * 10) / 10,
      });
    }
  }
  return pairs
    .sort((a, b) => b.score - a.score)
    .slice(0, maxPairs);
}

/** Parse a FASTA string into an array of { header, sequence } records. */
export function parseFasta(input: string): { header: string; sequence: string }[] {
  const records: { header: string; sequence: string }[] = [];
  let header = "";
  let seq = "";
  for (const line of input.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    if (trimmed.startsWith(">")) {
      if (header) records.push({ header, sequence: seq });
      header = trimmed.slice(1).trim();
      seq = "";
    } else {
      seq += trimmed;
    }
  }
  if (header) records.push({ header, sequence: seq });
  return records;
}
