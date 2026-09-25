#!/usr/bin/env tsx
/** Build isolated external and internal Vue portal artifacts. */

import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

const packageDir = resolve(import.meta.dirname, "..");
const pnpmCommand = process.platform === "win32" ? "pnpm.cmd" : "pnpm";

function buildVariant(variant: "external" | "internal") {
  const isExternal = variant === "external";
  const env = {
    ...process.env,
    VITE_DEPLOYMENT_MODE: process.env.VITE_DEPLOYMENT_MODE || "demo",
    VITE_SITE_VARIANT: variant,
    VITE_BASE_URL: process.env.VITE_BASE_URL || "/",
    VITE_API_BASE_URL: isExternal
      ? process.env["SOYMUTDB_EXTERNAL_API_URL"] || "https://api.external.soymutdb.test"
      : process.env["SOYMUTDB_INTERNAL_API_URL"] || "https://api.internal.soymutdb.test",
    VITE_JBROWSE_BASE_URL: isExternal
      ? process.env["SOYMUTDB_EXTERNAL_JBROWSE_URL"] || "https://jbrowse.external.soymutdb.test"
      : process.env["SOYMUTDB_INTERNAL_JBROWSE_URL"] || "https://jbrowse.internal.soymutdb.test",
    SOYMUTDB_VUE_DIST_DIR: `dist/${variant}`,
    SOYMUTDB_SITE_URL: isExternal
      ? process.env["SOYMUTDB_SITE_URL"] || "https://external.soymutdb.invalid"
      : process.env["SOYMUTDB_INTERNAL_SITE_URL"] || "https://internal.soymutdb.invalid",
  };

  console.log(`[vue-sites] building ${variant} artifact`);
  execFileSync(pnpmCommand, ["exec", "vite", "build"], {
    cwd: packageDir,
    env,
    stdio: "inherit",
  });
  execFileSync(pnpmCommand, ["exec", "tsx", "scripts/generate-static-routes.ts"], {
    cwd: packageDir,
    env,
    stdio: "inherit",
  });
}

buildVariant("external");
buildVariant("internal");
console.log("[vue-sites] external and internal artifacts built");
