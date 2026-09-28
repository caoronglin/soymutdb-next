// @vitest-environment node
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * Guards the service-worker namespace isolation between the two site variants.
 *
 * DB-CORE-5 requires the external and internal variants to keep their service
 * worker namespaces and caches separate. The builds ship different navigation
 * HTML (the internal one carries private records), so a cache name that does not
 * carry the variant would hand internal pages to an external visitor the moment
 * the two artifacts shared an origin. The variant is injected at build time by
 * `scripts/gen-sw.js`; this test keeps the template from quietly regressing to a
 * variant-agnostic name.
 */
const here = dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = join(here, "..", "..");

const template = readFileSync(join(WEB_ROOT, "public", "sw.js"), "utf-8");
const generator = readFileSync(join(WEB_ROOT, "scripts", "gen-sw.js"), "utf-8");

describe("service worker namespace isolation (DB-CORE-5)", () => {
  it("injects the site variant into the worker", () => {
    expect(template).toContain("__SW_NAMESPACE__");
    expect(generator).toContain("__SW_NAMESPACE__");
    expect(generator).toMatch(/replace\(\s*"__SW_NAMESPACE__"\s*,\s*SITE_VARIANT\s*\)/);
  });

  it("never names a cache without the variant", () => {
    // A bare "soymutdb-runtime" / "soymutdb-static-v..." literal is the bug this
    // guards: it is shared by every variant built from this template.
    expect(template).not.toMatch(/"soymutdb-runtime"/);
    expect(template).not.toMatch(/"soymutdb-static-v"/);
    expect(template).toContain("soymutdb-runtime-${SW_NAMESPACE}");
    expect(template).toContain("soymutdb-static-v${CACHE_VERSION}");
  });

  it("scopes the stale-cache sweep to this variant", () => {
    expect(template).toContain("k.startsWith(`soymutdb-static-v${SW_NAMESPACE}`)");
    expect(template).not.toContain('k.startsWith("soymutdb-static-v")');
  });

  it("never caches API traffic, including a bare /api path", () => {
    // `includes("/api/")` missed the minimal `VITE_API_BASE_URL` form: the bare
    // `/api` request fell through to stale-while-revalidate and landed in the
    // runtime cache, where a `private, no-store` API response stops being
    // private once it is written to disk.
    expect(template).toContain('/(?:^|\\/)api(?:\\/|$)/.test(pathname)');
    expect(template).not.toContain('pathname.includes("/api/")');
  });
});
