/**
 * Shared helpers for the public-artifact suites.
 *
 * The web artifact is a replacement-render SPA: the build-time prerendered
 * markup is inert and only becomes interactive after React's first commit
 * ("handoff"). `apps/web/src/react-app.tsx` (`AppReadySignal`) announces that
 * boundary on `<html data-app-ready>`, so a spec must wait for it before
 * interacting — otherwise a click can land on the static fallback and be
 * silently discarded.
 */
import { expect, type Page, type Request } from "@playwright/test";

/**
 * Wait until the SPA owns the document. Fails with a clear message instead of
 * letting subsequent locator actions time out on inert markup.
 */
export async function waitForAppReady(page: Page): Promise<void> {
  await expect
    .poll(
      () => page.evaluate(() => document.documentElement.dataset.appReady ?? null),
      {
        message:
          "the SPA never announced readiness (<html data-app-ready>) — the artifact stayed on inert SSG markup",
        timeout: 15_000,
      },
    )
    .toBe("true");
}

/** Navigate to a route and wait for the interactive document. */
export async function gotoReady(page: Page, url: string): Promise<void> {
  await page.goto(url);
  await waitForAppReady(page);
}

/**
 * Console/pageerror classes that are environment or browser-security noise
 * rather than script bugs. A cross-origin deployment surfaces a failed request
 * as a console error even though the app renders its handled error state, and
 * the SSG CSP meta emits a frame-ancestors warning on every page.
 */
export const TOLERATED_CONSOLE_ERRORS: readonly RegExp[] = [
  /Failed to load resource/i,
  /net::ERR_/i,
  /ERR_ABORTED/i,
  /Failed to fetch/i,
  /NetworkError/i,
  /Load failed/i,
  /frame-ancestors/i,
];

/**
 * Record unexpected console errors and pageerrors until the end of the test.
 * A non-empty result is a regression; compare it with `toEqual([])`.
 */
export function trackErrors(
  page: Page,
  tolerated: readonly RegExp[] = TOLERATED_CONSOLE_ERRORS,
): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (tolerated.some((pattern) => pattern.test(text))) return;
    errors.push(`console: ${text}`);
  });
  return errors;
}

// ---------------------------------------------------------------------------
// Deterministic biological mocks (no backend required)
// ---------------------------------------------------------------------------

/**
 * The single assembly every mocked request is scoped to. The id and the name
 * are intentionally different strings so a spec can prove the id scopes the
 * request while the name is what the UI renders and the deep link carries.
 */
export const MOCK_ASSEMBLY = Object.freeze({
  id: "1",
  name: "Wm82.a4.v1",
  species: "Glycine max",
  version: "a4.v1",
  is_default: true,
});

/** Unpublished source fixture: never mix its coordinates with Wm82.a4.v1. */
export const MOCK_PREVIEW_ASSEMBLY = Object.freeze({
  id: "6",
  name: "Gmax_880_v6.0",
  species: "Glycine max",
  version: "v6.0",
  is_default: false,
});

export const MOCK_GENE_ID = "Glyma.01G000100";
/** Release the mocked API pins in its `X-SoyMutDB-Release` response header. */
export const MOCK_RELEASE_ID = "7";
export const MOCK_MUTANT_PUBLIC_ID = "SMDB-00001";
export const MOCK_MUTANT_INTERNAL_ID = "INT-MUT-000001";
export const MOCK_VARIANT_ID = "Wm82.a4.v1_01_000123";

/** One gene result row. `position`/`end_position` drive the JBrowse action. */
const MOCK_GENE_ROW = Object.freeze({
  id: "101",
  gene_id: MOCK_GENE_ID,
  symbol: null,
  name: "Mock gene 1",
  biotype: "protein_coding",
  assembly_id: MOCK_ASSEMBLY.id,
  assembly_name: MOCK_ASSEMBLY.name,
  chromosome: "chr01",
  start_pos: 100,
  end_pos: 200,
  strand: "+",
  description: "A deterministic offline gene row.",
  variant_count: 2,
  high_impact_variants: 1,
  // ConfigurableTable's JBrowse action reads these raw keys directly; the API
  // list schema carries them so the action is not silently rendered as "—".
  position: 100,
  end_position: 200,
});

const MOCK_MUTANT_ROW = Object.freeze({
  public_id: MOCK_MUTANT_PUBLIC_ID,
  name: "Mock mutant line 1",
  mutagen: "EMS",
  cultivar: "Williams 82",
  variant_count: 3,
});

const MOCK_VARIANT_ROW = Object.freeze({
  variant_id: MOCK_VARIANT_ID,
  chromosome: "chr01",
  position: 150,
  ref_allele: "A",
  alt_allele: "G",
  variant_type: "SNV",
  impact: "HIGH",
  consequence: "missense_variant",
  gene_id: MOCK_GENE_ID,
  assembly: MOCK_ASSEMBLY.name,
  assembly_id: MOCK_ASSEMBLY.id,
  release_id: "7",
});

/**
 * Deterministic API mock for the primer-design page.
 *
 * The built portal bakes an ABSOLUTE API origin, so the static server's
 * same-origin `/api/v1/...` mocks never see these requests. This in-browser
 * route fulfils only what the page needs (assemblies, chromosomes, seqfetch,
 * active release) with CORS headers so the cross-origin fetches succeed, and
 * 404s everything else instead of inventing data.
 */
export async function mockPrimerApis(page: Page): Promise<void> {
  const sequence = "ACGTACGTACGTACGTACGT".repeat(15); // GC-balanced 300 bp
  await page.route(/\/api\/v1\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const origin = request.headers()["origin"];
    const headers: Record<string, string> = {
      "access-control-allow-origin": origin ?? "*",
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "authorization,content-type,x-soymutdb-release",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-expose-headers": "x-soymutdb-release",
      vary: "Origin",
      "x-soymutdb-release": MOCK_RELEASE_ID,
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", headers, body: JSON.stringify(body) });
    const path = url.pathname;
    if (path.endsWith("/genes/assemblies")) return json([MOCK_ASSEMBLY]);
    if (/\/genes\/assemblies\/[^/]+\/chromosomes$/.test(path)) {
      return json([{ id: "1", assembly_id: "1", name: "chr01", length: 100000, order: 0 }]);
    }
    if (path.endsWith("/tools/seqfetch")) {
      return json({
        format: "fasta",
        sequence: `>mock chr01:1-300\n${sequence}`,
        count: 1,
        truncated: false,
        missing: [],
      });
    }
    // No `releases/active` mock on purpose. A fabricated release id changes the
    // deployment context: after a reload the assembly query is released-scoped
    // and the primer page's assemblies stop resolving (proved with the page's
    // own requests). A 404 — the static-server baseline — leaves the release
    // unpinned and the page falls back to the default assembly, which is the
    // offline contract these specs assert.
    return json({}, 404);
  });
}

/**
 * Deterministic API mock for the standalone genome browser.
 *
 * The artifact bakes an absolute API origin, so the static server's same-origin
 * mocks never see these requests. The assembly uses JBrowse's
 * `FromConfigSequenceAdapter` (inline sequence data), which lets the linear
 * genome view initialise without any `/jbrowse-data` files on disk — the point
 * of this mock is to prove the BROWSER renders a real view, not to serve genome
 * data the repository does not ship.
 *
 * Deliberately no `/releases/active` mock: a fabricated release changes the
 * deployment context (proven with the primer page); a 404 leaves the release
 * unpinned, which is the offline contract.
 */
export async function mockJbrowseApis(page: Page): Promise<void> {
  const sequence = "ACGT".repeat(1000); // 4 kb inline reference sequence
  await page.route(/\/api\/v1\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const origin = request.headers()["origin"];
    const headers: Record<string, string> = {
      "access-control-allow-origin": origin ?? "*",
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "authorization,content-type,x-soymutdb-release",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-expose-headers": "x-soymutdb-release",
      vary: "Origin",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", headers, body: JSON.stringify(body) });
    const path = url.pathname;
    if (path.endsWith("/genes/assemblies")) return json([MOCK_ASSEMBLY]);
    if (path.endsWith("/tracks/jbrowse-config")) {
      return json({
        assembly: {
          name: MOCK_ASSEMBLY.name,
          aliases: [MOCK_ASSEMBLY.version],
          sequence: {
            trackId: "reference_sequence",
            type: "ReferenceSequenceTrack",
            adapter: {
              type: "FromConfigSequenceAdapter",
              features: [{ refName: "chr01", start: 0, end: sequence.length, seq: sequence }],
            },
          },
        },
        tracks: [],
      });
    }
    return json({}, 404);
  });
  // No genome data files are shipped for the offline artifact: fail them fast
  // instead of leaving track adapters waiting on the static server.
  await page.route(/\/jbrowse-data\//, (route) => route.fulfill({ status: 404, body: "" }));
}

/** A request captured by {@link mockEntityApis}, for context-consistency checks. */
export interface CapturedApiRequest {
  method: string;
  pathname: string;
  search: string;
  releaseHeader: string | null;
  authorizationHeader: string | null;
  request: Request;
}

/** Paths/streams this mock owns; anything else falls through to the network. */
function isMockedApiRequest(url: URL): boolean {
  if (url.pathname.includes("/api/v1/")) return true;
  // The internal artifact bakes an origin-only API base (no /api/v1), so match
  // that host explicitly instead of assuming a path shape.
  if (url.hostname === "api.internal.soymutdb.test") return true;
  return false;
}

/**
 * Serve the entity list/search/detail APIs from an in-browser route so real
 * result rows, their detail links and the detail payloads render with no
 * backend. Every mocked request is recorded so a spec can assert that the
 * assembly / release context did not change between the search and the detail
 * hop.
 *
 * The handler is path-based, not origin-based: the public artifact mounts the
 * API under its deployment sub-path while the internal artifact bakes an
 * absolute origin. Cross-origin (internal) requests get CORS headers and an
 * OPTIONS preflight, since the browser enforces CORS even for fulfilled routes.
 */
export async function mockEntityApis(
  page: Page,
  options: { assembly?: typeof MOCK_ASSEMBLY | typeof MOCK_PREVIEW_ASSEMBLY } = {},
): Promise<CapturedApiRequest[]> {
  const captured: CapturedApiRequest[] = [];
  const assembly = options.assembly ?? MOCK_ASSEMBLY;
  const geneRow = { ...MOCK_GENE_ROW, assembly_id: assembly.id, assembly_name: assembly.name };

  await page.route(/.*/, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!isMockedApiRequest(url)) {
      await route.fallback();
      return;
    }

    captured.push({
      method: request.method(),
      pathname: url.pathname,
      search: url.search,
      releaseHeader: request.headers()["x-soymutdb-release"] ?? null,
      authorizationHeader: request.headers()["authorization"] ?? null,
      request,
    });

    const origin = request.headers()["origin"];
    const cors: Record<string, string> = {
      "access-control-allow-origin": origin ?? "*",
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "authorization,content-type,x-soymutdb-release",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      vary: "Origin",
    };

    if (request.method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: cors });
    }

    const json = (body: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        // The portal pins the release from this response header. Without it the
        // client has no release context, so a JBrowse deep link carries only an
        // assembly and `/browser` correctly refuses to render (missing context)
        // instead of guessing a dataset.
        headers: {
          ...cors,
          "x-soymutdb-release": MOCK_RELEASE_ID,
          "access-control-expose-headers": "x-soymutdb-release",
        },
        body: JSON.stringify(body),
      });

    const path = url.pathname;

    // --- auth ---
    if (path.endsWith("/auth/login")) {
      return json({ access_token: "e2e-access-token", expires_in: 900 });
    }

    // --- active release singleton (not a fabricated published dataset) ---
    // The JBrowse bridge refuses links without BOTH release and assembly.
    // This deterministic API mock drives the real ReleaseScopeProvider pin.
    if (path.endsWith("/releases/active")) {
      return json({ release_id: MOCK_RELEASE_ID, version: "e2e", published_at: "2026-01-01T00:00:00Z" });
    }

    // --- genome catalog ---
    if (path.endsWith("/genes/assemblies")) return json([assembly]);
    if (/\/genes\/assemblies\/[^/]+\/chromosomes$/.test(path)) {
      return json([{ id: "1", assembly_id: assembly.id, name: "chr01", length: 100000, order: 0 }]);
    }

    // --- table templates ---
    const tableKind = /\/table-views\/([a-z_]+)$/.exec(path)?.[1];
    if (tableKind) {
      const columns: Record<string, Array<[string, string]>> = {
        genes: [
          ["assembly_name", "Genome version"],
          ["chromosome", "Chromosome"],
          ["position", "Position"],
          ["variant_count", "Mutation feature"],
          ["gene_id", "Gene ID"],
        ],
        mutant_lines: [
          ["public_id", "Mutant line"],
          ["name", "Name"],
          ["mutagen", "Mutagen"],
        ],
        variants: [
          ["variant_id", "Variant ID"],
          ["chromosome", "Chromosome"],
          ["position", "Position"],
          ["gene_id", "Gene ID"],
        ],
      };
      return json({
        kind: tableKind,
        columns: (columns[tableKind] ?? columns.variants).map(([key, label_en]) => ({
          key,
          label_zh: label_en,
          label_en,
          visible: true,
        })),
        actions: { jbrowse: true, genome_preview: false },
      });
    }

    // --- opt-in local unpublished mutation-site preview (test-only payload) ---
    // The live table joins catalogue genes to exact source mutation-site rows.
    // Earlier mocks supplied only the catalogue result, so the table was empty
    // and the JBrowse action could never exist. Keep this scoped to the one
    // fixture accession; all other queries return zero rows.
    if (path.endsWith("/preview/test-data/mutation-sites/by-gene")) {
      if (assembly.name !== MOCK_PREVIEW_ASSEMBLY.name || url.searchParams.get("gene_id") !== MOCK_GENE_ID) return json([]);
      return json([{
        source_site_key: "E2E-01-100",
        mutant_line_name: "E2E1",
        chromosome: "chr01",
        position: 100,
        confidence: "H",
        gene_id: MOCK_GENE_ID,
        feature: "insertion",
        available: true,
        gene_v2: null,
        gene_v4: null,
        gene_dn53: null,
      }]);
    }

    // --- gene search / detail / related ---
    if (/\/genes\/[^/]+$/.test(path) && !path.endsWith("/genes/assemblies")) {
      return json({
        ...geneRow,
        source: "mock",
        extra: {},
        annotations: [],
        transcripts: [],
        snp_count: 1,
        missense_count: 1,
      });
    }
    if (path.endsWith("/genes")) {
      return json({
        items: [geneRow],
        next_cursor: null,
        has_more: false,
        page: 1,
        page_size: 20,
        total: 1,
        total_pages: 1,
      });
    }
    if (path.includes("/expression/genes/")) {
      return json({ gene_id: MOCK_GENE_ID, expressions: [], next_cursor: null, has_more: false });
    }
    if (path.includes("/homologs/genes/")) {
      return json({ gene_id: MOCK_GENE_ID, homologs: [], next_cursor: null, has_more: false });
    }

    // --- mutant list / detail / phenotypes ---
    if (/\/mutants\/[^/]+\/phenotypes$/.test(path)) return json([]);
    if (/\/mutants\/[^/]+$/.test(path)) {
      return json({
        ...MOCK_MUTANT_ROW,
        species: "Glycine max",
        description: "A deterministic offline mutant line.",
        generation: "M3",
        phenotype_summary: null,
        is_public: true,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      });
    }
    if (path.endsWith("/mutants")) return json([MOCK_MUTANT_ROW]);

    // --- variant list / detail ---
    if (/\/variants\/[^/]+$/.test(path)) {
      return json({ ...MOCK_VARIANT_ROW, end_position: 150, length: 1 });
    }
    if (path.endsWith("/variants")) {
      return json({
        items: [MOCK_VARIANT_ROW],
        cursor: null,
        next_cursor: null,
        has_more: false,
        total_count: 1,
      });
    }

    // --- omnibox search (public shape; internal uses the same contract today) ---
    if (path.endsWith("/search/internal")) {
      return json({
        query: url.searchParams.get("query") ?? "",
        mutants: [
          {
            entity_type: "mutant_line",
            public_id: MOCK_MUTANT_PUBLIC_ID,
            internal_id: MOCK_MUTANT_INTERNAL_ID,
            name: MOCK_MUTANT_ROW.name,
            matched_field: "internal_id",
            match_type: "exact",
            is_public: true,
            release_id: 7,
            url: `/mutants/${MOCK_MUTANT_PUBLIC_ID}`,
          },
        ],
        genes: [],
        total_count: 1,
      });
    }
    if (path.endsWith("/search")) {
      return json({
        query: url.searchParams.get("query") ?? "",
        results: [
          {
            type: "mutant_line",
            id: MOCK_MUTANT_PUBLIC_ID,
            name: `${MOCK_MUTANT_ROW.name} (${MOCK_MUTANT_INTERNAL_ID})`,
            url: `/mutants/${MOCK_MUTANT_PUBLIC_ID}`,
            assembly: MOCK_ASSEMBLY.name,
            release_id: 7,
          },
        ],
        by_type: { mutant_line: 1 },
        cursor: null,
        next_cursor: null,
        has_more: false,
        total_count: 1,
      });
    }

    // --- news ---
    if (path.endsWith("/news/featured")) return json({ featured: [], carousel: [] });
    if (path.endsWith("/news")) return json({ items: [], total: 0 });

    return json({}, 404);
  });

  return captured;
}

/** Backwards-compatible alias for the gene-only suites. */
