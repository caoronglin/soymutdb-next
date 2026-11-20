#!/usr/bin/env tsx
/**
 * Build the isolated external and internal portal artifacts.
 *
 * Each variant is a complete Umi build of its own: the application shell, the
 * per-route documents, the finalized CSP, the .gz siblings and the service
 * worker. The two trees never share a build step that could carry one
 * variant's configuration into the other.
 */


import { execFileSync } from "node:child_process";
import { rmSync } from "node:fs";
import { join, resolve } from "node:path";

const packageDir = resolve(import.meta.dirname, "..");
const pnpmCommand = process.platform === "win32" ? "pnpm.cmd" : "pnpm";

/**
 * Entities the demo artifact prerenders, as a checked-in snapshot file.
 *
 * `generate-static-routes.ts` emits no entity document unless it is handed a
 * snapshot, and the committed `dist/external/routes.json` is built from the
 * demo tree, so the demo build has to name one explicitly. It is an *input* to
 * the build, not a default inside the generator: a production build gets
 * nothing here and therefore prerenders no entity page until an operator
 * supplies `SOYMUTDB_ENTITY_SNAPSHOT` for the release being deployed. See
 * `docs/dev/published-route-manifest.md` for the re-pin that a new snapshot
 * forces.
 */
const DEMO_ENTITY_SNAPSHOT = join(packageDir, "fixtures", "entity-snapshot.demo.json");

// The PDF viewer loads its worker from `public/pdf.worker.min.mjs` (Umi's
// webpack has no `?url` import convention); refresh that file before building
// either variant so it always matches the installed pdfjs-dist.
execFileSync(process.execPath, ["scripts/sync-pdf-worker.mjs"], {
  cwd: packageDir,
  stdio: "inherit",
});

function buildVariant(variant: "external" | "internal") {
  const isExternal = variant === "external";
  // A production build publishes only what an operator points it at: the demo
  // entity snapshot is a demo-build input, never a production default.
  const isProduction =
    (process.env.VITE_DEPLOYMENT_MODE || "demo").trim().toLowerCase() === "production";
  // The remote-preview provider is configured with non-VITE inputs and mapped
  // to this build only. Letting both variants read one shared VITE_* value would
  // put the internal viewer origin into the public artifact (and vice versa),
  // and `config.ts` inlines every key of its `viteEnv` object.
  const fileViewerUrl = isExternal
    ? process.env["SOYMUTDB_EXTERNAL_FILE_VIEWER_URL"]?.trim() || ""
    : process.env["SOYMUTDB_INTERNAL_FILE_VIEWER_URL"]?.trim() || "";
  const fileViewerOrigins = isExternal
    ? process.env["SOYMUTDB_EXTERNAL_FILE_VIEWER_ARTIFACT_ORIGINS"]?.trim() || ""
    : process.env["SOYMUTDB_INTERNAL_FILE_VIEWER_ARTIFACT_ORIGINS"]?.trim() || "";
  const env = {
    ...process.env,
    VITE_DEPLOYMENT_MODE: process.env.VITE_DEPLOYMENT_MODE || "demo",
    VITE_SITE_VARIANT: variant,
    VITE_FILE_VIEWER_URL: fileViewerUrl,
    VITE_FILE_VIEWER_ARTIFACT_ORIGINS: fileViewerOrigins,
    VITE_BASE_URL: isExternal
      ? process.env["SOYMUTDB_EXTERNAL_BASE_URL"] || process.env.VITE_BASE_URL || "/"
      : process.env["SOYMUTDB_INTERNAL_BASE_URL"] ||
        process.env.VITE_INTERNAL_BASE_URL ||
        process.env.VITE_BASE_URL ||
        "/",
    VITE_API_BASE_URL: isExternal
      ? process.env["SOYMUTDB_EXTERNAL_API_URL"] ||
        process.env.VITE_API_BASE_URL ||
        "https://api.external.soymutdb.test"
      : process.env["SOYMUTDB_INTERNAL_API_URL"] || "https://api.internal.soymutdb.test",
    VITE_JBROWSE_BASE_URL: isExternal
      ? process.env["SOYMUTDB_EXTERNAL_JBROWSE_URL"] ||
        process.env.VITE_JBROWSE_BASE_URL ||
        "https://jbrowse.external.soymutdb.test"
      : process.env["SOYMUTDB_INTERNAL_JBROWSE_URL"] ||
        "https://jbrowse.internal.soymutdb.test",
    SOYMUTDB_DIST_DIR: `dist/${variant}`,
    SOYMUTDB_SITE_URL: isExternal
      ? process.env["SOYMUTDB_SITE_URL"] || process.env["SOYMUTDB_PORTAL_ORIGIN"] || "https://external.soymutdb.invalid"
      : process.env["SOYMUTDB_INTERNAL_SITE_URL"] || "https://internal.soymutdb.invalid",
    // External variant only, like the content snapshot: the internal artifact
    // never publishes a record document, so it never reads the file.
    SOYMUTDB_ENTITY_SNAPSHOT: isExternal
      ? process.env["SOYMUTDB_ENTITY_SNAPSHOT"] ??
        (isProduction ? "" : DEMO_ENTITY_SNAPSHOT)
      : "",
  };

  console.log(`[sites] building ${variant} artifact`);
  execFileSync(pnpmCommand, ["exec", "max", "build"], {
    cwd: packageDir,
    env,
    stdio: "inherit",
  });
  execFileSync(pnpmCommand, ["exec", "tsx", "scripts/generate-static-routes.ts"], {
    cwd: packageDir,
    env,
    stdio: "inherit",
  });
  // Public content pages, external variant only. These two steps write HTML,
  // so they must run before finalize-csp hashes the documents; the internal
  // variant is skipped entirely rather than being handed the external
  // snapshot. With no SOYMUTDB_CONTENT_SNAPSHOT_URL / _FILE configured both
  // steps log an explicit skip and the artifacts stay exactly as the static
  // route generator left them.
  if (isExternal) {
    execFileSync(pnpmCommand, ["exec", "tsx", "scripts/fetch-content-snapshot.ts"], {
      cwd: packageDir,
      env,
      stdio: "inherit",
    });
    execFileSync(pnpmCommand, ["exec", "tsx", "scripts/content-snapshot-build.ts"], {
      cwd: packageDir,
      env,
      stdio: "inherit",
    });
  }
  // The rest of the chain is the same one `pnpm build` runs, in the same order:
  // CSP finalization must come after the last HTML writer, and the .gz siblings
  // and the service worker derive from the final bytes. Skipping it here shipped
  // variant trees whose meta policy still allowed 'unsafe-inline'.
  execFileSync(pnpmCommand, ["exec", "tsx", "scripts/finalize-csp.ts"], {
    cwd: packageDir,
    env,
    stdio: "inherit",
  });
  // Unconditional: every tree this repo serves is served from a host that
  // answers `Accept-Encoding: gzip` with these siblings (nginx gzip_static, the
  // two preview servers). `SOYMUTDB_EMIT_GZ=0` is the opt-out and lives inside
  // the script, so the two paths cannot disagree about whether it ran.
  execFileSync(pnpmCommand, ["exec", "tsx", "scripts/gzip-compress.ts"], {
    cwd: packageDir,
    env,
    stdio: "inherit",
  });
  execFileSync(pnpmCommand, ["exec", "node", "scripts/gen-sw.js"], {
    cwd: packageDir,
    env,
    stdio: "inherit",
  });
  execFileSync(pnpmCommand, ["exec", "tsx", "scripts/release-manifest.ts"], {
    cwd: packageDir,
    env,
    stdio: "inherit",
  });
}

// A prior single-site max build leaves root-level HTML, headers and assets.
// Publish only the two fresh variant trees, without stale root-level policies.
rmSync(resolve(packageDir, "dist"), { recursive: true, force: true });

buildVariant("external");
buildVariant("internal");
console.log("[sites] external and internal artifacts built");
