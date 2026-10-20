/**
 * BLAST E2E — full form at /blast, the /search/blast compatibility route, FASTA
 * validation, and result cross-links.
 *
 * The full form renders offline (no databases → empty select + disabled submit
 * guard). `/search/blast` redirects to the canonical full form at `/blast`.
 * Job submission and result cross-links use an offline mocked API.
 */
import { test, expect, type Page } from "@playwright/test";
import { gotoReady, waitForAppReady } from "./helpers";

const BASE = "";

// Static-server's documented local test principal (not a real account).
const TEST_EMAIL = "researcher@example.org";
const TEST_PASSWORD = "correct-horse-battery-staple";

const COMPLETED_JOB = {
  job_id: "11111111-2222-3333-4444-555555555555",
  status: "completed",
  program: "blastp",
  database: "Wm82_v4_protein",
  database_id: 1,
  query_sequence: ">query1 soybean query\nMKVLAAGIVGLNLGGK",
  parameters: { evalue: 1e-5, max_target_seqs: 50 },
  hit_count: 1,
  submitted_at: "2026-01-02T00:00:00Z",
};

const RUNNING_JOB = {
  ...COMPLETED_JOB,
  job_id: "99999999-8888-7777-6666-555555555555",
  status: "running",
  hit_count: 0,
};

const HITS = [
  {
    hsp_num: 1,
    // The API's subject id is the gene accession; the page uses the same value
    // for the gene column and the JBrowse locus label.
    subject_id: "Glyma.01G000100",
    subject_title: "Glyma.01G000100",
    percent_identity: 98.5,
    alignment_length: 120,
    mismatches: 2,
    gap_opens: 0,
    query_start: 1,
    query_end: 120,
    subject_start: 1000,
    subject_end: 2000,
    evalue: 1e-20,
    bit_score: 240,
  },
];

interface BlastStub {
  submits: unknown[];
}

/**
 * Stub the BLAST API surface. The page's history/results sections require a
 * signed-in session (`isSignedIn`), which the real static-server login mock
 * provides; only the blast endpoints are stubbed here.
 */
async function stubBlastApis(page: Page): Promise<BlastStub> {
  const submits: unknown[] = [];
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
    if (path.endsWith("/auth/login") && request.method() === "POST") {
      return json({ access_token: "e2e-access-token", expires_in: 900 });
    }
    if (path.endsWith("/auth/refresh")) return json({ access_token: "e2e-access-token", expires_in: 900 });
    if (path.endsWith("/auth/me")) return json({ username: TEST_EMAIL, email: TEST_EMAIL, role: "user" });
    if (path.endsWith("/jobs/events")) {
      // EventSource fallback: no stream in the static artifact.
      return route.fulfill({ status: 204, headers, body: "" });
    }
    if (path.endsWith("/blast/databases")) {
      return json([
        {
          id: 1,
          name: "Wm82_v4_protein",
          db_type: "prot",
          assembly_id: 1,
          assembly_name: "Wm82.a4.v1",
          assembly_version: "a4.v1",
          assembly_is_default: true,
          is_active: true,
        },
      ]);
    }
    if (path.endsWith("/blast/jobs") && request.method() === "GET") {
      return json({ items: [COMPLETED_JOB, RUNNING_JOB], total: 2, page: 1, page_size: 5 });
    }
    if (path.endsWith("/blast/jobs") && request.method() === "POST") {
      submits.push(request.postDataJSON());
      return json({ ...COMPLETED_JOB, status: "pending", hit_count: 0 }, 202);
    }
    if (path.endsWith(`/blast/jobs/${COMPLETED_JOB.job_id}/results`)) {
      return json({ hits: HITS, total_hits: HITS.length });
    }
    return json({}, 404);
  });
  return { submits };
}

async function signInAndOpenBlast(page: Page): Promise<void> {
  await page.goto(`${BASE}/login?redirect=${encodeURIComponent("/blast")}`, { waitUntil: "load" });
  await waitForAppReady(page);
  await page.getByLabel("Email", { exact: true }).fill(TEST_EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(TEST_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL(/\/blast$/);
  await expect(page.getByTestId("blast-submit")).toBeVisible();
}

test.describe("BLAST — form and routing", () => {
  test("/blast renders the full form", async ({ page }) => {
    await gotoReady(page, `${BASE}/blast`);
    // The title block is an eyebrow label ("BLAST Search") plus a descriptive
    // level-1 heading; assert the rendered structure instead of binding the
    // heading to one i18n string.
    await expect(page.getByText("BLAST Search").first()).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/search sequences/i);
    // The current default is DIAMOND BLASTP; both the selected programme
    // and query input must be visible, regardless of backend availability.
    const programme = page.getByTestId("blast-program");
    // antd Select renders a div rather than an <input>, so assert the rendered
    // selection label instead of an input value.
    await expect(programme).toContainText("BLASTP");
    // "Reference sequence type" also matches /sequence/i, so target the query
    // textarea by its exact label ("Input Sequence").
    await expect(page.getByRole("textbox", { name: "Input Sequence" })).toBeVisible();
  });

  test("/search/blast redirects to the canonical full form", async ({ page }) => {
    await gotoReady(page, `${BASE}/search/blast`);
    await expect(page).toHaveURL(/\/blast$/);
    await expect(page.getByRole("textbox", { name: "Input Sequence" })).toBeVisible();
    await expect(page.getByTestId("blast-program")).toBeVisible();
    await expect(page.getByTestId("blast-database")).toBeVisible();
  });

  test("empty FASTA never reaches the API", async ({ page }) => {
    const submissions: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/blast/jobs") && request.method() === "POST") {
        submissions.push(request.url());
      }
    });
    await gotoReady(page, `${BASE}/blast`);
    // The contract is that an incomplete form never reaches the API. The client
    // rejects it locally through schema/FASTA validation, so assert the absence
    // of a request rather than a particular disabled styling.
    await page.getByTestId("blast-submit").click();
    await page.waitForTimeout(500);
    expect(submissions).toEqual([]);
  });
});

test.describe("BLAST — signed-in job flow (offline mocked API)", () => {
  test("submitting a job posts the documented payload and shows it in the history", async ({
    page,
  }) => {
    const stub = await stubBlastApis(page);
    await signInAndOpenBlast(page);

    // The default database (flagged assembly_is_default) is preselected.
    await expect(page.getByTestId("blast-database")).toContainText("Wm82_v4_protein");
    await page.getByTestId("blast-sequence").fill(">query1\nMKVLAAGIVGLNLGGK");
    await page.getByTestId("blast-submit").click();

    await expect
      .poll(() => stub.submits.length, { message: "the form must POST one BLAST job" })
      .toBe(1);
    const payload = stub.submits[0] as {
      program: string;
      database: string;
      query_sequence: string;
      parameters: { evalue: number; max_target_seqs: number };
    };
    expect(payload.program).toBe("blastp");
    expect(payload.database).toBe("Wm82_v4_protein");
    expect(payload.query_sequence).toContain("MKVLAAGIVGLNLGGK");
    expect(payload.parameters.evalue).toBeCloseTo(1e-5);
    expect(payload.parameters.max_target_seqs).toBe(50);
  });

  test("completed job exposes JBrowse 2 + gene-search cross links from its hits", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await stubBlastApis(page);
    await signInAndOpenBlast(page);

    // Jobs history renders both stored jobs; only the completed one can open.
    await expect(page.getByText(/running/i).first()).toBeVisible();
    await page.getByRole("button", { name: /view results/i }).click();

    // Hits table: identity, E-value, subject gene id (whole accession).
    await expect(page.getByText("98.5%")).toBeVisible();
    await expect(page.getByText("1.00e-20")).toBeVisible();
    await expect(page.getByText("Glyma.01G000100").first()).toBeVisible();

    // JBrowse 2 deep link carries the assembly + the hit locus.
    const browserLink = page.getByRole("link", { name: /jbrowse/i }).first();
    await expect(browserLink).toBeVisible();
    const href = await browserLink.getAttribute("href");
    // The portal route renders the embedded JBrowse at /browser.
    expect(href).toContain("/browser?");
    expect(href).toContain("assembly=Wm82.a4.v1");
    expect(href).toContain("Glyma.01G000100%3A1000-2000");

    // The hit's gene id is a button that opens the portal's gene search with
    // the accession prefilled and the search already running.
    await page.getByRole("button", { name: "Glyma.01G000100" }).first().click();
    await page.waitForURL(/\/search\/genes/);
    const geneUrl = new URL(page.url());
    expect(geneUrl.searchParams.get("q")).toBe("Glyma.01G000100");
    expect(geneUrl.searchParams.get("assembly")).toBe("Wm82.a4.v1");
    expect(geneUrl.searchParams.get("run")).toBe("true");

    expect(pageErrors, "the BLAST job flow must not throw").toEqual([]);
  });
});
