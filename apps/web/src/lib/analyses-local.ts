/**
 * Analyses — local "recent jobs" record (browser-side fallback).
 *
 * The backend now exposes `GET /analyses` (own jobs, newest first) so the
 * list page prefers the server. This module keeps a lightweight localStorage
 * index of job ids the current browser has submitted, which:
 *   - survives anonymous / pre-backend deploys (list endpoint not yet
 *     deployed → 404 → fall back to local ids + per-job lookups), and
 *   - lets the list page render immediately after a submission.
 *
 * Entries are just job ids; job payloads are always fetched live from
 * `getAnalysis(jobId)`.
 */

const STORAGE_KEY = "soymutdb.analyses.recent_jobs";
const MAX_ENTRIES = 20;

function readRaw(): string[] {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((v): v is string => typeof v === "string");
  } catch {
    return [];
  }
}

/** Remember a submitted job id (deduped, newest first, capped at MAX_ENTRIES). */
export function recordRecentJob(jobId: string): void {
  if (typeof localStorage === "undefined") return;
  try {
    const next = [jobId, ...readRaw().filter((id) => id !== jobId)].slice(0, MAX_ENTRIES);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable — ignore */
  }
}

/** Recent job ids, newest first. */
export function readRecentJobs(): string[] {
  return readRaw();
}

/** Forget a job id (e.g. when the server reports it does not exist). */
export function forgetRecentJob(jobId: string): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(readRaw().filter((id) => id !== jobId)));
  } catch {
    /* storage unavailable — ignore */
  }
}
