#!/usr/bin/env node
/**
 * Service Worker 生成脚本 — 构建链最后一步（apps/web/package.json "build"）
 *
 * 流程：
 *   1. 扫描 dist 下的 content-hashed bundles（排除 .gz / .map）→ precache 清单（相对路径）
 *   2. CACHE_VERSION = 构建时间戳 + 清单内容 hash（产物内容变化 → 版本号轮换）
 *   3. 读取 public/sw.js 模板，替换 __PRECACHE_MANIFEST__ / __CACHE_VERSION__
 *   4. 输出 dist/sw.js，并同步刷新 dist/sw.js.gz（gzip-compress 在更早步骤运行，
 *      它压缩的是未替换占位符的模板版本，这里必须覆盖，避免部署 stale 的 .gz）。
 *      .gz 仅在 SOYMUTDB_EMIT_GZ=1（容器路径）时生成；其它路径只删除遗留 .gz。
 *
 * 路径约定：清单使用相对路径，SW 运行时以 registration.scope 为
 * 基准解析，因此能够跟随 Umi base/publicPath 的部署前缀工作。
 *
 * 使用：pnpm --filter @soymutdb/web build（自动串联）；也可单独
 *       `node scripts/gen-sw.js`（在 apps/web 目录下）。
 */

import { existsSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join, posix, resolve } from "node:path";
import { createHash } from "node:crypto";
import { gzipSync } from "node:zlib";

/* ------------------------------------------------------------------ */
/*  Configuration                                                     */
/* ------------------------------------------------------------------ */

const ROOT = process.cwd();
const TEMPLATE = join(ROOT, "public", "sw.js");
const DIST_DIR = resolve(ROOT, process.env.SOYMUTDB_DIST_DIR ?? "dist");
const OUT_FILE = join(DIST_DIR, "sw.js");
const OUT_GZ = `${OUT_FILE}.gz`;
// 仅容器路径产出 .gz（nginx gzip_static）；Pages/gh-pages 不读取 .gz。
const EMIT_GZ = process.env.SOYMUTDB_EMIT_GZ === "1";
// The external and internal artifacts are separate deployments with separate
// caches (AGENTS.md cache boundary). The version string therefore carries the
// site variant, so a variant's cache name can never collide with the other's.
const SITE_VARIANT = (process.env.VITE_SITE_VARIANT ?? "external").trim().toLowerCase();
if (SITE_VARIANT !== "external" && SITE_VARIANT !== "internal") {
    throw new Error(`[gen-sw] VITE_SITE_VARIANT must be external or internal, got "${SITE_VARIANT}"`);
}

/* ------------------------------------------------------------------ */
/*  Main                                                              */
/* ------------------------------------------------------------------ */

function main() {
    if (!existsSync(TEMPLATE)) {
        throw new Error(`[gen-sw] template not found: ${TEMPLATE}`);
    }
    if (!existsSync(DIST_DIR)) {
        throw new Error(`[gen-sw] ${DIST_DIR} does not exist — run the frontend build first`);
    }

    // 1) Umi emits content-hashed bundles at the dist root; keep supporting the
    // prior /assets layout while discovering hashed output at any depth.
    function collectHashedAssets(directory, relativeDirectory = "") {
        const files = [];
        for (const entry of readdirSync(directory, { withFileTypes: true })) {
            const relativePath = posix.join(relativeDirectory, entry.name);
            if (entry.isDirectory()) {
                files.push(...collectHashedAssets(join(directory, entry.name), relativePath));
                continue;
            }
            if (
                !entry.isFile() ||
                entry.name === "sw.js" ||
                entry.name.endsWith(".gz") ||
                entry.name.endsWith(".map") ||
                !/(?:^|[._-])[a-f0-9]{8,}(?:[._-]|$)/i.test(entry.name)
            ) {
                continue;
            }
            files.push(relativePath);
        }
        return files;
    }
    const manifest = collectHashedAssets(DIST_DIR).sort();
    if (manifest.length === 0) {
        throw new Error(`[gen-sw] no content-hashed assets under ${DIST_DIR} — run the frontend build first`);
    }

    // 2) CACHE_VERSION：时间戳 + 清单内容 hash（hash 变化 → 版本轮换 → 旧静态缓存被清理）
    const digest = createHash("sha256").update(manifest.join("\n")).digest("hex").slice(0, 8);
    const timestamp = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
    const version = `${timestamp}-${digest}`;

    // 3) 读模板并替换占位符
    let sw = readFileSync(TEMPLATE, "utf8");
    const manifestJson = JSON.stringify(manifest, null, 4);
    if (
        !sw.includes("__PRECACHE_MANIFEST__") ||
        !sw.includes("__CACHE_VERSION__") ||
        !sw.includes("__SW_NAMESPACE__")
    ) {
        throw new Error(
            "[gen-sw] template placeholders (__PRECACHE_MANIFEST__ / __CACHE_VERSION__ / __SW_NAMESPACE__) missing",
        );
    }
    sw = sw.replace("__PRECACHE_MANIFEST__", manifestJson);
    sw = sw.replace("__CACHE_VERSION__", `${SITE_VARIANT}-${version}`);
    // 变体名进运行时缓存与清理前缀：外部站/内网站的缓存互不可见（DB-CORE-5）。
    sw = sw.replace("__SW_NAMESPACE__", SITE_VARIANT);

    // 4) 输出 dist/sw.js + 同步 .gz（与 gzip-compress 相同规则：≥1KB 且压缩变小）
    writeFileSync(OUT_FILE, sw, "utf8");
    // 旧 .gz 是模板版本，必须删除/重生成；不产出 .gz 时也必须删除，
    // 否则 gzip_static 会把上一次容器构建的 sw.js.gz 当成当前 SW 发出去。
    rmSync(OUT_GZ, { force: true });
    if (EMIT_GZ && Buffer.byteLength(sw) >= 1024) {
        const gz = gzipSync(sw, { level: 9 });
        if (gz.length < Buffer.byteLength(sw)) {
            writeFileSync(OUT_GZ, gz);
        }
    }

    console.log(`[gen-sw] wrote ${OUT_FILE} (${(Buffer.byteLength(sw) / 1024).toFixed(1)} KB)`);
    console.log(`[gen-sw] cache version: ${version}`);
    console.log(`[gen-sw] precache manifest: ${manifest.length} files (${manifest.slice(0, 3).join(", ")}${manifest.length > 3 ? ", …" : ""})`);
}

try {
    main();
} catch (err) {
    console.error(String(err?.message ?? err));
    process.exit(1);
}
