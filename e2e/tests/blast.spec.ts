/**
 * BLAST E2E — account form at /blast, anonymous /search/blast entry, FASTA
 * validation, and result cross-links.
 *
 * The full form renders offline (no databases → empty select + disabled submit
 * guard). `/search/blast` executes anonymous capability-authorized jobs.
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
  // Provenance of the searched database, exactly as the API returns it
  // (BlastJobResponse.release_id / .assembly_name): the genome-browser link
  // is pinned to the release the hits were computed against, so a job from an
  // older release keeps that release.
  release_id: 7,
  assembly_name: "Wm82.a4.v1",
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
    // This fixture's protein ID also has an exact gene record. Real protein
    // IDs need not map; the browser action must resolve rather than infer.
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

/**
 * One catalog row in the shape `GET /blast/databases` actually returns.
 *
 * `GET /blast/databases` is served by `BlastCatalogService.list_databases`,
 * which filters on `is_active`, `engine` and `build_status` BEFORE responding
 * (apps/api/app/services/blast_service.py:129-134) — so a real response can
 * never omit them. The fixture therefore has to carry them too: the portal
 * re-applies the same predicate in `compatibleBlastDatabases`
 * (packages/api-client/src/blast.ts:142-148), and an absent `engine` compares
 * `undefined === "ncbi_blast"` → false, which empties the select instead of
 * failing loudly. `engine`/`build_status` are optional in the OpenAPI schema
 * with defaults, but a database that only carries the defaults is not one the
 * server would have listed; `ncbi_blast` + `published` is what
 * `blast.tsx:128-135` submits by default.
 *
 * Shared by both stubs below on purpose: the signed-in and anonymous entries
 * read the same catalog, and they drifted apart once already.
 */
const DB_CATALOG_ROW = {
  id: 1,
  name: "Wm82_v4_protein",
  db_type: "prot",
  assembly_id: 1,
  assembly_name: "Wm82.a4.v1",
  assembly_version: "a4.v1",
  assembly_is_default: true,
  release_id: 7,
  is_active: true,
  engine: "ncbi_blast",
  build_status: "published",
  created_at: "2026-01-01T00:00:00Z",
} as const;

/**
 * What `GET /blast/jobs/{id}/hits/{subject}/genome-target` returns for a
 * resolved subject (apps/api/app/services/blast_service.py:435-447). The
 * client refuses to build a link unless the response echoes the job's own
 * release AND assembly, so a stub that answered `{}` could never open the
 * browser — the assertion would have been about the mock, not the page.
 */
const GENOME_TARGET = {
  status: "resolved",
  gene_id: "Glyma.01G000100",
  chromosome: "chr01",
  start: 12000,
  end: 15000,
  strand: "+",
  release_id: 7,
  assembly_id: 1,
  assembly_name: "Wm82.a4.v1",
  locus: "chr01:12000-15000",
  resolution: "gene_accession",
} as const;

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
    if (path.endsWith("/auth/me")) return json({ username: TEST_EMAIL, email: TEST_EMAIL, role_name: "researcher", effective_roles: ["viewer", "researcher"] });
    if (path.endsWith("/jobs/events")) {
      // EventSource fallback: no stream in the static artifact.
      return route.fulfill({ status: 204, headers, body: "" });
    }
    if (path.endsWith("/blast/databases")) {
      return json([DB_CATALOG_ROW]);
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
    if (path.endsWith(`/blast/jobs/${COMPLETED_JOB.job_id}/hits/Glyma.01G000100/genome-target`)) {
      return json(GENOME_TARGET);
    }
    if (path.endsWith("/genes/assemblies")) {
      expect(request.headers()["x-soymutdb-release"]).toBe("7");
      return json([{ id: 1, name: "Wm82.a4.v1", is_default: true }]);
    }
    if (path.endsWith("/genes/Glyma.01G000100")) {
      expect(request.headers()["x-soymutdb-release"]).toBe("7");
      expect(url.searchParams.get("assembly_id")).toBe("1");
      return json({ gene_id: "Glyma.01G000100", assembly_id: 1, chromosome: "chr01", start_pos: 12000, end_pos: 15000 });
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
    // Scoped by accessible name, not by level alone: the portal renders a
    // second `<h1>` (the hidden document title block), so a bare
    // `heading[level=1]` lookup is a strict-mode violation, not a product bug.
    await expect(
      page.getByRole("heading", { level: 1, name: /search sequences/i }),
    ).toBeVisible();
    // The current default is NCBI BLAST+ / BLASTP; both the selected programme
    // and query input must be visible, regardless of backend availability.
    //
    // The programme `<Select>` exposes a combobox named by
    // `blastPublic.program` ("Search program") and carries no test id — this
    // assertion used to reach for `blast-program`, which never existed on this
    // route. antd 6 puts `role="combobox"` on an inner readonly `<input>`
    // (empty from the DOM's point of view) and renders the chosen label as a
    // sibling text node inside `.ant-select-content`, so the rendered value is
    // read from that wrapper. Asserting the whole content is the point: a
    // `toContainText("BLASTP")` would also pass for "TBLASTN"/"TBLASTX".
    const programme = page.getByRole("combobox", { name: "Search program", exact: true });
    await expect(programme).toBeVisible();
    expect(
      (await programme.evaluate((element) => element.closest(".ant-select-content")?.textContent?.trim()))
        ?? "",
      "the programme select must show the default BLASTP",
    ).toBe("BLASTP");
    // The query textarea is labelled per program (`blastSearch.proteinInput`
    // for a protein program), not "Input Sequence" — that key is unused on
    // both BLAST routes, so the old name only ever matched an empty page.
    await expect(page.getByRole("textbox", { name: "Protein FASTA query" })).toBeVisible();
  });

  test("/search/blast keeps the anonymous entry separate", async ({ page }) => {
    await gotoReady(page, `${BASE}/search/blast`);
    await expect(page).toHaveURL(/\/search\/blast$/);
    await expect(page.getByRole("heading", { name: "Anonymous BLAST" })).toBeVisible();
    await expect(page.getByPlaceholder("Paste a protein FASTA sequence")).toBeVisible();
    await expect(page.getByRole("link", { name: /signed-in workflow/i })).toBeVisible();
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
    await expect(page.getByTestId("blast-submit")).toBeDisabled();
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

    // Resolve one exact gene on click, then navigate in the same tab. The
    // interval is the gene's genomic span, never the protein's AA alignment.
    await page.getByTestId("blast-gbrowse-link").first().click();
    await page.waitForURL(/\/browser\?/);
    const browserUrl = new URL(page.url());
    expect(browserUrl.searchParams.get("assembly")).toBe("Wm82.a4.v1");
    // TanStack serializes numeric-looking string values as JSON strings.
    // Assert the decoded release value used by the browser route.
    expect(String(JSON.parse(browserUrl.searchParams.get("release")!))).toBe("7");
    expect(browserUrl.searchParams.get("locus")).toBe("chr01:12000-15000");

    expect(pageErrors, "the BLAST job flow must not throw").toEqual([]);
  });
});


test("anonymous BLAST submits, polls and downloads without account calls", async ({ page }) => {
  const privateCalls: string[] = [];
  let submissions = 0;
  const token = "browser-memory-capability";
  await page.route(/\/api\/v1\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const headers = {
      "access-control-allow-origin": request.headers()["origin"] ?? "*",
      "access-control-allow-headers": "content-type,x-soymutdb-release,x-blast-token",
      "access-control-allow-methods": "GET,POST,OPTIONS",
    };
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers });
    const json = (body: unknown, status = 200) => route.fulfill({
      status, headers, contentType: "application/json", body: JSON.stringify(body),
    });
    expect(url.search).not.toContain(token);
    if (url.pathname.includes("/blast/jobs") || url.pathname.endsWith("/auth/me") || url.pathname.endsWith("/jobs/events")) {
      privateCalls.push(url.pathname);
    }
    if (url.pathname.endsWith("/blast/databases")) return json([DB_CATALOG_ROW]);
    if (url.pathname.endsWith("/blast/public/jobs") && request.method() === "POST") {
      submissions++;
      expect(request.headers()["authorization"]).toBeUndefined();
      expect(request.postDataJSON().program).toBe("blastp");
      return json({ job: { ...COMPLETED_JOB, status: "running" }, access_token: token,
        expires_at: new Date(Date.now() + 3600000).toISOString() }, 201);
    }
    if (url.pathname.includes("/blast/public/jobs/")) {
      expect(request.headers()["x-blast-token"]).toBe(token);
      expect(request.headers()["authorization"]).toBeUndefined();
      if (url.pathname.endsWith("/results")) return json({ job_id: COMPLETED_JOB.job_id,
        status: "completed", hits: HITS, total_hits: 1,
        download_url: "https://objects.example/anonymous-results.tsv" });
      return json(COMPLETED_JOB);
    }
    return json({}, 404);
  });
  await gotoReady(page, "/search/blast");
  // Same per-program label the signed-in entry uses.
  await page.getByRole("textbox", { name: "Protein FASTA query" }).fill(">query\nMKVLAAGIVGLNLGGK");
  await page.getByRole("button", { name: "Run BLAST", exact: true }).click();
  await expect(page.getByText("Glyma.01G000100")).toBeVisible();
  await expect(page.getByRole("link", { name: "Download raw results" })).toHaveAttribute(
    "href", "https://objects.example/anonymous-results.tsv",
  );
  expect(submissions).toBe(1);
  expect(privateCalls).toEqual([]);
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain(token);
  expect(page.url()).not.toContain(token);
  await page.screenshot({ path: "test-results-public/blast-anonymous-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "Anonymous BLAST" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: "test-results-public/blast-anonymous-mobile.png", fullPage: true });
});
