import { describe, expect, it } from "vitest";
import {
  buildCsp,
  buildJbrowseLocusUrl,
  isMinimalSearchPath,
  isSearchTestPreviewEnabled,
  minimalSearchRedirect,
  normalizeBasePath,
  resolveAppUrl,
  resolveAssetUrl,
  resolveDevAllowedHosts,
  requireDeploymentOrigin,
  resolveAnalyticsProvider,
} from "./deployment";

describe("analytics provider selection", () => {
  it("defaults to the platform-native collector when nothing is configured", () => {
    // The first-party `/track.gif` collector needs no third-party script, so a
    // deployment that says nothing must not load a remote beacon.
    expect(resolveAnalyticsProvider(undefined, undefined)).toEqual({
      cloudflare: false,
      reason: "default: platform-native analytics only",
    });
    expect(resolveAnalyticsProvider("", "").cloudflare).toBe(false);
  });

  it("keeps the beacon for a token-only deployment and says so", () => {
    // Continuity, not a silent policy change: a project that already sets the
    // token keeps reporting, and the build tells the operator to make it
    // explicit. Silently dropping configured analytics would be worse than
    // keeping a documented legacy path.
    const selection = resolveAnalyticsProvider(undefined, "abc123");
    expect(selection.cloudflare).toBe(true);
    expect(selection.reason).toContain("legacy:");
    expect(selection.reason).toContain("SOYMUTDB_ANALYTICS_PROVIDER=cloudflare");
  });

  it("turns the beacon off for an explicit native selection even with a token", () => {
    // The decisive case: an operator removes the third-party dependency while
    // the old variable is still present in the environment.
    expect(resolveAnalyticsProvider("native", "abc123")).toEqual({
      cloudflare: false,
      reason: "explicit: platform-native analytics only",
    });
    expect(resolveAnalyticsProvider("NATIVE", "abc123").cloudflare).toBe(false);
  });

  it("enables the beacon for the explicit opt-ins", () => {
    for (const provider of ["cloudflare", "both", " cloudflare "]) {
      expect(resolveAnalyticsProvider(provider, "abc123").cloudflare).toBe(true);
    }
  });

  it("fails the build on an unknown provider instead of falling back", () => {
    // A typo must not quietly change which script a deployed page loads; the
    // same reasoning as `VITE_SITE_VARIANT`.
    expect(() => resolveAnalyticsProvider("cloudfare", "abc123")).toThrow(
      /must be one of native, cloudflare, both/,
    );
    expect(() => resolveAnalyticsProvider("native-only", undefined)).toThrow(
      /must be one of native, cloudflare, both/,
    );
  });

  it("fails the build when a beacon is requested without a token", () => {
    // An empty token reports nothing, which reads as "no traffic" rather than
    // "misconfigured" — the failure has to surface at build time.
    for (const provider of ["cloudflare", "both"]) {
      expect(() => resolveAnalyticsProvider(provider, undefined)).toThrow(
        /requires SOYMUTDB_CLOUDFLARE_ANALYTICS_TOKEN/,
      );
      expect(() => resolveAnalyticsProvider(provider, "   ")).toThrow(
        /requires SOYMUTDB_CLOUDFLARE_ANALYTICS_TOKEN/,
      );
    }
  });
});

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

  it("allows an explicitly configured file viewer to be framed", () => {
    const csp = buildCsp({
      apiOrigin: "https://api.staging.example.org",
      frameOrigins: ["https://viewer.staging.example.org"],
    });
    expect(csp).toContain(
      "frame-src 'self' https://viewer.staging.example.org;",
    );
  });

  it("rejects placeholder origins at build time", () => {
    expect(() => requireDeploymentOrigin("https://api.example.com", "API")).toThrow(
      /placeholder origin/i,
    );
  });
});

describe("minimal search deployment boundary", () => {
  it("allows only the gene ID and physical location search routes", () => {
    expect(isMinimalSearchPath("/search/genes")).toBe(true);
    expect(isMinimalSearchPath("/search/location/")).toBe(true);
    expect(isMinimalSearchPath("/search")).toBe(false);
    expect(isMinimalSearchPath("/genes/Glyma.01G000100")).toBe(false);
    expect(isMinimalSearchPath("/browser")).toBe(false);
  });

  it("redirects every other direct URL to the existing gene search page", () => {
    expect(minimalSearchRedirect("/")).toBe("/search/genes");
    expect(minimalSearchRedirect("/variants")).toBe("/search/genes");
    expect(minimalSearchRedirect("/search/location")).toBeNull();
  });

  it("requires a separate explicit opt-in before reading unpublished search data", () => {
    expect(isSearchTestPreviewEnabled(undefined)).toBe(false);
    expect(isSearchTestPreviewEnabled("minimal")).toBe(false);
    expect(isSearchTestPreviewEnabled("true")).toBe(true);
    expect(isSearchTestPreviewEnabled(" TRUE ")).toBe(true);
  });
});

/**
 * Regression for Issue #10:
 *
 *   Blocked request. This host ("cnb-38o-1k28dm5ta-001.cnb.space") is not
 *   allowed.
 *
 * Vite 6 rejects a request whose `Host` is not in `server.allowedHosts`, and CNB
 * mints a NEW `*.cnb.space` hostname for every cloud development environment. So
 * the allowlist must be a set of patterns that covers hostnames that did not
 * exist when this code was written.
 */
describe("dev-server allowed hosts (CNB preview domains)", () => {
  // Vite's own matching rule: a leading dot means "this domain and every
  // subdomain"; everything else is exact. Reproduced here so the assertions
  // describe the behaviour a browser will actually hit.
  const accepts = (value: string | undefined, host: string): boolean => {
    const hosts = resolveDevAllowedHosts(value);
    if (hosts === true) return true;
    const bare = host.replace(/^\[[^\]]+\]/, "").split(":")[0].toLowerCase();
    return hosts.some((entry) => {
      const pattern = entry.toLowerCase();
      if (pattern.startsWith(".")) {
        return bare === pattern.slice(1) || bare.endsWith(pattern);
      }
      return bare === pattern;
    });
  };

  it("accepts the generated hostname from the blocked-request report", () => {
    expect(accepts(undefined, "cnb-38o-1k28dm5ta-001.cnb.space")).toBe(true);
    expect(accepts(undefined, "cnb-38o-1k28dm5ta-001.cnb.space:8686")).toBe(true);
  });

  it("accepts a hostname no environment has been created for yet", () => {
    // The whole point: hard-coding the reported host fixes one environment.
    expect(accepts(undefined, "some-future-env-id-9f2.cnb.space")).toBe(true);
    expect(accepts(undefined, "fjisdofi21-5173.cnb.run")).toBe(true);
  });

  it("accepts loopback and the platform apexes", () => {
    expect(accepts(undefined, "localhost")).toBe(true);
    expect(accepts(undefined, "localhost:5173")).toBe(true);
    expect(accepts(undefined, "127.0.0.1")).toBe(true);
    expect(accepts(undefined, "cnb.space")).toBe(true);
  });

  it("does not accept an arbitrary host", () => {
    expect(accepts(undefined, "evil.example.com")).toBe(false);
    expect(accepts(undefined, "cnb.space.evil.com")).toBe(false);
    expect(accepts(undefined, "notcnb.space")).toBe(false);
    expect(accepts(undefined, "cnb.spacex")).toBe(false);
  });

  it("never defaults to a wildcard", () => {
    expect(resolveDevAllowedHosts(undefined)).not.toBe(true);
    expect(resolveDevAllowedHosts("")).not.toBe(true);
  });

  it("extends the allowlist additively from the environment", () => {
    expect(accepts("staging.example.com", "staging.example.com")).toBe(true);
    expect(accepts("staging.example.com", "cnb-38o-1k28dm5ta-001.cnb.space")).toBe(true);
    expect(accepts("staging.example.com", "other.example.com")).toBe(false);
  });

  it("normalizes full URLs, ports and whitespace in the override", () => {
    const value = " https://tunnel.foo.io:8080/some/path , second.example.com ";
    expect(accepts(value, "tunnel.foo.io")).toBe(true);
    expect(accepts(value, "second.example.com")).toBe(true);
    expect(accepts(value, "unlisted.example.com")).toBe(false);
  });

  it("treats `true` as the explicit wildcard opt-in", () => {
    expect(resolveDevAllowedHosts("true")).toBe(true);
    expect(resolveDevAllowedHosts("*")).toBe(true);
    expect(accepts("true", "anything.example.com")).toBe(true);
  });
});
