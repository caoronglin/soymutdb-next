#!/usr/bin/env node
/**
 * Forwards the locale-key parity check to the framework-neutral checker that
 * now owns the catalogs: `@soymutdb/i18n-core/check-locale-keys.mjs`.
 *
 * `@soymutdb/i18n` no longer owns the locale JSON (it moved to i18n-core in the
 * Phase C seam split), but the CI contract in `scripts/test_ci_job_contracts.py`
 * pins this exact path and script. We keep a thin forwarder so that contract
 * stays green without duplicating the checker logic.
 */
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const coreChecker = join(here, "..", "i18n-core", "check-locale-keys.mjs");

// Tolerate a stray `--` exactly like the core checker: pnpm may forward it, and
// a bare `--` would otherwise be read as a file path. Filter it, then dispatch.
const args = process.argv.slice(2).filter((arg) => arg !== "--");
const forwardArgs = args[0] === "--self-test" ? ["--self-test"] : [];

const result = spawnSync(process.execPath, [coreChecker, ...forwardArgs], {
  stdio: "inherit",
});
process.exit(result.status ?? 1);
