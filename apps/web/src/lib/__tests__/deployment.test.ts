import { describe, expect, it } from "vitest";
import {
  buildCsp,
  buildJbrowseLocusUrl,
  normalizeBasePath,
  resolveAppUrl,
  resolveAssetUrl,
  requireDeploymentOrigin,
} from "../deployment";

describe("deployment URL contract", () => {
  it("normalizes a deployment base and resolves nested SSG resources", () => {
    expect(normalizeBasePath("/soymutdb-next")).toBe("/soymutdb-next/");
    expect(resolveAssetUrl("/soymutdb-next/", "assets/app.js")).toBe(
      "/soymutdb-next/assets/app.js",
    );
    expect(resolveAssetUrl("/soymutdb-next/", "assets/app.js", "/news/item.html")).toBe(
      "/soymutdb-next/assets/app.js",
    );
    expect(resolveAppUrl("/soymutdb-next/", "/login")).toBe("/soymutdb-next/login");
  });

  it("builds a base-aware JBrowse 2 locus deep link", () => {
    const { href } = buildJbrowseLocusUrl("/soymutdb-next/", {
      assembly: "Wm82.a4.v1",
      locus: "chr01:100-200",
    });
    expect(href).toBe("/soymutdb-next/browser?assembly=Wm82.a4.v1&locus=chr01%3A100-200");
  });

  it("builds a JBrowse 2 deep link for a root deployment", () => {
    expect(
      buildJbrowseLocusUrl("/", { assembly: "Wm82.a4.v1", locus: "chr01" }).href,
    ).toBe("/browser?assembly=Wm82.a4.v1&locus=chr01");
  });

  it("builds CSP from real API and JBrowse origins", () => {
    const csp = buildCsp({
      apiOrigin: "https://api.staging.example.org",
      jbrowseOrigin: "https://browser.staging.example.org",
    });
    expect(csp).toContain("connect-src 'self' https://api.staging.example.org");
    expect(csp).toContain("frame-src 'self' https://browser.staging.example.org");
    expect(csp).not.toContain("example.com;");
  });

  it("rejects placeholder origins at build time", () => {
    expect(() => requireDeploymentOrigin("https://api.example.com", "API")).toThrow(
      /placeholder origin/i,
    );
  });
});
