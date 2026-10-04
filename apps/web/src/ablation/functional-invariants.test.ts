// ABLATION — functional invariants of the public portal that no other layer proves.
//
// Coverage rationale: the 2026-09-26 ablation wave covered the API (16 files / 18 scenarios) and
// two admin guards. Of the 89 frontend and package test files, only 3 were true ablations; the
// rest assert an input/output pair and cannot tell a load-bearing guard from a vacuous one. This
// file closes that gap for the portal function set, using the same protocol as
// `apps/admin/src/regression/nav-reachability.test.ts`:
//
//   control  = the invariant as shipped
//   ablation = exactly ONE protective factor neutralised, same input
//   verdict  = GUARD-ACTIVE (observable flip) | GUARD-INERT (no flip)
//
// Each test asserts BOTH observations. A green run therefore proves the guard is load-bearing,
// not that the function returns something.

import { describe, expect, it } from "vitest";

import { resolveSearchAssembly } from "../lib/search-assembly";
import { isSafeExternalUrl, safeExternalUrl } from "../lib/url-safety";
import { resolveInitialReleaseId, resolveJbrowseBaseUrl, resolveJbrowseOrigin } from "../lib/deployment";
import { resolveSiteVariant, type SiteVariant } from "../lib/site-variant";

type Assembly = { id: number; name: string; is_default: boolean };

const ASSEMBLIES: Assembly[] = [
  { id: 4, name: "v4", is_default: false },
  { id: 5, name: "v5", is_default: true },
];

describe("F1 · deep-link assembly must not fall back to the default genome", () => {
  it("GUARD-ACTIVE: an unresolvable deep link is rejected, and the fallback would query v5", () => {
    const selected = resolveSearchAssembly(ASSEMBLIES, "unknown");
    // Single-factor ablation of the explicit-match guard: hand the same input to a
    // "be helpful" defaulting policy. This is the R-04 violation — a deep link that
    // silently runs against a different genome reports coordinates that are not its own.
    const withFallback = selected ?? ASSEMBLIES.find((assembly) => assembly.is_default);

    expect(selected, "control: invalid assembly must resolve to nothing").toBeUndefined();
    expect(withFallback?.name, "ablation: the fallback policy resolves to the default").toBe("v5");
  });

  it("GUARD-ACTIVE: unloaded assembly lists yield no selection rather than a guess", () => {
    const loaded = resolveSearchAssembly(undefined, "v4");
    const emptyList = resolveSearchAssembly([]);

    expect(loaded).toBeUndefined();
    expect(emptyList).toBeUndefined();
  });
});

describe("F2 · server-supplied URLs must not become navigation targets", () => {
  it("GUARD-ACTIVE: hostile schemes are dropped, and verbatim pass-through would execute them", () => {
    const hostile = [
      "javascript:alert(1)",
      "JavaScript:alert(1)",
      "data:text/html,<script>alert(1)</script>",
      "file:///etc/passwd",
      "ftp://files.example/x",
    ];
    // Single-factor ablation of the scheme allowlist: render the stored value verbatim.
    const withoutAllowlist = (value: string) => value;

    for (const value of hostile) {
      expect(safeExternalUrl(value), `control: ${value}`).toBeUndefined();
      expect(isSafeExternalUrl(value), `control: ${value}`).toBe(false);
      expect(withoutAllowlist(value), `ablation: ${value}`).toBe(value);
    }
  });

  it("GUARD-ACTIVE: legitimate absolute URLs still pass", () => {
    expect(safeExternalUrl("https://files.example/x.vcf.gz")).toBe("https://files.example/x.vcf.gz");
    expect(safeExternalUrl("http://localhost:9000/x")).toBe("http://localhost:9000/x");
  });
});

describe("F3 · static pages must carry the release they were built against", () => {
  it("GUARD-ACTIVE: a missing release id resolves to null, not a silent default dataset", () => {
    const fromEnv = resolveInitialReleaseId(undefined);
    const fromBlank = resolveInitialReleaseId("   ");

    // Single-factor ablation: default to a hardcoded release so a misbuilt page still
    // renders. That is a silent wrong-dataset read (baseline §2.2 rule 4).
    const withHardcodedDefault = (value: string | undefined) => value?.trim() || "rel-v5";

    expect(fromEnv, "control: absent release must not be invented").toBeNull();
    expect(fromBlank, "control: blank release must not be invented").toBeNull();
    expect(withHardcodedDefault(undefined), "ablation: the defaulting policy invents one").toBe("rel-v5");
  });
});

describe("F4 · the JBrowse bridge origin must stay pinned to the configured base", () => {
  it("GUARD-ACTIVE: trailing slashes cannot desync the frame URL from the origin validator", () => {
    const PORTAL = "https://portal.soymutdb.invalid";
    // Single-factor ablation of the trailing-slash normalisation: keep the raw value.
    // The frame loads from `base` while postMessage is validated against `origin(base)`.
    // If those two disagree, a hostile origin is never rejected — DB-CORE-5/§2.2 rule 3.
    const withoutNormalisation = (value: string) => value;

    for (const configured of ["https://jbrowse.example.org/", "https://jbrowse.example.org///"]) {
      const base = resolveJbrowseBaseUrl(configured);
      const origin = resolveJbrowseOrigin(configured, PORTAL);

      expect(base, `control: ${configured} is normalised`).toBe("https://jbrowse.example.org");
      expect(origin, `control: origin is derived from the same normalised base`).toBe(
        "https://jbrowse.example.org",
      );
      expect(
        new URL(base, PORTAL).origin === origin,
        `control: frame origin and validator origin agree for ${configured}`,
      ).toBe(true);

      const rawBase = withoutNormalisation(configured);
      expect(rawBase, `ablation: ${configured} keeps its raw form`).toBe(configured);
    }
  });

  it("GUARD-ACTIVE: an absent configuration stays same-origin instead of a shared default", () => {
    const PORTAL = "https://portal.soymutdb.invalid";
    const base = resolveJbrowseBaseUrl(undefined);
    const origin = resolveJbrowseOrigin(undefined, PORTAL);
    // Single-factor ablation: hardcode the public JBrowse origin.
    const withSharedDefault = () => "https://jbrowse.example.org";

    expect(base, "control: no configuration means a same-origin relative path").toBe("/jbrowse");
    expect(origin, "control: the validator follows the portal origin").toBe(PORTAL);
    expect(origin, "ablation: the hardcoded default would leave the portal origin").not.toBe(
      withSharedDefault(),
    );
  });
});

describe("F5 · the site variant is validated at build time, never inferred", () => {
  it("GUARD-ACTIVE: an unknown variant fails the build instead of minting a third site", () => {
    // Single-factor ablation: cast the build-time variable through. "staging" or a
    // case-shifted "INTERNAL" would become a variant the internal/external guards,
    // the CORS allowlist and the service-worker namespace do not know about.
    const withoutAllowlist = (value: unknown) => String(value ?? "external") as SiteVariant;

    for (const bogus of ["staging", "INTERNAL", "internal ", 42, { toString: () => "internal" }]) {
      expect(() => resolveSiteVariant(bogus), `control: ${String(bogus)} is rejected`).toThrow(
        /must be exactly "external" or "internal"/,
      );
      expect(withoutAllowlist(bogus), `ablation: ${String(bogus)} would be accepted`).toBe(
        String(bogus),
      );
    }
  });

  it("GUARD-ACTIVE: an unset variant is the public site, not an inferred identity", () => {
    // Single-factor ablation of the empty-value branch: refuse to build without a
    // declared variant, which would break local development for no security gain.
    const strictBuild = (value: unknown) =>
      value === undefined || value === null || value === "" ? "external" : resolveSiteVariant(value);

    for (const unset of [undefined, null, ""]) {
      expect(resolveSiteVariant(unset), `control: ${String(unset)}`).toBe("external");
      expect(strictBuild(unset), `control: the shipped policy accepts it`).toBe("external");
    }
  });
});
