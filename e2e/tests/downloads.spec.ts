/**
 * Downloads catalogue — offline artifact gate.
 *
 * Covers the data-file catalogue's real behaviour: API-driven grouping, the
 * preview dialog opening per file, and the download path's URL-scheme guard.
 * The guard matters: both the signed URL and the stored `file_url` are server
 * data, so a poisoned row must not be able to hand `javascript:`/`data:` to
 * `window.open`. The API is stubbed in-browser because the built artifact
 * targets an absolute API origin.
 */
import { test, expect, type Page } from "@playwright/test";

import { gotoReady } from "./helpers";

interface StubFile {
  id: string;
  name: string;
  description: string | null;
  file_url: string;
  file_size: number | null;
  category: string | null;
  download_count: number;
  created_at: string;
}

const SMALL_FILE: StubFile = {
  id: "file-small",
  name: "variants_small.vcf.gz",
  description: "Small variant call set",
  file_url: "https://files.example.test/variants_small.vcf.gz",
  file_size: 1536,
  category: "variants",
  download_count: 3,
  created_at: "2026-01-02T00:00:00Z",
};
const EVIL_FILE: StubFile = {
  id: "file-evil",
  name: "poisoned.tsv",
  description: "A row whose URLs must never reach window.open",
  // Both the catalogue URL and the signed URL are hostile; the page must open
  // nothing rather than forwarding a script URL to a new tab.
  file_url: "javascript:alert('catalogue')",
  file_size: 1024,
  category: "genes",
  download_count: 0,
  created_at: "2026-01-03T00:00:00Z",
};

interface OpenedCall {
  url: string;
  target: string | undefined;
}

async function stubDownloadsApi(page: Page): Promise<void> {
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
    if (path.endsWith("/content/downloads")) return json([SMALL_FILE, EVIL_FILE]);
    if (path.endsWith("/content/downloads/file-small/url")) {
      return json({ url: "https://cdn.example.test/signed/variants_small.vcf.gz", expires_in: 300 });
    }
    if (path.endsWith("/content/downloads/file-evil/url")) {
      return json({ url: "javascript:alert('signed')", expires_in: 300 });
    }
    return json({}, 404);
  });
}

/** Capture window.open calls before the app boots (popups are blocked in CI). */
async function captureWindowOpen(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const calls: Array<{ url: string; target: string | undefined }> = [];
    (window as unknown as { __openedCalls: typeof calls }).__openedCalls = calls;
    window.open = ((url?: string | URL, target?: string) => {
      calls.push({ url: String(url), target });
      return null;
    }) as typeof window.open;
  });
}

async function openedCalls(page: Page): Promise<OpenedCall[]> {
  return page.evaluate(
    () => (window as unknown as { __openedCalls?: OpenedCall[] }).__openedCalls ?? [],
  );
}

test("renders the API catalogue grouped with per-file actions", async ({ page }) => {
  await stubDownloadsApi(page);
  await gotoReady(page, "/downloads");

  await expect(page.getByTestId("download-row-file-small")).toBeVisible();
  await expect(page.getByTestId("download-row-file-evil")).toBeVisible();
  // Format column derives from the extension; a single row per file.
  await expect(page.getByText("variants_small.vcf.gz")).toBeVisible();
  await expect(page.getByText("poisoned.tsv")).toBeVisible();
  await expect(page.getByRole("button", { name: "Preview" }).first()).toBeVisible();
});

test("opens the signed https URL and refuses a javascript: signed URL", async ({ page }) => {
  await captureWindowOpen(page);
  await stubDownloadsApi(page);
  await gotoReady(page, "/downloads");

  // Safe row: the signed URL is opened in a new tab.
  await page
    .getByTestId("download-row-file-small")
    .getByRole("button", { name: /download/i })
    .click();
  await expect
    .poll(async () => (await openedCalls(page)).map((call) => call.url))
    .toContain("https://cdn.example.test/signed/variants_small.vcf.gz");

  // Poisoned row: neither the signed URL nor the catalogue file_url may reach
  // window.open, so the call list must not grow.
  const before = (await openedCalls(page)).length;
  await page
    .getByTestId("download-row-file-evil")
    .getByRole("button", { name: /download/i })
    .click();
  await page.waitForTimeout(500);
  const after = await openedCalls(page);
  expect(after.length).toBe(before);
  expect(after.some((call) => call.url.startsWith("javascript:"))).toBe(false);
});

test("opens the preview dialog for a small file", async ({ page }) => {
  await stubDownloadsApi(page);
  await gotoReady(page, "/downloads");

  await page
    .getByTestId("download-row-file-small")
    .getByRole("button", { name: "Preview" })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  // The filename appears in the dialog header and in its download link, so
  // assert the header occurrence rather than a strict-mode-ambiguous text.
  await expect(dialog.getByTitle("variants_small.vcf.gz")).toBeVisible();
  await expect(dialog.getByText("VCF", { exact: true })).toBeVisible();
});
