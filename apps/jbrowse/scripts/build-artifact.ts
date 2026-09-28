#!/usr/bin/env tsx
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { composeCsp, parseCsp } from "@soymutdb/shared/build/csp";
import { collectInlineScriptHashes } from "@soymutdb/shared/build/csp-hash";
import { injectHeadersOrigins } from "./inject-headers-origins";

const deploymentMode = process.env.VITE_DEPLOYMENT_MODE?.trim().toLowerCase() || "standard";
const distDir = resolve(process.env.SOYMUTDB_DIST_DIR?.trim() || "dist");
const headersPath = resolve(distDir, "_headers");
const headersCspPattern = /^([\t ]*Content-Security-Policy:[\t ]*)(.+)$/m;
const metaTagPattern = /<meta\b[^>]*http-equiv=["']Content-Security-Policy["'][^>]*>/i;

injectHeadersOrigins(
  {
    apiBaseUrl: process.env.VITE_API_BASE_URL,
    dataUrl: process.env.VITE_JBROWSE_DATA_URL,
    portalOrigin: process.env.SOYMUTDB_PORTAL_ORIGIN,
    adminOrigin: process.env.SOYMUTDB_ADMIN_ORIGIN,
    allowPlaceholderOrigins: deploymentMode !== "production",
  },
  headersPath,
);

function withScriptHashes(policy: string, hashes: readonly string[]): string {
  const directives = parseCsp(policy);
  const scriptSources = (directives.get("script-src") ?? ["'self'"]).filter(
    (source) => source !== "'unsafe-inline'",
  );
  directives.set("script-src", [...new Set([...scriptSources, ...hashes])]);
  return composeCsp(Object.fromEntries(directives));
}

function setMetaPolicy(html: string, policy: string, path: string): string {
  const tagMatch = metaTagPattern.exec(html);
  if (!tagMatch) throw new Error(`JBrowse HTML has no CSP meta tag: ${path}`);
  const tag = tagMatch[0];
  const content = /\bcontent="[^"]*"/i;
  if (!content.test(tag)) throw new Error(`JBrowse CSP meta tag has no double-quoted content: ${path}`);
  const escapedPolicy = policy.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
  const nextTag = tag.replace(content, `content="${escapedPolicy}"`);
  return html.replace(tagMatch[0], nextTag);
}

function walkHtml(directory: string): string[] {
  const paths: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) paths.push(...walkHtml(path));
    else if (entry.isFile() && entry.name.endsWith(".html")) paths.push(path);
  }
  return paths;
}

const headers = readFileSync(headersPath, "utf8");
const headerMatch = headersCspPattern.exec(headers);
if (!headerMatch) throw new Error(`JBrowse artifact has no CSP header: ${headersPath}`);
const basePolicy = headerMatch[2].trim();
const allHashes = new Set<string>();
const htmlPaths = walkHtml(distDir);
if (htmlPaths.length === 0) throw new Error(`JBrowse artifact has no HTML documents: ${distDir}`);

for (const path of htmlPaths) {
  const html = readFileSync(path, "utf8");
  const hashes = collectInlineScriptHashes(html);
  for (const hash of hashes) allHashes.add(hash);
  writeFileSync(path, setMetaPolicy(html, withScriptHashes(basePolicy, hashes), path), "utf8");
}

const sitePolicy = withScriptHashes(basePolicy, [...allHashes]);
writeFileSync(
  headersPath,
  headers.replace(headersCspPattern, (_match, prefix: string) => `${prefix}${sitePolicy}`),
  "utf8",
);
