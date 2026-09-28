#!/usr/bin/env tsx
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { requireDeploymentOrigin } from "@soymutdb/shared/deployment";

const apiOrigin = requireDeploymentOrigin(
  process.env.VITE_API_BASE_URL,
  "Admin API",
  { allowInsecureHttp: process.env.NODE_ENV === "development" },
);
const distDir = resolve(process.env.SOYMUTDB_DIST_DIR?.trim() || "dist");
const headersPath = resolve(distDir, "_headers");
const headers = readFileSync(headersPath, "utf8");
const cspLine = /^([\t ]*Content-Security-Policy:[\t ]*)(.+)$/m;
if (!cspLine.test(headers)) {
  throw new Error(`Admin artifact has no Content-Security-Policy header: ${headersPath}`);
}
const finalized = headers.replace(cspLine, (_match, prefix: string, policy: string) => {
  if (!policy.includes("frame-ancestors 'none'")) {
    throw new Error("Admin CSP must keep frame-ancestors 'none'");
  }
  return `${prefix}${policy.replace(/connect-src[^;]*/, `connect-src 'self' ${apiOrigin}`)}`;
});
writeFileSync(headersPath, finalized, "utf8");
