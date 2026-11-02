#!/usr/bin/env tsx
/**
 * Fetch the public content snapshot for the external portal artifact.
 *
 * Contract: `GET /content/snapshot` in
 * `apps/api/app/api/v1/content.py` -> `ContentSnapshotService.build_snapshot`.
 * The payload is validated and re-emitted through the public whitelist in
 * `src/lib/static-content-render.ts` before anything is written, so a
 * successful fetch can never copy an unknown or internal field into
 * `data/content.json`.
 *
 * Resolution order (external variant only):
 *   1. `SOYMUTDB_CONTENT_SNAPSHOT_URL`  — HTTP GET with a timeout, a byte cap
 *      and response validation.
 *   2. `SOYMUTDB_CONTENT_SNAPSHOT_FILE` — an already-verified external fixture.
 *   3. Neither configured -> skip with an explicit log. The build keeps
 *      producing exactly the documents it produced before this step existed.
 *
 * Failure policy:
 *   - The internal variant never reaches this code path, and even when it does
 *     the step returns before reading a byte.
 *   - A configured source that fails, answers an unusable response, carries an
 *     unknown `schema_version`, is not `site_variant=external`, or does not
 *     match `SOYMUTDB_RELEASE_ID` is **fail-closed** in a production/CI build:
 *     the step throws and the artifact is not produced.
 *   - In a local build the same failure degrades to a logged skip, so an
 *     unconfigured laptop still builds the portal.
 *
 * Usage: tsx scripts/fetch-content-snapshot.ts   (run per variant by build-sites.ts)
 * Env:   SOYMUTDB_DIST_DIR, VITE_SITE_VARIANT, SOYMUTDB_CONTENT_SNAPSHOT_URL,
 *        SOYMUTDB_CONTENT_SNAPSHOT_FILE, SOYMUTDB_RELEASE_ID
 */

import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  assertSnapshotRelease,
  normalizeContentSnapshot,
  resolveExpectedReleaseId,
  type PublicContentSnapshot,
} from "../src/lib/static-content-render";

/** Hard cap on the snapshot response/file size (API caps 500 articles). */
export const DEFAULT_MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024;

/** Hard cap on the fetch wall clock. */
export const DEFAULT_SNAPSHOT_TIMEOUT_MS = 30_000;

/** Where the whitelisted snapshot is published inside the variant tree. */
export const SNAPSHOT_RELATIVE_PATH = "data/content.json";

export type SnapshotSourceKind = "url" | "file";

export interface SnapshotAcquisition {
  status: "acquired" | "skipped";
  reason?: string;
  source?: SnapshotSourceKind;
  snapshot?: PublicContentSnapshot;
  releaseId?: number;
}

export interface AcquireOptions {
  env: NodeJS.ProcessEnv;
  /** Injected in tests; defaults to the global fetch. */
  fetchImpl?: typeof fetch;
  /** Injected in tests; defaults to a size-capped fs read. */
  readFile?: (path: string, maxBytes: number) => string;
  timeoutMs?: number;
  maxBytes?: number;
  /** Injected in tests; defaults to console.log/console.warn. */
  log?: (message: string) => void;
  warn?: (message: string) => void;
}

/**
 * Production/CI builds fail closed on a configured-but-broken snapshot. A
 * missing configuration is never fatal: the portal builds without static
 * content pages and says so.
 */
export function isProductionBuild(env: NodeJS.ProcessEnv): boolean {
  if (env.CI === "true") return true;
  if ((env.NODE_ENV ?? "").trim() === "production") return true;
  return (env.VITE_DEPLOYMENT_MODE ?? "").trim() === "production";
}

export function resolveSiteVariant(env: NodeJS.ProcessEnv): "external" | "internal" {
  const value = (env.VITE_SITE_VARIANT ?? env.SOYMUTDB_SITE_VARIANT ?? "external")
    .trim()
    .toLowerCase();
  if (value === "external" || value === "internal") return value;
  throw new Error(
    `[content-snapshot] VITE_SITE_VARIANT must be "external" or "internal"; got ${JSON.stringify(value)}`,
  );
}

function defaultReadFile(path: string, maxBytes: number): string {
  const size = statSync(path).size;
  if (size > maxBytes) {
    throw new Error(
      `${path} is ${size} bytes, over the ${maxBytes} byte snapshot limit`,
    );
  }
  return readFileSync(path, "utf8");
}

/**
 * Read a response body with a hard byte cap.
 *
 * `content-length` is only a hint (it can be absent or wrong), so the body is
 * streamed and counted: an endpoint that starts sending an unbounded payload is
 * cancelled mid-flight instead of filling the build machine's memory.
 */
async function readLimitedBody(
  response: Response,
  maxBytes: number,
): Promise<string> {
  const declared = Number(response.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > maxBytes) {
    throw new Error(
      `declared content-length ${declared} exceeds the ${maxBytes} byte snapshot limit`,
    );
  }
  if (!response.body) {
    const text = await response.text();
    if (Buffer.byteLength(text, "utf8") > maxBytes) {
      throw new Error(`response body exceeds the ${maxBytes} byte snapshot limit`);
    }
    return text;
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel().catch(() => undefined);
      throw new Error(`response body exceeds the ${maxBytes} byte snapshot limit`);
    }
    chunks.push(value);
  }
  return Buffer.concat(chunks.map((chunk) => Buffer.from(chunk))).toString("utf8");
}

async function fetchSnapshot(
  url: string,
  options: AcquireOptions,
  maxBytes: number,
): Promise<unknown> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const timeoutMs = options.timeoutMs ?? DEFAULT_SNAPSHOT_TIMEOUT_MS;
  const response = await fetchImpl(url, {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (response.status === 304) {
    throw new Error(
      "the API answered 304 Not Modified; the fetch must not send conditional headers " +
        "(builds always take a full snapshot)",
    );
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} ${response.statusText}`);
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType && !contentType.toLowerCase().includes("json")) {
    throw new Error(
      `unexpected content-type ${JSON.stringify(contentType)}; a proxy or login page ` +
        "answered instead of the snapshot endpoint",
    );
  }
  const body = await readLimitedBody(response, maxBytes);
  try {
    return JSON.parse(body) as unknown;
  } catch (error) {
    throw new Error(`response is not valid JSON: ${(error as Error).message}`);
  }
}

function parseAndValidate(raw: unknown, expectedReleaseId: number | undefined): PublicContentSnapshot {
  const snapshot = normalizeContentSnapshot(raw);
  assertSnapshotRelease(snapshot, expectedReleaseId);
  return snapshot;
}

/**
 * Resolve, validate and (via the caller) publish the snapshot.
 *
 * Returns `{ status: "skipped" }` only when nothing was configured or when a
 * local build could not reach a configured source. Throws when a production
 * build was configured and the source did not produce a usable snapshot.
 */
export async function acquireContentSnapshot(
  options: AcquireOptions,
): Promise<SnapshotAcquisition> {
  const { env } = options;
  const log = options.log ?? ((message: string) => console.log(message));
  const warn = options.warn ?? ((message: string) => console.warn(message));

  // Internal first, before any path is resolved: the internal artifact must
  // never read, copy or embed the external snapshot.
  const variant = resolveSiteVariant(env);
  if (variant === "internal") {
    log(
      "[content-snapshot] internal variant: content snapshot skipped (internal artifacts " +
        "never read the external snapshot)",
    );
    return { status: "skipped", reason: "internal-variant" };
  }

  const production = isProductionBuild(env);
  const maxBytes = options.maxBytes ?? DEFAULT_MAX_SNAPSHOT_BYTES;
  const url = env.SOYMUTDB_CONTENT_SNAPSHOT_URL?.trim() || undefined;
  const file = env.SOYMUTDB_CONTENT_SNAPSHOT_FILE?.trim() || undefined;
  const expectedReleaseId = resolveExpectedReleaseId(env.SOYMUTDB_RELEASE_ID);

  if (!url && !file) {
    log(
      "[content-snapshot] no source configured (SOYMUTDB_CONTENT_SNAPSHOT_URL / " +
        "SOYMUTDB_CONTENT_SNAPSHOT_FILE) — static content pages are not generated; " +
        "/about, /news and /publications keep their SPA/API behaviour",
    );
    return { status: "skipped", reason: "not-configured" };
  }

  if (url) {
    try {
      log(`[content-snapshot] fetching ${url} (timeout ${options.timeoutMs ?? DEFAULT_SNAPSHOT_TIMEOUT_MS} ms, max ${maxBytes} bytes)`);
      const snapshot = parseAndValidate(await fetchSnapshot(url, options, maxBytes), expectedReleaseId);
      return {
        status: "acquired",
        source: "url",
        snapshot,
        releaseId: snapshot.release_id,
      };
    } catch (error) {
      const message = (error as Error).message;
      if (production) {
        throw new Error(
          `[content-snapshot] FATAL: SOYMUTDB_CONTENT_SNAPSHOT_URL is configured but the ` +
            `snapshot could not be used: ${message}`,
        );
      }
      warn(
        `[content-snapshot] fetch failed (${message}) — falling back to the remaining source`,
      );
    }
  }

  if (file) {
    try {
      const readFile = options.readFile ?? defaultReadFile;
      const raw = JSON.parse(readFile(file, maxBytes)) as unknown;
      const snapshot = parseAndValidate(raw, expectedReleaseId);
      return {
        status: "acquired",
        source: "file",
        snapshot,
        releaseId: snapshot.release_id,
      };
    } catch (error) {
      const message = (error as Error).message;
      if (production) {
        throw new Error(
          `[content-snapshot] FATAL: SOYMUTDB_CONTENT_SNAPSHOT_FILE is configured but the ` +
            `snapshot could not be used: ${message}`,
        );
      }
      warn(`[content-snapshot] fixture unusable (${message}) — content pages not generated`);
    }
  }

  return { status: "skipped", reason: production ? "unavailable" : "unavailable-local" };
}

/** Absolute path of the snapshot inside the variant tree being built. */
export function snapshotOutputPath(env: NodeJS.ProcessEnv): string {
  return resolve(
    process.cwd(),
    env.SOYMUTDB_DIST_DIR?.trim() || "dist",
    SNAPSHOT_RELATIVE_PATH,
  );
}

async function main(): Promise<void> {
  const env = process.env;
  const result = await acquireContentSnapshot({ env });

  if (result.status !== "acquired" || !result.snapshot) {
    console.log(
      `[content-snapshot] skipped (${result.reason ?? "unknown"}) — the build continues with ` +
        "the documents generate-static-routes already produced",
    );
    return;
  }

  const target = snapshotOutputPath(env);
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, JSON.stringify(result.snapshot), "utf8");
  console.log(
    `[content-snapshot] wrote ${target} from ${result.source}: ` +
      `${result.snapshot.news.items.length} news item(s), ` +
      `${Object.values(result.snapshot.news_detail).filter((entry) => entry !== null).length} ` +
      `statically generatable detail(s), ${result.snapshot.publications.length} publication(s)` +
      (result.releaseId === undefined ? "" : `, release_id=${result.releaseId}`),
  );
}

const invokedDirectly =
  process.argv[1] !== undefined &&
  resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url));

if (invokedDirectly) {
  main().catch((error: unknown) => {
    console.error((error as Error)?.message ?? String(error));
    process.exit(1);
  });
}
