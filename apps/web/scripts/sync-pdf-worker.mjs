#!/usr/bin/env node
/**
 * Copy the pdf.js worker into `apps/web/public/`.
 *
 * Umi/webpack does not implement Vite's `?url` import convention, so the old
 * `import("pdfjs-dist/build/pdf.worker.min.mjs?url")` bundled the worker as
 * application JS instead of emitting it as a static asset. The viewer now
 * points `GlobalWorkerOptions.workerSrc` at the public file, which Umi copies
 * verbatim into both site artifacts.
 *
 * Runs before `dev` and at the start of `build-sites.ts`, so the public copy is
 * always fresh for the installed pdfjs-dist version.
 */
import { createRequire } from "node:module";
import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

const packageDir = resolve(import.meta.dirname, "..");
const require = createRequire(resolve(packageDir, "package.json"));
const workerSource = require.resolve("pdfjs-dist/build/pdf.worker.min.mjs");
const targetDir = resolve(packageDir, "public");
const target = resolve(targetDir, "pdf.worker.min.mjs");

mkdirSync(targetDir, { recursive: true });
copyFileSync(workerSource, target);

const bytes = readFileSync(target).byteLength;
console.log(`[pdf-worker] copied pdf.worker.min.mjs (${bytes} bytes) to public/`);
