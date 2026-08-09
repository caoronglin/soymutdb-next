#!/usr/bin/env tsx
/**
 * Content Snapshot Fetcher (E2-3)
 *
 * Fetches the public content snapshot (news + about) for static content
 * pages.  Contract: docs/design/static-content-richtext-2026-08.md §4.1.
 *
 * Resolution order:
 *   1. $CONTENT_SNAPSHOT_URL  -> fetch -> validate -> dist/data/content.json
 *   2. apps/web/content-snapshot/content.json (committed fixture) -> copy
 *   3. Nothing available:
 *        - CI / production (NODE_ENV=production or CI=true): FAIL (exit 1)
 *        - local: warn + skip (content pages fall back to SPA/API)
 */

import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const DIST_DIR = join(process.cwd(), "dist");
const DATA_DIR = join(DIST_DIR, "data");
const SNAPSHOT_OUT = join(DATA_DIR, "content.json");
const FIXTURE_DIR = join(process.cwd(), "content-snapshot");
const FIXTURE_FILE = join(FIXTURE_DIR, "content.json");

const SNAPSHOT_URL = process.env.CONTENT_SNAPSHOT_URL ?? "";
const IS_PRODUCTION_BUILD =
  process.env.CI === "true" || process.env.NODE_ENV === "production";

interface Snapshot {
  schema_version: number;
  generated_at: string;
  news: {
    source_total: number;
    included_total: number;
    truncated: boolean;
    items: unknown[];
  };
  news_detail: Record<string, unknown>;
  about: Record<string, string | null>;
}

function validateSnapshot(raw: unknown): Snapshot {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("snapshot is not an object");
  }
  const s = raw as Record<string, unknown>;
  if (s.schema_version !== 1) {
    throw new Error(`unsupported schema_version: ${s.schema_version}`);
  }
  if (typeof s.generated_at !== "string" || !s.generated_at) {
    throw new Error("snapshot missing generated_at");
  }
  const news = s.news as Record<string, unknown> | undefined;
  if (typeof news !== "object" || news === null) {
    throw new Error("snapshot missing news block");
  }
  if (!Array.isArray(news.items)) {
    throw new Error("snapshot news.items must be an array");
  }
  if (typeof news.source_total !== "number" || typeof news.included_total !== "number") {
    throw new Error("snapshot news totals must be numbers");
  }
  if (typeof s.news_detail !== "object" || s.news_detail === null) {
    throw new Error("snapshot missing news_detail");
  }
  return s as unknown as Snapshot;
}

function writeSnapshot(snapshot: Snapshot): void {
  mkdirSync(DATA_DIR, { recursive: true });
  writeFileSync(SNAPSHOT_OUT, JSON.stringify(snapshot), "utf-8");
  console.log(
    `[content-snapshot] wrote ${SNAPSHOT_OUT} (news items: ${snapshot.news.included_total}, truncated: ${snapshot.news.truncated})`,
  );
}

async function fetchRemote(): Promise<Snapshot> {
  console.log(`[content-snapshot] fetching ${SNAPSHOT_URL}`);
  const res = await fetch(SNAPSHOT_URL, {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) {
    throw new Error(`snapshot fetch failed: HTTP ${res.status}`);
  }
  return validateSnapshot(await res.json());
}

async function main(): Promise<void> {
  if (SNAPSHOT_URL) {
    try {
      writeSnapshot(await fetchRemote());
      return;
    } catch (err) {
      // URL configured but unreachable/invalid → fail fast in CI (the
      // deploy would otherwise ship stale/absent content pages silently).
      if (IS_PRODUCTION_BUILD) {
        console.error(`[content-snapshot] FATAL: ${(err as Error).message}`);
        process.exit(1);
      }
      console.warn(
        `[content-snapshot] fetch failed (${(err as Error).message}) — local fallback`,
      );
    }
  } else if (IS_PRODUCTION_BUILD) {
    // No URL configured → keep the existing deploy pipeline working;
    // content pages simply fall back to SPA/API (opt-in feature).
    console.warn(
      "[content-snapshot] CONTENT_SNAPSHOT_URL not set — content SSG skipped (SPA/API fallback)",
    );
    return;
  }

  if (existsSync(FIXTURE_FILE)) {
    try {
      const raw = JSON.parse(readFileSync(FIXTURE_FILE, "utf-8"));
      writeSnapshot(validateSnapshot(raw));
      console.warn("[content-snapshot] using committed fixture (may be stale)");
      return;
    } catch (err) {
      console.warn(
        `[content-snapshot] fixture invalid (${(err as Error).message}) — skipping`,
      );
    }
  }

  if (IS_PRODUCTION_BUILD) {
    console.warn(
      "[content-snapshot] no fixture committed — content SSG skipped (SPA/API fallback)",
    );
    return;
  }
  console.warn(
    "[content-snapshot] no snapshot source — skipping content SSG (SPA/API fallback)",
  );
}

main().catch((err) => {
  console.error(`[content-snapshot] FATAL: ${(err as Error).message}`);
  process.exit(1);
});
