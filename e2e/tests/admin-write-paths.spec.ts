/**
 * Authenticated admin write-path gate: editing and saving the primary site
 * navigation.
 *
 * `admin-shell.spec.ts` proves the console *mounts*; it never makes the console
 * write anything. This flow is what an operator uses to change the live site,
 * and it was only covered by Vitest — where the API client is mocked at the
 * module boundary, so a wrong request body or a missing `expected_version`
 * cannot be observed.
 *
 * Two harness facts this spec depends on, both learned by measurement:
 *
 * 1. The console restores a session from `GET /auth/refresh` on every full page
 *    load. Answering that before the form is submitted makes it treat the
 *    visitor as already signed in and navigate away from `/login`, so the
 *    identifier field never renders. Session endpoints are therefore gated on a
 *    real sign-in.
 * 2. `/site-control` reads four endpoints before its editor appears
 *    (`settings/general/document`, `admin/features`, `site/navigation`,
 *    `settings/header_external/document`). Leaving any of them at a bare 404
 *    keeps the page in its loading state — verified by dumping the rendered
 *    text, which then contained only the shell.
 * 3. This build's console is Chinese-first, so every label is Chinese:
 *    `分组 1 英文标题`, `拖拽排序 Main`, `添加分组`, `保存外部站点导航`. Locators
 *    below accept either language so the same spec survives a locale flip.
 */
import { test, expect, type Page, type Route } from "@playwright/test";

// The static server's documented local test principal (not a real account).
const TEST_IDENTIFIER = "researcher@example.org";
const TEST_PASSWORD = "correct-horse-battery-staple";

const SETTINGS_VERSION = 7;

/** A stored navigation document in the shape `parseHeaderNavigationJson` accepts. */
const STORED_NAVIGATION = {
  schema_version: 1,
  groups: [
    {
      id: "main",
      title_en: "Main",
      title_zh: "主导航",
      enabled: true,
      order: 0,
      links: [
        {
          id: "home-link",
          label_en: "Home",
          label_zh: "首页",
          target: "internal",
          href: "/",
          enabled: true,
          order: 0,
          feature: null,
        },
      ],
    },
    {
      id: "tools",
      title_en: "Tools",
      title_zh: "工具",
      enabled: true,
      order: 1,
      links: [],
    },
  ],
};

type Captured = { patch: { body: unknown } | null };

async function stubConsole(
  page: Page,
  options: { captured: Captured; patchStatus?: number },
): Promise<void> {
  const { captured, patchStatus = 200 } = options;
  let signedIn = false;

  await page.route(/\/api\/v1\//, async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const origin = request.headers()["origin"];
    const headers: Record<string, string> = {
      "access-control-allow-origin": origin ?? "*",
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "authorization,content-type,x-soymutdb-release,x-csrf-token",
      "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
      vary: "Origin",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", headers, body: JSON.stringify(body) });
    const path = url.pathname;

    if (path.endsWith("/auth/login")) {
      signedIn = true;
      return json({ access_token: "e2e-access-token", expires_in: 900 });
    }
    // No session before the form is submitted: 401 keeps the login form mounted
    // instead of letting the console restore a session and navigate away.
    if (!signedIn) return json({ detail: "no session" }, 401);
    if (path.endsWith("/auth/refresh")) {
      return json({ access_token: "e2e-access-token", expires_in: 900 });
    }
    if (path.endsWith("/auth/me")) {
      return json({
        username: TEST_IDENTIFIER,
        email: TEST_IDENTIFIER,
        effective_roles: ["administrator"],
      });
    }

    // The four reads `/site-control` needs before its editor renders.
    if (path.endsWith("/admin/settings/general/document")) {
      return json({
        section: "general",
        version: 1,
        values: { siteName: "SoyMutDB", databaseKind: "genome" },
      });
    }
    if (path.endsWith("/admin/features")) {
      return json({ features: [{ key: "blast", enabled: true }] });
    }
    if (path.endsWith("/site/navigation")) {
      return json({ variant: "external", groups: [] });
    }
    if (path.endsWith("/admin/settings/header_external/document")) {
      return json({
        section: "header_external",
        version: SETTINGS_VERSION,
        values: { navigation_json: JSON.stringify(STORED_NAVIGATION) },
      });
    }
    if (request.method() === "PATCH" && path.endsWith("/admin/settings/header_external")) {
      captured.patch = { body: request.postDataJSON() };
      if (patchStatus === 409) return json({ detail: "version conflict" }, 409);
      return json({
        section: "header_external",
        version: SETTINGS_VERSION + 1,
        values: { navigation_json: JSON.stringify(STORED_NAVIGATION) },
      });
    }
    // No other console fixtures: honest 404 so pages show their own empty state.
    return json({}, 404);
  });
}

async function signIn(page: Page): Promise<void> {
  await page.goto("/login", { waitUntil: "load" });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.appReady ?? null), {
      message: "the admin SPA never announced readiness (<html data-app-ready>)",
      timeout: 20_000,
    })
    .toBe("true");
  await page.getByTestId("admin-identifier").fill(TEST_IDENTIFIER);
  await page.getByTestId("admin-password").fill(TEST_PASSWORD);
  await page.getByTestId("admin-login-submit").click();
  await expect(page.getByTestId("shell-header")).toBeVisible({ timeout: 20_000 });
}

test("saving the primary navigation sends the edited document with its base version", async ({
  page,
}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const captured: Captured = { patch: null };
  await stubConsole(page, { captured });
  await signIn(page);

  await page.goto("/site-control", { waitUntil: "load" });
  await expect(page.getByTestId("shell-header")).toBeVisible({ timeout: 20_000 });

  // The stored document is what the editor renders.
  const firstGroup = page.getByRole("textbox", {
    name: /(Group 1 English title|分组 1 英文标题)/,
  });
  await expect(firstGroup).toHaveValue("Main", { timeout: 20_000 });
  await expect(
    page.getByRole("textbox", { name: /(Group 2 English title|分组 2 英文标题)/ }),
  ).toHaveValue("Tools");
  // A drag handle per group, naming the group it moves.
  await expect(page.getByLabel(/(Reorder Main|拖拽排序 Main)/)).toBeVisible();

  // Deterministic dirty transition: adding a group changes the document without
  // depending on drag physics, which keeps the save assertion stable.
  const saveButton = page.getByRole("button", { name: /(Save .*navigation|保存.*导航)/ });
  await expect(saveButton).toBeDisabled();
  await page.getByRole("button", { name: /(Add group|添加分组)/ }).click();
  await expect(saveButton).toBeEnabled();

  await saveButton.click();
  await expect
    .poll(() => captured.patch, {
      message: "the editor never PATCHed the navigation settings document",
      timeout: 15_000,
    })
    .not.toBeNull();

  const body = captured.patch!.body as {
    expected_version: number;
    values: { navigation_json: string };
  };
  // Optimistic concurrency: without the base version the server cannot reject a
  // second editor's write, which is the whole point of the versioned endpoint.
  expect(body.expected_version).toBe(SETTINGS_VERSION);
  const saved = JSON.parse(body.values.navigation_json) as {
    schema_version: number;
    groups: Array<{ id: string }>;
  };
  expect(saved.schema_version).toBe(1);
  expect(saved.groups.map((group) => group.id)).toEqual(["main", "tools", expect.any(String)]);
  expect(pageErrors, "saving the navigation must not throw").toEqual([]);
});

test("a version conflict is surfaced instead of silently discarding the edit", async ({ page }) => {
  const captured: Captured = { patch: null };
  await stubConsole(page, { captured, patchStatus: 409 });
  await signIn(page);

  await page.goto("/site-control", { waitUntil: "load" });
  await expect(
    page.getByRole("textbox", { name: /(Group 1 English title|分组 1 英文标题)/ }),
  ).toHaveValue("Main", { timeout: 20_000 });

  await page.getByRole("button", { name: /(Add group|添加分组)/ }).click();
  await page.getByRole("button", { name: /(Save .*navigation|保存.*导航)/ }).click();

  await expect.poll(() => captured.patch, { timeout: 15_000 }).not.toBeNull();
  // A 409 means another editor wrote first; the operator has to know their draft
  // was not applied.
  await expect(
    // The console is Chinese-first: the actual copy is
    // "导航已在其他会话中被修改，已加载最新版本，请检查编辑内容后重新保存。".
    page.getByText(/changed in another session|导航已在其他会话中被修改/i).first(),
  ).toBeVisible({ timeout: 10_000 });
});

/**
 * Drag one sortable element onto another with a real pointer sequence.
 *
 * dnd-kit's `PointerSensor` here is configured with
 * `activationConstraint: { distance: 4 }`: it ignores a press until the pointer
 * has travelled 4px, so a single `mouse.move(start→end)` is not a drag — the
 * sensor never activates and the list does not reorder. The intermediate moves
 * below are what make this a drag rather than a click-and-release.
 */
async function dragOnto(page: Page, fromLabel: RegExp, toLabel: RegExp): Promise<void> {
  const from = page.getByLabel(fromLabel);
  const to = page.getByLabel(toLabel);
  const source = await from.boundingBox();
  const target = await to.boundingBox();
  if (!source || !target) throw new Error("drag source or target has no bounding box");

  const startX = source.x + source.width / 2;
  const startY = source.y + source.height / 2;
  const endX = target.x + target.width / 2;
  const endY = target.y + target.height / 2;

  await page.mouse.move(startX, startY);
  await page.mouse.down();
  // Past the 4px activation threshold first, then in steps so dnd-kit keeps
  // receiving pointermove events instead of a single teleport.
  await page.mouse.move(startX, startY + 8, { steps: 2 });
  await page.mouse.move(endX, endY, { steps: 12 });
  await page.mouse.up();
}

test("dragging a navigation group reorders the document that is saved", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const captured: Captured = { patch: null };
  await stubConsole(page, { captured });
  await signIn(page);

  await page.goto("/site-control", { waitUntil: "load" });
  await expect(
    page.getByRole("textbox", { name: /(Group 1 English title|分组 1 英文标题)/ }),
  ).toHaveValue("Main", { timeout: 20_000 });

  // Stored order is main → tools. Drag the first group's handle onto the second.
  await dragOnto(page, /(Reorder Main|拖拽排序 Main)/, /(Reorder Tools|拖拽排序 Tools)/);

  // A drag that reorders marks the document dirty; the Save button is disabled
  // while the document is clean, so this is also the "the drag actually landed"
  // signal.
  const saveButton = page.getByRole("button", { name: /(Save .*navigation|保存.*导航)/ });
  await expect(saveButton, "the drag did not change the document").toBeEnabled({
    timeout: 10_000,
  });

  await saveButton.click();
  await expect.poll(() => captured.patch, { timeout: 15_000 }).not.toBeNull();

  const body = captured.patch!.body as { values: { navigation_json: string } };
  const saved = JSON.parse(body.values.navigation_json) as { groups: Array<{ id: string }> };
  // The saved order is the dragged order — not the stored one. This is the part
  // that a "drag handle exists" assertion cannot see.
  expect(saved.groups.map((group) => group.id)).toEqual(["tools", "main"]);
  expect(pageErrors, "dragging a group must not throw").toEqual([]);
});
