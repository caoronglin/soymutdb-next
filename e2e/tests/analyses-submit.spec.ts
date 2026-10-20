/**
 * fastp submission pipeline — offline artifact gate.
 *
 * The job submission is the module's write path: SHA-256 → presigned upload →
 * `POST /analyses/{type}/submit` → navigate to the job page. It had no browser
 * coverage at all (only the pipeline's unit tests). The mocks below return a
 * SAME-ORIGIN presigned URL on purpose: the artifact's CSP restricts
 * `connect-src`, so a real object-storage origin cannot be reached from the
 * static server.
 */
import { test, expect, type Page } from "@playwright/test";

import { gotoReady, waitForAppReady } from "./helpers";

const TEST_EMAIL = "researcher@example.org";
const TEST_PASSWORD = "correct-horse-battery-staple";

interface SubmitStub {
  uploads: unknown[];
  submits: unknown[];
  uploadBytes: number;
}

async function stubSubmitApi(page: Page, options: { authenticated?: boolean } = {}): Promise<SubmitStub> {
  const authenticated = options.authenticated ?? true;
  const stub: SubmitStub = { uploads: [], submits: [], uploadBytes: 0 };
  const origin = new URL(page.url() || "http://localhost:4173").origin;
  await page.route(/\/api\/v1\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const originHeader = request.headers()["origin"];
    const headers: Record<string, string> = {
      "access-control-allow-origin": originHeader ?? "*",
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
      if (!authenticated) return json({ detail: "Not authenticated" }, 401);
      return json({ access_token: "e2e-access-token", expires_in: 900 });
    }
    if (path.endsWith("/auth/me")) {
      if (!authenticated) return json({ detail: "Not authenticated" }, 401);
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
    if (path.endsWith("/analyses/uploads") && request.method() === "POST") {
      stub.uploads.push(request.postDataJSON());
      return json({
        upload_url: `${origin}/uploads-mock/put`,
        upload_method: "POST",
        upload_fields: { key: "analyses/uploads/read1.fastq" },
        object_key: "analyses/uploads/read1.fastq",
        expires_in: 600,
        max_size_bytes: 524288000,
      });
    }
    if (path.endsWith("/analyses/fastp/submit") && request.method() === "POST") {
      stub.submits.push(request.postDataJSON());
      return json({ job_id: "job-submit-1", status: "queued" });
    }
    if (path.endsWith("/analyses/job-submit-1")) {
      return json({
        job_id: "job-submit-1",
        analysis_type: "fastp",
        status: "running",
        created_at: "2026-01-05T00:00:00Z",
        updated_at: "2026-01-05T00:00:01Z",
        result: null,
      });
    }
    return json({}, 404);
  });
  await page.route(/\/uploads-mock\/put/, async (route) => {
    stub.uploadBytes += (route.request().postDataBuffer() ?? Buffer.alloc(0)).length;
    await route.fulfill({ status: 204, body: "" });
  });
  return stub;
}

async function signInToFastp(page: Page): Promise<void> {
  await page.goto(`/login?redirect=${encodeURIComponent("/analyses/fastp")}`, { waitUntil: "load" });
  await waitForAppReady(page);
  await page.getByLabel("Email", { exact: true }).fill(TEST_EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(TEST_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL(/\/analyses\/fastp$/);
}

test("anonymous visitor gets the research gate and never presigns an upload", async ({ page }) => {
  // Anonymous server: the session-restore probe must not authenticate.
  const stub = await stubSubmitApi(page, { authenticated: false });
  await gotoReady(page, "/analyses/fastp");
  await expect(page.getByRole("heading", { name: "Research access required" })).toBeVisible();
  expect(stub.uploads).toHaveLength(0);
});

test("a researcher uploads a FASTQ and submits the documented job payload", async ({ page }) => {
  const stub = await stubSubmitApi(page);
  await signInToFastp(page);

  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles({
    name: "read1.fastq",
    mimeType: "application/octet-stream",
    buffer: Buffer.from(">read1\nACGTACGTACGT\n+\nFFFFFFFFFFFF\n"),
  });
  await expect(page.getByText("read1.fastq")).toBeVisible();

  await page.locator('form button[type="submit"]').click();

  await expect
    .poll(() => stub.uploads.length, { message: "the pipeline must request a presigned upload" })
    .toBe(1);
  // SHA-256 of the file is bound into the presigned request.
  expect(stub.uploads[0]).toMatchObject({
    filename: "read1.fastq",
    size: 35,
  });
  expect((stub.uploads[0] as { checksum_sha256: string }).checksum_sha256).toMatch(/^[0-9a-f]{64}$/);

  await expect
    .poll(() => stub.submits.length, { message: "the pipeline must submit the job" })
    .toBe(1);
  expect(stub.submits[0]).toEqual({
    input_objects: ["analyses/uploads/read1.fastq"],
    params: { trim_front1: 0, trim_tail1: 0, quality_phred: 15, thread: 4 },
  });
  expect(stub.uploadBytes, "the object bytes must be POSTed to the presigned URL").toBeGreaterThan(0);

  // Forwarded to the job page, which shows the running state.
  await page.waitForURL(/\/analyses\/job-submit-1$/);
  await expect(page.getByText(/job running/i).first()).toBeVisible({ timeout: 20_000 });
});

test("an out-of-range parameter never reaches the upload pipeline", async ({ page }) => {
  const stub = await stubSubmitApi(page);
  await signInToFastp(page);

  await page.locator('input[type="file"]').setInputFiles({
    name: "read1.fastq",
    mimeType: "application/octet-stream",
    buffer: Buffer.from(">read1\nACGT\n"),
  });
  await page.locator("#quality_phred").fill("99");
  await page.locator('form button[type="submit"]').click();

  // The numeric input carries native min/max bounds, so the browser refuses the
  // submission before the form's own validateParam runs; the contract under
  // test is that no presigned upload is requested.
  await expect
    .poll(() => page.locator("#quality_phred").evaluate((element) => element.checkValidity()))
    .toBe(false);
  expect(stub.uploads).toHaveLength(0);
});
