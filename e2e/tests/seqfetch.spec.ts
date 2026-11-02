/**
 * Sequence Fetch tool — offline artifact gate.
 *
 * Covers both documented modes end-to-end against a stubbed API:
 *   - "by gene IDs" POSTs `{assembly, genes}` and renders FASTA + count/missing;
 *   - "by region" POSTs `{assembly, region:"chr:start-end"}` and renders FASTA;
 *   - a large result returns only a pre-signed `download_url` (no inline text);
 *   - client-side validation refuses an empty and an over-200 gene list without
 *     sending a request.
 * The built artifact targets an absolute API origin, so the stub runs in-browser.
 */
import { test, expect, type Page } from "@playwright/test";

import { gotoReady } from "./helpers";

interface CapturedRequest {
  pathname: string;
  body: unknown;
}

interface SeqFetchStub {
  response: Record<string, unknown>;
  captured: CapturedRequest[];
}

async function stubSeqFetchApi(page: Page, response: Record<string, unknown>): Promise<SeqFetchStub> {
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
    if (path.endsWith("/tools/seqfetch")) {
      captured.push({ pathname: path, body: request.postDataJSON() });
      return json(response);
    }
    return json({}, 404);
  });
  return { response, captured };
}

const FASTQ = {
  format: "fasta",
  sequence: ">Glyma.01G000100 chr01:100-200\nACGTACGTACGTACGT\n>Glyma.02G000200 chr02:500-600\nTTTTGGGGCCCCAAAA",
  count: 2,
  truncated: false,
  missing: ["Glyma.99G999999"],
};

/**
 * The assembly control only renders in the "by region" tab, but the selected
 * assembly is shared state for BOTH modes. Visit the region tab once so the
 * async assemblies query resolves and the default assembly is preselected, then
 * optionally return to the gene-ID tab.
 */
async function ensureAssemblySelected(page: Page, returnToGenes = false): Promise<void> {
  await page.getByRole("tab", { name: /by region/i }).click();
  // The antd 6 Select renders the selected label as text inside its own
  // wrapper; assert the visible label rather than a version-specific class.
  await expect(page.getByText("Wm82.a4.v1").first()).toBeVisible();
  if (returnToGenes) await page.getByRole("tab", { name: /by gene ids/i }).click();
}

test("fetches FASTA by gene IDs and reports count and missing genes", async ({ page }) => {
  const stub = await stubSeqFetchApi(page, FASTQ);
  await gotoReady(page, "/tools/seqfetch");
  await ensureAssemblySelected(page, true);

  await page.locator("#sf-genes").fill("Glyma.01G000100\nGlyma.02G000200");
  await page.getByRole("button", { name: /fetch sequences/i }).click();

  await expect(page.getByTestId("seqfetch-fasta-preview")).toBeVisible();
  await expect(page.getByTestId("seqfetch-fasta-preview")).toContainText(">Glyma.01G000100");
  await expect(page.getByText("2 sequences")).toBeVisible();
  await expect(page.getByText("Missing genes")).toBeVisible();
  await expect(page.getByText("Glyma.99G999999")).toBeVisible();

  expect(stub.captured).toHaveLength(1);
  expect(stub.captured[0]!.pathname.endsWith("/api/v1/tools/seqfetch")).toBe(true);
  expect(stub.captured[0]!.body).toEqual({
    assembly: "Wm82.a4.v1",
    genes: ["Glyma.01G000100", "Glyma.02G000200"],
  });
});

test("fetches FASTA for a genomic region with the documented interval payload", async ({ page }) => {
  const stub = await stubSeqFetchApi(page, FASTQ);
  await gotoReady(page, "/tools/seqfetch");
  await ensureAssemblySelected(page);

  await page.locator("#sf-chr").fill("chr01");
  await page.locator("#sf-start").fill("100");
  await page.locator("#sf-end").fill("400");
  await page.getByRole("button", { name: /fetch sequences/i }).click();

  await expect(page.getByTestId("seqfetch-fasta-preview")).toBeVisible();
  expect(stub.captured).toHaveLength(1);
  expect(stub.captured[0]!.body).toEqual({ assembly: "Wm82.a4.v1", region: "chr01:100-400" });
});

test("renders a download link instead of inline text for a large result", async ({ page }) => {
  await stubSeqFetchApi(page, {
    format: "fasta",
    sequence: null,
    count: 400,
    truncated: true,
    missing: [],
    download_url: "https://files.example.test/seqfetch-large.fasta.gz",
  });
  await gotoReady(page, "/tools/seqfetch");
  await ensureAssemblySelected(page, true);

  await page.locator("#sf-genes").fill("Glyma.01G000100");
  await page.getByRole("button", { name: /fetch sequences/i }).click();

  await expect(page.getByText("Large result")).toBeVisible();
  await expect(page.getByTestId("seqfetch-fasta-preview")).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: /download fasta/i }),
  ).toHaveAttribute("href", "https://files.example.test/seqfetch-large.fasta.gz");
});

test("refuses an empty and an over-200 gene list without sending a request", async ({ page }) => {
  const stub = await stubSeqFetchApi(page, FASTQ);
  await gotoReady(page, "/tools/seqfetch");
  await ensureAssemblySelected(page, true);

  const submit = page.getByRole("button", { name: /fetch sequences/i });
  await submit.click();
  await expect(page.getByText("Enter at least one gene ID.")).toBeVisible();

  const tooMany = Array.from({ length: 201 }, (_value, index) => `Gene.${index}`).join(",");
  await page.locator("#sf-genes").fill(tooMany);
  await submit.click();
  await expect(page.getByText("Up to 200 gene IDs are allowed.")).toBeVisible();

  expect(stub.captured).toHaveLength(0);
});
