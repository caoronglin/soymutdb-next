/**
 * Public seed-request form — offline artifact gate.
 *
 * The form is the public write path: it prefills from a gene deep link, validates
 * the gene list client-side and POSTs `{name,email,institution,country,gene_ids,notes}`
 * to `/api/v1/seed-requests`. Nothing else in the browser suite exercised that
 * chain, so a broken payload, a dropped prefill or a missing success state would
 * only surface in production. The API is stubbed in-browser because the built
 * artifact targets an absolute API origin.
 */
import { test, expect, type Page } from "@playwright/test";

import { TOLERATED_CONSOLE_ERRORS, gotoReady } from "./helpers";

interface CapturedSubmit {
  method: string;
  pathname: string;
  contentType: string;
  body: unknown;
}

async function stubSeedRequestApi(page: Page): Promise<CapturedSubmit[]> {
  const captured: CapturedSubmit[] = [];
  await page.route(/\/api\/v1\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const origin = request.headers()["origin"];
    const headers: Record<string, string> = {
      "access-control-allow-origin": origin ?? "*",
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "authorization,content-type,x-soymutdb-release,x-csrf-token",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      vary: "Origin",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    if (request.method() === "POST" && url.pathname.endsWith("/seed-requests")) {
      captured.push({
        method: request.method(),
        pathname: url.pathname,
        contentType: request.headers()["content-type"] ?? "",
        body: request.postDataJSON(),
      });
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        headers,
        body: JSON.stringify({ id: "seed-request-e2e", status: "received" }),
      });
      return;
    }
    // Homepage stats / other public reads: honest 404, tolerated by the helper.
    await route.fulfill({ status: 404, contentType: "application/json", headers, body: "{}" });
  });
  return captured;
}

test("prefills the gene from the URL, submits JSON and shows the success state", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (TOLERATED_CONSOLE_ERRORS.some((pattern) => pattern.test(text))) return;
    consoleErrors.push(text);
  });
  const submitted = await stubSeedRequestApi(page);

  await gotoReady(page, "/seed-request?genes=Glyma.01G000100");
  await expect(page.getByTestId("seed-request-form")).toBeVisible();
  // The gene-detail "request seeds" entry writes the accession into the textarea.
  await expect(page.getByLabel(/gene ids/i)).toHaveValue(/Glyma\.01G000100/);

  await page.getByLabel(/^full name$/i).fill("E2E Researcher");
  await page.getByLabel(/^email address$/i).fill("e2e@example.org");
  await page.getByLabel(/^institution$/i).fill("SoyMutDB E2E Lab");
  await page.getByLabel(/^country \/ region$/i).fill("China");
  await page.getByTestId("seed-request-submit").click();

  await expect(page.getByTestId("seed-request-success")).toBeVisible({ timeout: 15_000 });

  expect(submitted, "the form must POST exactly one seed request").toHaveLength(1);
  const request = submitted[0]!;
  expect(request.pathname.endsWith("/api/v1/seed-requests")).toBe(true);
  expect(request.contentType).toContain("application/json");
  expect(request.body).toMatchObject({
    name: "E2E Researcher",
    email: "e2e@example.org",
    institution: "SoyMutDB E2E Lab",
    country: "China",
    gene_ids: ["Glyma.01G000100"],
  });
  expect(consoleErrors).toEqual([]);
});

test("rejects more than 200 gene ids client-side without hitting the API", async ({ page }) => {
  const submitted = await stubSeedRequestApi(page);
  await gotoReady(page, "/seed-request");

  const tooMany = Array.from({ length: 201 }, (_value, index) => `Gene.${index}`).join(",");
  await page.getByLabel(/gene ids/i).fill(tooMany);
  await page.getByLabel(/^full name$/i).fill("E2E Researcher");
  await page.getByLabel(/^email address$/i).fill("e2e@example.org");
  await page.getByLabel(/^institution$/i).fill("SoyMutDB E2E Lab");
  await page.getByLabel(/^country \/ region$/i).fill("China");
  await page.getByTestId("seed-request-submit").click();

  // Client-side cap: an error is shown and no write request is sent.
  await expect(page.getByText(/at most 200|too many/i).first()).toBeVisible({ timeout: 10_000 });
  expect(submitted).toHaveLength(0);
});
