/**
 * Analyses module — offline artifact gate.
 *
 * The module is researcher-gated and has a server list endpoint plus a
 * localStorage "recent jobs" fallback. None of those three behaviours had a
 * browser assertion before this gate:
 *   1. an anonymous visitor sees the research-access gate and issues zero
 *      personal `/analyses` requests;
 *   2. a researcher session lists the server jobs and a row opens the job page;
 *   3. when the list endpoint is missing, locally recorded job ids are resolved
 *      through `GET /analyses/{id}` instead of showing an empty page.
 */
import { test, expect, type Page } from "@playwright/test";

import { gotoReady, waitForAppReady } from "./helpers";

const TEST_EMAIL = "researcher@example.org";
const TEST_PASSWORD = "correct-horse-battery-staple";

const FASTP_JOB = {
  job_id: "job-fastp-001",
  analysis_type: "fastp",
  status: "succeeded",
  created_at: "2026-01-02T00:00:00Z",
  updated_at: "2026-01-02T00:05:00Z",
  result: null,
};
const SCANPY_JOB = {
  job_id: "job-scanpy-002",
  analysis_type: "scanpy",
  status: "running",
  created_at: "2026-01-03T00:00:00Z",
  updated_at: "2026-01-03T00:05:00Z",
  result: null,
};
const LOCAL_JOB = {
  job_id: "job-local-03",
  analysis_type: "fastp",
  status: "running",
  created_at: "2026-01-04T00:00:00Z",
  updated_at: "2026-01-04T00:05:00Z",
  result: null,
};

interface AnalysesStub {
  requests: Array<{ method: string; pathname: string }>;
}

async function stubAnalysesApi(
  page: Page,
  options: { listStatus: number; listJobs?: unknown[]; jobsById?: Record<string, unknown> },
): Promise<AnalysesStub> {
  const requests: Array<{ method: string; pathname: string }> = [];
  await page.route(/\/api\/v1\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push({ method: request.method(), pathname: url.pathname });
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
    if (path.endsWith("/auth/login") || path.endsWith("/auth/refresh")) {
      return json({ access_token: "e2e-access-token", expires_in: 900 });
    }
    if (path.endsWith("/auth/me")) {
      return json({
        id: "user-researcher",
        username: TEST_EMAIL,
        email: TEST_EMAIL,
        is_active: true,
        is_superuser: false,
        role_name: "researcher",
        effective_roles: ["researcher"],
      });
    }
    if (path.endsWith("/analyses")) {
      return json(
        options.listStatus === 200
          ? { items: options.listJobs ?? [FASTP_JOB, SCANPY_JOB], total: 2 }
          : {},
        options.listStatus,
      );
    }
    const jobId = path.split("/analyses/")[1];
    if (jobId && options.jobsById?.[jobId]) {
      return json(options.jobsById[jobId]);
    }
    return json({}, 404);
  });
  return { requests };
}

async function signIn(page: Page, redirect = "/analyses"): Promise<void> {
  await page.goto(`/login?redirect=${encodeURIComponent(redirect)}`, { waitUntil: "load" });
  await waitForAppReady(page);
  await page.getByLabel("Email", { exact: true }).fill(TEST_EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(TEST_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL(new RegExp(`${redirect.replace(/\//g, "\\/")}$`));
}

test("anonymous visitor sees the research gate without personal analyses requests", async ({
  page,
}) => {
  const requests: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    // Only the personal API endpoint; the document/prefetch requests for the
    // /analyses route itself are not personal data requests.
    if (pathname.startsWith("/api/") && pathname.endsWith("/analyses")) {
      requests.push(request.url());
    }
  });
  await gotoReady(page, "/analyses");
  await expect(page.getByRole("heading", { name: "Research access required" })).toBeVisible();
  await page.waitForTimeout(500);
  expect(requests, "an anonymous visitor must not call the personal analyses endpoint").toEqual([]);
});

test("researcher sees the server job list and a row opens the job page", async ({ page }) => {
  const stub = await stubAnalysesApi(page, {
    listStatus: 200,
    jobsById: { "job-scanpy-002": SCANPY_JOB, "job-fastp-001": FASTP_JOB },
  });
  await signIn(page);

  // Server list: one row per job with pipeline + status rendered.
  await expect(page.getByText("fastp").first()).toBeVisible();
  await expect(page.getByText("scanpy").first()).toBeVisible();
  await expect(page.getByText("running").first()).toBeVisible();
  await expect(page.getByText("succeeded").first()).toBeVisible();
  expect(
    stub.requests.some((request) => request.pathname.endsWith("/analyses")),
    "the researcher list must use the server endpoint",
  ).toBe(true);

  // Row click navigates to the job page (which polls the job endpoint). Click
  // the table row, not the "New fastp job" call to action with the same label.
  await page.getByRole("row").filter({ hasText: "succeeded" }).click();
  await page.waitForURL(/\/analyses\/job-fastp-001$/);
  await expect(page.getByText(/submitted/i).first()).toBeVisible({ timeout: 20_000 });
});

test("missing list endpoint falls back to locally remembered job ids", async ({ page }) => {
  const stub = await stubAnalysesApi(page, {
    listStatus: 404,
    jobsById: { "job-local-03": LOCAL_JOB },
  });
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "soymutdb.analyses.recent_jobs",
      JSON.stringify(["job-local-03"]),
    );
  });
  await signIn(page);

  // The local record resolved through GET /analyses/{id} renders a row.
  // The cell renders the first eight characters of the id plus an ellipsis.
  await expect(page.getByText(/job-loca/).first()).toBeVisible({ timeout: 20_000 });
  expect(
    stub.requests.some((request) => request.pathname.endsWith("/analyses/job-local-03")),
    "the fallback must resolve the remembered id through the job endpoint",
  ).toBe(true);
});
