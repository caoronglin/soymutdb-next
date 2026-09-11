#!/usr/bin/env tsx
/**
 * Gzip Compression Script
 *
 * Finds all .html, .css, .js, .svg, .json, .xml files in dist/ and
 * creates pre-compressed .gz equivalents alongside them (like `gzip -k`).
 *
 * Web servers (nginx, Caddy, Cloudflare, etc.) can serve these files
 * directly with Content-Encoding: gzip for zero-CPU static delivery.
 *
 * Skips files that already have a newer .gz counterpart and compresses
 * at level 9 (maximum) since build time is not latency-sensitive.
 */

import { readdirSync, statSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { gzipSync } from "node:zlib";

/* ------------------------------------------------------------------ */
/*  Configuration                                                     */
/* ------------------------------------------------------------------ */

const DIST_DIR = resolve(process.cwd(), process.env.SOYMUTDB_DIST_DIR ?? "dist");
const COMPRESS_EXTENSIONS = new Set([
    ".html",
    ".css",
    ".js",
    ".svg",
    ".json",
    ".xml",
    ".txt",
    ".map",
]);
const MIN_SIZE = 1024; // Don't bother compressing tiny files (< 1 KB)
const COMPRESS_LEVEL = 9;

/* ------------------------------------------------------------------ */
/*  Walker                                                            */
/* ------------------------------------------------------------------ */

function* walk(dir: string): Generator<string> {
    let entries: string[];
    try {
        entries = readdirSync(dir);
    } catch {
        return;
    }
    for (const entry of entries) {
        const full = join(dir, entry);
        const st = statSync(full);
        if (st.isDirectory()) {
            // Skip node_modules, source map dirs, etc.
            if (entry === "node_modules" || entry.startsWith(".")) continue;
            yield* walk(full);
        } else if (st.isFile()) {
            yield full;
        }
    }
}

/* ------------------------------------------------------------------ */
/*  Main                                                              */
/* ------------------------------------------------------------------ */

function compress() {
    if (!existsSync(DIST_DIR)) {
        console.warn(`[ssg:compress] ${DIST_DIR} does not exist — nothing to compress.`);
        return;
    }

    let compressed = 0;
    let skipped = 0;
    let totalOriginal = 0;
    let totalCompressed = 0;

    for (const filePath of walk(DIST_DIR)) {
        // Skip already-compressed files
        if (filePath.endsWith(".gz")) {
            skipped++;
            continue;
        }

        const ext = filePath.slice(filePath.lastIndexOf("."));
        if (!COMPRESS_EXTENSIONS.has(ext)) {
            skipped++;
            continue;
        }

        const st = statSync(filePath);
        if (st.size < MIN_SIZE) {
            skipped++;
            continue;
        }

        const gzPath = `${filePath}.gz`;

        // Skip if .gz exists and is newer
        if (existsSync(gzPath)) {
            const gzSt = statSync(gzPath);
            if (gzSt.mtimeMs >= st.mtimeMs) {
                skipped++;
                continue;
            }
        }

        const original = readFileSync(filePath);
        const compressedData = gzipSync(original, { level: COMPRESS_LEVEL });

        // Don't write if compression made it larger
        if (compressedData.length >= original.length) {
            skipped++;
            continue;
        }

        writeFileSync(gzPath, compressedData);

        totalOriginal += original.length;
        totalCompressed += compressedData.length;
        compressed++;

        const pct = ((1 - compressedData.length / original.length) * 100).toFixed(1);
        console.log(
            `[ssg:compress] ${relative(DIST_DIR, filePath)}: ${(original.length / 1024).toFixed(1)} KB → ${(compressedData.length / 1024).toFixed(1)} KB (${pct}% reduction)`,
        );
    }

    console.log(
        `[ssg:compress] Done. ${compressed} files compressed, ${skipped} skipped. ` +
            `Total saved: ${((totalOriginal - totalCompressed) / 1024).toFixed(1)} KB ` +
            `(${(totalOriginal > 0 ? (1 - totalCompressed / totalOriginal) * 100 : 0).toFixed(1)}% reduction).`,
    );
}

compress();
