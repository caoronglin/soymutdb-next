import { execFile } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderSampleDetailHtml, type SampleVariant } from "../fallback-data";

const execFileAsync = promisify(execFile);
const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");
const GENERATOR = resolve(REPOSITORY_ROOT, "apps/web/scripts/generate-samples.ts");
const TSX_LOADER = resolve(
  REPOSITORY_ROOT,
  "apps/web/node_modules/tsx/dist/loader.mjs",
);

const temporaryDirectories: string[] = [];

interface GeneratorOptions {
  existingSitemap?: string;
  publicationMode?: "release" | "preview" | "demo";
  siteUrl?: string;
}

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function runGenerator(
  mode: "standard" | "demo",
  response: { status: number; body: unknown },
  options: GeneratorOptions = {},
) {
  const directory = mkdtempSync(join(tmpdir(), "sample-generation-"));
  temporaryDirectories.push(directory);
  if (options.existingSitemap !== undefined) {
    mkdirSync(join(directory, "dist"), { recursive: true });
    writeFileSync(join(directory, "dist/sitemap.xml"), options.existingSitemap, "utf8");
  }
  const requestLog = join(directory, "requests.log");
  const fetchMock = join(directory, "fetch-mock.mjs");
  writeFileSync(
    fetchMock,
    [
      'import { appendFileSync } from "node:fs";',
      'globalThis.fetch = async function(input) {',
      '  appendFileSync(process.env.MOCK_REQUEST_LOG, String(input) + "\\n");',
      '  return new Response(process.env.MOCK_RESPONSE_BODY, {',
      '    status: Number(process.env.MOCK_RESPONSE_STATUS),',
      '    headers: { "content-type": "application/json" },',
      '  });',
      '};',
    ].join("\n"),
  );
  return execFileAsync(process.execPath, ["--import", TSX_LOADER, GENERATOR], {
    cwd: directory,
    env: {
      ...process.env,
      SOYMUTDB_API_URL: "",
      SOYMUTDB_FETCH_TIMEOUT: "250",
      SOYMUTDB_PUBLICATION_MODE: options.publicationMode ?? "",
      SOYMUTDB_SITE_URL: options.siteUrl ?? "https://public.example.org/portal/",
      VITE_API_BASE_URL: "http://127.0.0.1:8000/api/v1",
      VITE_BASE_URL: "/portal/",
      VITE_DEPLOYMENT_MODE: mode,
      VITE_JBROWSE_BASE_URL: "http://localhost:5175",
      MOCK_REQUEST_LOG: requestLog,
      MOCK_RESPONSE_BODY: JSON.stringify(response.body),
      MOCK_RESPONSE_STATUS: String(response.status),
      NODE_OPTIONS: `--import=${fetchMock}`,
    },
  }).then((result) => ({
    directory,
    requests: (existsSync(requestLog) ? readFileSync(requestLog, "utf8") : "")
      .trim()
      .split("\n")
      .filter(Boolean)
      .map((url) => new URL(url, "http://relative.test")),
    ...result,
  }));
}

describe("sample HTML security", () => {
  it("escapes API text and emits only base-aware application URLs", () => {
    const malicious = {
      id: "SMDB-00001",
      gene: "</span><script>alert(1)</script>",
      geneName: '<img src=x onerror="alert(2)">',
      chromosome: "Gm01",
      position: 12,
      refAllele: "G",
      altAllele: "A",
      mutationType: "SNP",
      impact: "HIGH",
      phenotype: '<svg onload="alert(3)">',
      mutagen: "EMS",
      cultivar: "Williams & Sons",
      referenceGenome: "Wm82.a4.v1",
      description: "</script><script>alert(4)</script>",
      proteinChange: "p.Gln726*",
    } satisfies SampleVariant;

    const html = renderSampleDetailHtml(malicious, "/portal/");

    expect(html).not.toContain("<script>alert");
    expect(html).not.toContain("<img src=x");
    expect(html).not.toContain("<svg onload");
    expect(html).toContain("&lt;img src=x onerror=&quot;alert(2)&quot;&gt;");
    expect(html).toContain('href="/portal/browser"');
    expect(html).toContain('href="/portal/search"');
  });

  it("escapes JSON-LD script breakouts, canonical attributes, and tracking URLs", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "http://localhost:8000");
    vi.stubEnv("VITE_BASE_URL", "/portal/");
    vi.stubEnv("VITE_DEPLOYMENT_MODE", "minimal");
    vi.stubEnv("VITE_JBROWSE_BASE_URL", "");
    const { renderBaseTemplate } = await import("../base-template");

    const html = renderBaseTemplate({
      title: 'Bad " title <tag>',
      description: '<img src=x onerror="alert(1)">',
      canonical: 'https://public.example.org/portal/samples/x.html?x=" onload="alert(2)',
      jsonLd: { description: "</script><script>alert(3)</script>" },
      assets: { jsEntry: "assets/app.js", cssEntry: "assets/app.css", preloads: [], fontPreloads: [] },
    });

    const jsonLd = html.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)?.[1];
    expect(jsonLd).toBeDefined();
    expect(jsonLd).not.toContain("<");
    expect(jsonLd).toContain("\\u003c/script");
    expect(html).toContain("&quot; onload=&quot;alert(2)");
    expect(html).not.toContain('href="https://public.example.org/portal/samples/x.html?x=" onload=');
    expect(html).toContain('src="/portal/track.gif?p=');
  });
});

describe("sample release-data contract", () => {
  it("uses VITE_API_BASE_URL, limit=200, and the API items response without fallback", async () => {
    const { directory, requests } = await runGenerator("standard", {
      status: 200,
      body: {
        items: [{
          id: "SMDB-00001",
          chromosome: "Gm01",
          position: 45230012,
          ref_allele: "G",
          alt_allele: "A",
          variant_type: "SNP",
          gene_id: "Glyma.01G123400",
          gene_symbol: '<img src=x onerror="alert(1)">',
          impact: "HIGH",
          consequence: "</script><script>alert(2)</script>",
        }],
        next_cursor: null,
        total_count: 1,
        has_more: false,
      },
    });
    const html = readFileSync(join(directory, "dist/samples/SMDB-00001.html"), "utf8");
    const sitemap = readFileSync(join(directory, "dist/sitemap.xml"), "utf8");

    expect(requests).toHaveLength(1);
    expect(requests[0].pathname).toBe("/api/v1/variants");
    expect(requests[0].searchParams.get("limit")).toBe("200");
    expect(html).not.toContain("<img src=x");
    expect(html).not.toContain("</script><script>");
    expect(html).toContain('href="/portal/browser"');
    expect(html).toContain('src="/portal/track.gif?p=');
    expect(html).toContain(
      '<link rel="canonical" href="https://public.example.org/portal/samples/SMDB-00001.html"',
    );
    expect(sitemap).toContain(
      "<loc>https://public.example.org/portal/samples/SMDB-00001.html</loc>",
    );
  }, 15_000);

  it("fails closed when production release data is unavailable", async () => {
    await expect(
      runGenerator("standard", { status: 503, body: { detail: "unavailable" } }),
    ).rejects.toMatchObject({ code: 1 });
  }, 15_000);

  it("allows explicit demo fixtures but marks and excludes them from scientific indexing", async () => {
    const { directory } = await runGenerator("demo", { status: 503, body: { detail: "unavailable" } });
    const html = readFileSync(join(directory, "dist/samples/SMDB-00001.html"), "utf8");
    const robots = readFileSync(join(directory, "dist/robots.txt"), "utf8");

    expect(html).toContain('<meta name="robots" content="noindex, nofollow"');
    expect(html).toMatch(/demo fixture/i);
    expect(html).not.toContain('rel="canonical"');
    expect(existsSync(join(directory, "dist/sitemap.xml"))).toBe(false);
    expect(robots).toContain("noindex, nofollow");
    expect(robots).toContain("User-agent: *\nDisallow: /\n");
    expect(robots).not.toContain("Sitemap:");
  }, 15_000);

  it("keeps preview output non-indexable without requiring a public origin", async () => {
    const { directory } = await runGenerator(
      "standard",
      {
        status: 200,
        body: {
          items: [{
            id: "SMDB-00001",
            chromosome: "Gm01",
            position: 45230012,
            ref_allele: "G",
            alt_allele: "A",
            variant_type: "SNP",
            gene_id: "Glyma.01G123400",
          }],
        },
      },
      {
        publicationMode: "preview",
        siteUrl: "not-a-public-origin",
        existingSitemap: "<urlset><url><loc>https://stale.example.org</loc></url></urlset>",
      },
    );
    const detail = readFileSync(join(directory, "dist/samples/SMDB-00001.html"), "utf8");
    const index = readFileSync(join(directory, "dist/samples/index.html"), "utf8");
    const robots = readFileSync(join(directory, "dist/robots.txt"), "utf8");

    expect(detail).toContain('<meta name="robots" content="noindex, nofollow"');
    expect(index).toContain('<meta name="robots" content="noindex, nofollow"');
    expect(detail).not.toContain('rel="canonical"');
    expect(detail).not.toContain('type="application/ld+json"');
    expect(existsSync(join(directory, "dist/sitemap.xml"))).toBe(false);
    expect(robots).toContain("noindex, nofollow");
    expect(robots).toContain("User-agent: *\nDisallow: /\n");
    expect(robots).not.toContain("Sitemap:");
  }, 15_000);
});

describe("minimal deployment template", () => {
  it("does not require a JBrowse origin", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "http://localhost:8000");
    vi.stubEnv("VITE_BASE_URL", "/minimal/");
    vi.stubEnv("VITE_DEPLOYMENT_MODE", "minimal");
    vi.stubEnv("VITE_JBROWSE_BASE_URL", "");
    const { renderBaseTemplate } = await import("../base-template");

    expect(() =>
      renderBaseTemplate({
        title: "Minimal",
        description: "Web only",
        assets: { jsEntry: "assets/app.js", cssEntry: "assets/app.css", preloads: [], fontPreloads: [] },
      }),
    ).not.toThrow();
  });
});
