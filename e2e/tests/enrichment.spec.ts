/**
 * GO / KEGG Enrichment tool — offline artifact gate.
 *
 * The tool has two real request/response contracts:
 *   - ORA: POST {assembly_id, genes, mode:"ora", ontology, p_threshold,
 *     max_terms, min_genes} → terms with gene_count/genes;
 *   - GSEA: the same keys plus `values` (parallel to `genes`) and a GSEA term
 *     shape (es/nes/size).
 * Each mode renders a summary (input/background counts), ontology/mode tags, the
 * significance chart and a term table. The API is stubbed in-browser because the
 * built artifact targets an absolute API origin.
 */
import { test, expect, type Page } from "@playwright/test";

import { gotoReady } from "./helpers";

interface CapturedRequest {
  pathname: string;
  body: unknown;
}

interface EnrichmentStub {
  captured: CapturedRequest[];
}

const CONTEXT = {
  assembly_id: 1,
  release_id: 7,
  assembly_name: "Wm82.a4.v1",
  assembly_version: "a4.v1",
  annotation_source: null,
};

const ORA_RESPONSE = {
  ...CONTEXT,
  mode: "ora",
  ontology: "go",
  input_genes: 2,
  background_genes: 1000,
  terms: [
    {
      id: "GO:0008150",
      name: "biological_process",
      p_value: 0.0012,
      q_value: 0.0045,
      gene_count: 2,
      genes: ["Glyma.01G000100", "Glyma.02G000200"],
    },
  ],
};

const GSEA_RESPONSE = {
  ...CONTEXT,
  mode: "gsea",
  ontology: "kegg",
  input_genes: 2,
  background_genes: 800,
  terms: [
    {
      id: "ko00010",
      name: "Glycolysis / Gluconeogenesis",
      es: 0.42,
      nes: 1.8,
      p_value: 0.01,
      q_value: 0.03,
      size: 12,
      genes: ["Glyma.01G000100"],
    },
  ],
};

async function stubEnrichmentApi(page: Page): Promise<EnrichmentStub> {
  const captured: CapturedRequest[] = [];
  await page.route(/\/api\/v1\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const origin = request.headers()["origin"];
    const headers: Record<string, string> = {
      "access-control-allow-origin": origin ?? "*",
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "authorization,content-type,x-soymutdb-release",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      vary: "Origin",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", headers, body: JSON.stringify(body) });
    const path = url.pathname;
    if (path.endsWith("/genes/assemblies")) {
      return json([
        { id: "1", name: "Wm82.a4.v1", species: "Glycine max", version: "a4.v1", is_default: true },
      ]);
    }
    if (path.endsWith("/tools/enrichment")) {
      const body = request.postDataJSON() as { mode?: string };
      captured.push({ pathname: path, body });
      return json(body.mode === "gsea" ? GSEA_RESPONSE : ORA_RESPONSE);
    }
    return json({}, 404);
  });
  return { captured };
}

async function waitForDefaultAssembly(page: Page): Promise<void> {
  await expect(page.getByText(/Wm82\.a4\.v1/).first()).toBeVisible();
}

test("ORA submits the documented payload and renders summary, tags and term table", async ({
  page,
}) => {
  const stub = await stubEnrichmentApi(page);
  await gotoReady(page, "/tools/enrichment");
  await waitForDefaultAssembly(page);

  await page.locator("#en-genes").fill("Glyma.01G000100\nGlyma.02G000200");
  // Regression: min=0.000001 + a fixed step made the default 0.05 a step
  // mismatch, so the browser blocked native submission and the tool silently
  // did nothing. The input must accept the default threshold natively.
  expect(
    await page.locator("#en-p").evaluate((element) => element.checkValidity()),
    "the default P-value threshold must satisfy native constraint validation",
  ).toBe(true);
  await page.getByRole("button", { name: /run analysis/i }).click();

  await expect(page.getByText("2 input genes, 1000 in background.")).toBeVisible();
  // Tags, not the form's ontology select / mode tab with the same label.
  const tag = (label: string) => page.locator(".ant-tag").filter({ hasText: new RegExp(`^${label}$`) });
  await expect(tag("GO")).toBeVisible();
  await expect(tag("ORA")).toBeVisible();
  await expect(tag("1 terms")).toBeVisible();
  // Term table: id + name, formatted p/q-values and member gene tags. The table
  // renders a compact (mobile) variant too, so anchor on the first match.
  await expect(page.getByText("GO:0008150").first()).toBeVisible();
  await expect(page.getByText("biological_process").first()).toBeVisible();
  await expect(page.getByRole("cell", { name: "0.0012" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "0.0045" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Glyma.01G000100" }).first()).toBeVisible();

  expect(stub.captured).toHaveLength(1);
  expect(stub.captured[0]!.pathname.endsWith("/api/v1/tools/enrichment")).toBe(true);
  expect(stub.captured[0]!.body).toEqual({
    assembly_id: 1,
    genes: ["Glyma.01G000100", "Glyma.02G000200"],
    mode: "ora",
    ontology: "go",
    p_threshold: 0.05,
    max_terms: 50,
    min_genes: 5,
  });
});

test("GSEA sends parallel genes/values and renders the GSEA term shape", async ({ page }) => {
  const stub = await stubEnrichmentApi(page);
  await gotoReady(page, "/tools/enrichment");
  await waitForDefaultAssembly(page);

  await page.getByRole("tab", { name: /^gsea$/i }).click();
  // Switch ontology through the form so the payload also proves the control.
  // Keyboard selection: the options list is virtualized and the second option
  // can sit outside the viewport in the headless window.
  await page.locator("#en-ontology").click();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  // The dropdown closes on selection; the payload assertion below is the
  // authoritative check that KEGG reached the request.
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await page.locator("#en-gsea-values").fill("Glyma.01G000100\t2.31\nGlyma.02G000200\t-1.2");
  await page.getByRole("button", { name: /run analysis/i }).click();

  await expect(page.getByText("2 ranked genes, 800 in background.")).toBeVisible();
  const tag = (label: string) => page.locator(".ant-tag").filter({ hasText: new RegExp(`^${label}$`) });
  await expect(tag("KEGG")).toBeVisible();
  await expect(tag("GSEA")).toBeVisible();
  await expect(page.getByText("ko00010").first()).toBeVisible();
  await expect(page.getByText("Glycolysis / Gluconeogenesis").first()).toBeVisible();
  // ES column uses signed formatting.
  await expect(page.getByText("+0.420").first()).toBeVisible();

  expect(stub.captured).toHaveLength(1);
  expect(stub.captured[0]!.body).toMatchObject({
    assembly_id: 1,
    genes: ["Glyma.01G000100", "Glyma.02G000200"],
    values: [2.31, -1.2],
    mode: "gsea",
    ontology: "kegg",
    p_threshold: 0.05,
    max_terms: 50,
    min_genes: 5,
  });
});

test("client-side validation rejects empty genes and an out-of-range p-value", async ({ page }) => {
  const stub = await stubEnrichmentApi(page);
  await gotoReady(page, "/tools/enrichment");
  await waitForDefaultAssembly(page);

  const submit = page.getByRole("button", { name: /run analysis/i });
  await submit.click();
  await expect(page.getByText("Enter at least one gene ID.")).toBeVisible();

  await page.locator("#en-genes").fill("Glyma.01G000100");
  // An out-of-range P value is caught by native number constraints, so the form
  // never reaches onSubmit: assert no request and an invalid native control.
  await page.locator("#en-p").fill("1.5");
  await submit.click();
  await expect
    .poll(() => page.locator("#en-p").evaluate((element: HTMLInputElement) => element.checkValidity()))
    .toBe(false);

  expect(stub.captured).toHaveLength(0);
});
