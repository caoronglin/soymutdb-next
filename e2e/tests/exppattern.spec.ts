/**
 * Expression Pattern tool — offline artifact gate.
 *
 * Covers the heatmap tool's real contract: the POST payload (assembly id, gene
 * list, clustering flag, scaling), the summary tags, the missing-gene notice and
 * the expression matrix (genes as rows, conditions as columns). The chart
 * itself is rendered by the shared charts facade lazily, so the gate asserts the
 * deterministic matrix/table contract and that the heatmap figure mounts.
 *
 * The built artifact targets an absolute API origin; the API is stubbed here.
 */
import { test, expect, type Page } from "@playwright/test";

import { gotoReady } from "./helpers";

interface CapturedRequest {
  pathname: string;
  body: unknown;
}

interface ExpPatternStub {
  captured: CapturedRequest[];
}

const RESULT = {
  assembly_id: 1,
  release_id: 7,
  assembly_name: "Wm82.a4.v1",
  assembly_version: "a4.v1",
  genes: ["Glyma.01G000100", "Glyma.02G000200"],
  conditions: ["root", "leaf"],
  matrix: [
    [1.5, 2.25],
    [-0.5, 0.75],
  ],
  row_order: [0, 1],
  clustering: "mean_sort",
  value_range: [-0.5, 2.25],
  missing_genes: ["Glyma.99G999999"],
  scale: "zscore",
};

async function stubExpPatternApi(page: Page): Promise<ExpPatternStub> {
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
    if (path.endsWith("/tools/exppattern")) {
      captured.push({ pathname: path, body: request.postDataJSON() });
      return json(RESULT);
    }
    return json({}, 404);
  });
  return { captured };
}

test("submits the documented payload and renders summary, missing genes and matrix", async ({
  page,
}) => {
  const stub = await stubExpPatternApi(page);
  await gotoReady(page, "/tools/exppattern");
  // The assembly control is always rendered; wait for the query to preselect it.
  await expect(page.getByText(/Wm82\.a4\.v1/).first()).toBeVisible();

  await page.locator("#ep-genes").fill("Glyma.01G000100\nGlyma.02G000200");
  await page.getByRole("button", { name: /build heatmap/i }).click();

  // Summary card: counts, clustering badge and the z-score scaling tag.
  await expect(page.getByText("2 genes × 2 conditions.")).toBeVisible();
  await expect(page.getByText("Hierarchical clustering")).toBeVisible();
  await expect(page.getByText("z-score").first()).toBeVisible();
  // Missing-gene notice is data-driven, not decorative.
  await expect(page.getByText("Missing genes")).toBeVisible();
  await expect(page.getByText("Glyma.99G999999")).toBeVisible();

  // Expression matrix: genes as rows, conditions as columns, values rendered.
  // Roles rather than text: the charts facade keeps a visually hidden values
  // table for screen readers, so a bare text match can land on hidden markup.
  await expect(page.getByText("Expression matrix")).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "root" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "leaf" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Glyma.01G000100" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Glyma.02G000200" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "2.25" })).toBeVisible();

  // Heatmap figure mounts through the lazy charts facade and its accessible
  // name is interpolated (a missing `conditions` option used to leave the raw
  // `{{conditions}}` placeholder both here and in the summary).
  await expect(page.getByText("Expression heatmap")).toBeVisible();
  await expect(page.getByRole("img", { name: /2 genes × 2 conditions/ })).toBeVisible();

  expect(stub.captured, "the form must POST exactly one analysis").toHaveLength(1);
  expect(stub.captured[0]!.pathname.endsWith("/api/v1/tools/exppattern")).toBe(true);
  expect(stub.captured[0]!.body).toEqual({
    assembly_id: 1,
    genes: ["Glyma.01G000100", "Glyma.02G000200"],
    cluster_rows: false,
    scale: "zscore",
  });
});

test("refuses an empty and an over-50 gene list without sending a request", async ({ page }) => {
  const stub = await stubExpPatternApi(page);
  await gotoReady(page, "/tools/exppattern");
  await expect(page.getByText(/Wm82\.a4\.v1/).first()).toBeVisible();

  const submit = page.getByRole("button", { name: /build heatmap/i });
  await submit.click();
  await expect(page.getByText("Enter at least one gene ID.")).toBeVisible();

  const tooMany = Array.from({ length: 51 }, (_value, index) => `Gene.${index}`).join("\n");
  await page.locator("#ep-genes").fill(tooMany);
  await submit.click();
  await expect(page.getByText("Up to 50 gene IDs are allowed.")).toBeVisible();

  expect(stub.captured).toHaveLength(0);
});
