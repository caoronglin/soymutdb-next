import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { renderSampleDetailHtml, type SampleVariant } from "../fallback-data";

const WEB_ROOT = resolve(import.meta.dirname, "../..");
const GENERATOR = resolve(WEB_ROOT, "scripts/generate-samples.ts");
const TSX_IMPORT = createRequire(import.meta.url).resolve("tsx");
const temporaryDirectories: string[] = [];

interface RunResult {
  code: number | null;
  cwd: string;
  stderr: string;
  stdout: string;
}

function sampleApiItem(id = "SAFE-1") {
  return {
    id,
    variant_id: id,
    chromosome: "Gm01",
    position: 42,
    ref_allele: "A",
    alt_allele: "T",
    variant_type: "SNP",
    impact: "HIGH",
    gene_id: "Glyma.01G000100",
    gene_symbol: "GmSafe",
  };
}

async function runGenerator(environment: Record<string, string | undefined>): Promise<RunResult> {
  const cwd = mkdtempSync(join(tmpdir(), "soymutdb-samples-"));
  temporaryDirectories.push(cwd);
  const preload = join(cwd, "mock-fetch.mjs");
  writeFileSync(preload, `
import { appendFileSync } from "node:fs";
globalThis.fetch = async function(input) {
  appendFileSync(process.cwd() + "/fetch-url.txt", String(input) + "\\n");
  if (process.env.SAMPLE_TEST_FETCH === "reject") throw new Error("API unavailable");
  return new Response(process.env.SAMPLE_TEST_FETCH ?? "{}", {
    status: Number(process.env.SAMPLE_TEST_STATUS ?? "200"),
    headers: { "Content-Type": "application/json" },
  });
};
`, "utf8");
  const childEnvironment = { ...process.env };
  for (const [name, value] of Object.entries(environment)) {
    if (value === undefined) delete childEnvironment[name];
    else childEnvironment[name] = value;
  }
  childEnvironment.NODE_OPTIONS = [childEnvironment.NODE_OPTIONS, `--import=${preload}`]
    .filter(Boolean)
    .join(" ");

  return await new Promise((resolveRun) => {
    const child = spawn(process.execPath, ["--import", TSX_IMPORT, GENERATOR], {
      cwd,
      env: childEnvironment,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += String(chunk); });
    child.stderr.on("data", (chunk) => { stderr += String(chunk); });
    child.on("close", (code) => resolveRun({ code, cwd, stderr, stdout }));
  });
}

afterEach(async () => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

describe("sample HTML security", () => {
  it("escapes hostile API text in the sample detail markup", () => {
    const hostile = {
      ...sampleApiItem(),
      gene: "Glyma.01G000100",
      geneName: "GmSafe",
      refAllele: "A",
      altAllele: "T",
      mutationType: "SNP",
      phenotype: '<img src=x onerror="window.pwned=1">',
      mutagen: "EMS",
      cultivar: "Williams 82",
      referenceGenome: "Wm82.a4.v1",
      description: "</script><script>window.pwned=2</script>",
    } satisfies SampleVariant;

    const html = renderSampleDetailHtml(hostile, "/portal/");

    expect(html).not.toContain("<img src=x");
    expect(html).not.toContain("</script><script>");
    expect(html).toContain("&lt;img src=x onerror=&quot;window.pwned=1&quot;&gt;");
    expect(html).toContain("&lt;/script&gt;&lt;script&gt;window.pwned=2&lt;/script&gt;");
    expect(html).toContain('href="/portal/browser"');
    expect(html).toContain('href="/portal/search"');
  });
});

describe("sample release data contract", () => {
  it("fails a production build when the API is unavailable", async () => {
    const result = await runGenerator({
      VITE_API_BASE_URL: "http://127.0.0.1:1/api/v1",
      VITE_BASE_URL: "/portal/",
      VITE_DEPLOYMENT_MODE: "standard",
      VITE_JBROWSE_BASE_URL: "http://localhost:5175",
      SOYMUTDB_FETCH_TIMEOUT: "50",
      SAMPLE_TEST_FETCH: "reject",
    });

    expect(result.code).not.toBe(0);
    expect(existsSync(join(result.cwd, "dist/samples/SMDB-00001.html"))).toBe(false);
  });

  it("reads the API items contract and emits base-aware scientific URLs", async () => {
    const result = await runGenerator({
      VITE_API_BASE_URL: "https://api.test/api/v1",
      VITE_BASE_URL: "/portal/",
      VITE_DEPLOYMENT_MODE: "minimal",
      VITE_JBROWSE_BASE_URL: undefined,
      VITE_JBROWSE_URL: undefined,
      SOYMUTDB_SITE_URL: "https://db.example.org",
      SAMPLE_TEST_FETCH: JSON.stringify({ items: [sampleApiItem()], has_more: false }),
    });

    expect(result.code, result.stderr).toBe(0);
    const detail = readFileSync(join(result.cwd, "dist/samples/SAFE-1.html"), "utf8");
    const index = readFileSync(join(result.cwd, "dist/samples/index.html"), "utf8");
    const sitemap = readFileSync(join(result.cwd, "dist/sitemap.xml"), "utf8");

    expect(readFileSync(join(result.cwd, "fetch-url.txt"), "utf8")).toContain("limit=200");
    expect(detail).toContain('href="https://db.example.org/portal/samples/SAFE-1.html"');
    expect(detail).toContain('src="/portal/track.gif?');
    expect(index).toContain('href="/portal/samples/SAFE-1.html"');
    expect(sitemap).toContain("https://db.example.org/portal/samples/SAFE-1.html");
    expect(detail).not.toContain('name="robots" content="noindex');
  });

  it("rejects an API identifier that could escape the samples directory", async () => {
    const result = await runGenerator({
      VITE_API_BASE_URL: "https://api.test/api/v1",
      VITE_BASE_URL: "/portal/",
      VITE_DEPLOYMENT_MODE: "standard",
      VITE_JBROWSE_BASE_URL: "http://localhost:5175",
      SAMPLE_TEST_FETCH: JSON.stringify({ items: [sampleApiItem("../escape")] }),
    });

    expect(result.code).not.toBe(0);
    expect(readFileSync(join(result.cwd, "fetch-url.txt"), "utf8")).toContain("/variants?limit=200");
    expect(existsSync(join(result.cwd, "dist/escape.html"))).toBe(false);
    expect(existsSync(join(result.cwd, "dist/samples"))).toBe(false);
  });

  it("keeps demo fixtures out of all indexable crawl artifacts", async () => {
    const result = await runGenerator({
      VITE_API_BASE_URL: "https://demo.example.org/api/v1",
      VITE_BASE_URL: "/portal/",
      VITE_DEPLOYMENT_MODE: "demo",
      VITE_JBROWSE_BASE_URL: "https://browser.example.org",
      SOYMUTDB_SITE_URL: "https://db.example.org",
      SAMPLE_TEST_FETCH: "reject",
    });

    expect(result.code, result.stderr).toBe(0);
    const detail = readFileSync(join(result.cwd, "dist/samples/SMDB-00001.html"), "utf8");
    const index = readFileSync(join(result.cwd, "dist/samples/index.html"), "utf8");
    const robots = readFileSync(join(result.cwd, "dist/robots.txt"), "utf8");

    expect(detail).toContain('name="robots" content="noindex, nofollow"');
    expect(index).toContain('name="robots" content="noindex, nofollow"');
    expect(detail).toMatch(/demonstration data/i);
    expect(index).toMatch(/demonstration data/i);
    expect(detail).toContain("p=%2Fportal%2Fsamples%2FSMDB-00001.html");
    expect(detail).not.toContain('rel="canonical"');
    expect(detail).not.toContain('type="application/ld+json"');
    expect(existsSync(join(result.cwd, "dist/sitemap.xml"))).toBe(false);
    expect(robots).toContain("noindex, nofollow");
    expect(robots).toContain("User-agent: *\nDisallow: /\n");
    expect(robots).not.toContain("Sitemap:");
  });
});
