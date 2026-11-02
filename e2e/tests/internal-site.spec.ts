/**
 * Internal site variant E2E — root base path + internal-only surfaces.
 *
 * Rewritten 2026-10-18: the previous version of this spec encoded the retired
 * Vue UI's data-testids (`login-form`, `search-input`, `search-internal-row`,
 * `mutant-detail`, …) and a `v-model`-specific interaction model. After the
 * React migration none of those ids existed, so the suite could never pass;
 * it is not part of the CI lane, which hid the rot. The tests below assert the
 * invariant that actually matters for the dual-site boundary: the internal
 * artifact is served at the origin root (never `/soymutdb-next`), it carries
 * the internal-only index policy, and its root-relative login surface works.
 */
import { test, expect } from "@playwright/test";
import { gotoReady, trackErrors } from "./helpers";

const OFFLINE = !process.env.INTERNAL_BASE_URL;
const BASE = process.env.INTERNAL_BASE_URL ?? "http://localhost:4175/";
const PUBLIC_BASE_PATH = "/soymutdb-next";
const SKIP_NO_BASE = "requires INTERNAL_BASE_URL for a deployed internal stack";

function underBase(relative = ""): string {
  return new URL(relative, BASE).toString();
}

const VALID_CREDENTIALS = {
  email: "researcher@example.org",
  password: "correct-horse-battery-staple",
};

test.describe("internal site variant — separate origin/base path", () => {
  test("serves the internal artifact at its root base with internal-only policy", async ({
    page,
    request,
  }) => {
    test.skip(!OFFLINE && !process.env.INTERNAL_BASE_URL, SKIP_NO_BASE);

    const errors = trackErrors(page);
    await gotoReady(page, underBase());

    // The React app shell is mounted and the URL is the origin root, not the
    // public Pages sub-path.
    await expect(page.getByTestId("antd-home")).toBeVisible();
    expect(new URL(page.url()).pathname).not.toMatch(
      new RegExp(`^${PUBLIC_BASE_PATH}(/|$)`),
    );

    // Exactly one robots meta, carrying the full internal index policy. A
    // duplicate tag is invalid head markup (and used to be emitted here).
    const robotsMeta = page.locator('meta[name="robots"]');
    await expect(robotsMeta).toHaveCount(1);
    await expect(robotsMeta).toHaveAttribute("content", /noindex/i);
    await expect(robotsMeta).toHaveAttribute("content", /nofollow/i);
    await expect(robotsMeta).toHaveAttribute("content", /noarchive/i);

    // The internal artifact publishes a deny-all robots.txt (the public one
    // allows crawling), which is an internal-only surface.
    const robots = await request.get(underBase("robots.txt"));
    expect(robots.status()).toBe(200);
    expect(await robots.text()).toMatch(/^\s*Disallow:\s*\/\s*$/m);

    expect(
      errors,
      "the internal document must render without unexpected console errors or pageerrors",
    ).toEqual([]);
  });

  test("root-relative login surface renders without testing credentials", async ({
    page,
  }) => {
    test.skip(!OFFLINE && !process.env.INTERNAL_BASE_URL, SKIP_NO_BASE);

    const errors = trackErrors(page);
    await gotoReady(page, underBase("login"));

    await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
    const email = page.getByLabel("Email", { exact: true });
    const password = page.getByLabel("Password", { exact: true });
    await expect(email).toBeVisible();
    await expect(password).toBeVisible();
    await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();

    // No credential is filled or submitted by this suite.
    await expect(email).toHaveValue("");
    await expect(password).toHaveValue("");
    expect(new URL(page.url()).pathname).toBe("/login");

    expect(
      errors,
      "the internal login surface must render without unexpected console errors",
    ).toEqual([]);
  });

  test("successful login redirects to the internal /search, never the public prefix", async ({
    page,
  }) => {
    test.skip(!OFFLINE && !process.env.INTERNAL_BASE_URL, SKIP_NO_BASE);

    const errors = trackErrors(page);
    // The internal artifact bakes an absolute API origin, so intercept the
    // cross-origin login the way a deployed API would answer it.
    await page.route("**/api/v1/auth/login", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: {
          "Set-Cookie": "soymutdb_e2e_refresh=mock; Path=/; HttpOnly; SameSite=Lax",
        },
        body: JSON.stringify({ access_token: "e2e-access-token", expires_in: 900 }),
      });
    });

    await gotoReady(page, underBase("login?redirect=%2Fsearch"));
    await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
    await page.getByLabel("Email", { exact: true }).fill(VALID_CREDENTIALS.email);
    await page.getByLabel("Password", { exact: true }).fill(VALID_CREDENTIALS.password);
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page).toHaveURL(/\/search$/);
    expect(new URL(page.url()).pathname).not.toMatch(
      new RegExp(`^${PUBLIC_BASE_PATH}(/|$)`),
    );

    expect(
      errors,
      "the internal login redirect must stay free of script errors",
    ).toEqual([]);
  });
});
