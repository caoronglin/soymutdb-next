/**
 * API shape resilience: the entity detail pages must degrade, not crash.
 *
 * Rounds 14–15 shipped runtime shape guards (`apps/web/src/lib/api-contract-guards.ts`)
 * after the gene page crashed on a malformed 200 (`undefined.toLocaleString()`),
 * caused by a list envelope arriving where a detail record was expected. This
 * spec proves the same contract end-to-end on the built artifact: every entity
 * detail page is given a wrong-shape 200 from an intercepted request and must
 * render its empty/error state without a pageerror, without React's error
 * boundary, and without the `toLocaleString` TypeError.
 *
 * Interception (not a static-server fixture) keeps the failure mode honest for
 * all three routes and works against the production-shaped artifact whose API
 * base is an absolute origin.
 */
import { test, expect, type Page } from "@playwright/test";
import { TOLERATED_CONSOLE_ERRORS, waitForAppReady } from "./helpers";

interface ShapeCase {
  name: string;
  url: string;
  /** Matches the detail endpoint only (assemblies/featured are left alone). */
  apiPattern: RegExp;
  /** Wrong-shape body that used to be trusted as the detail record. */
  malformedBody: unknown;
  /** User-visible state the page must reach instead of crashing. */
  expectedText: RegExp;
}

const CASES: ShapeCase[] = [
  {
    name: "gene detail",
    url: "/genes/Glyma.01G000100",
    // The search-list envelope; this exact shape crashed the genome view.
    apiPattern: /\/api\/v1\/genes\/(?!assemblies)[^/?]+(?:\?|$)/,
    malformedBody: {
      items: [],
      next_cursor: null,
      has_more: false,
      page: 1,
      page_size: 20,
      total: 0,
      total_pages: 0,
    },
    expectedText: /no data available/i,
  },
  {
    name: "mutant detail",
    url: "/mutants/SM7K3ZQ9P2A",
    apiPattern: /\/api\/v1\/mutants\/[^/?]+(?:\?|$)/,
    malformedBody: { items: [] },
    expectedText: /mutant line was not found|not public yet/i,
  },
  {
    name: "news detail",
    url: "/news/hello",
    apiPattern: /\/api\/v1\/news\/(?!featured)[^/?]+(?:\?|$)/,
    malformedBody: { items: [] },
    expectedText: /failed to load news|article not found/i,
  },
];

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (TOLERATED_CONSOLE_ERRORS.some((pattern) => pattern.test(text))) return;
    errors.push(text);
  });
  return errors;
}

for (const shapeCase of CASES) {
  test(`${shapeCase.name} renders its degraded state for a wrong-shape 200`, async ({
    page,
    baseURL,
  }) => {
    const errors = collectConsoleErrors(page);
    await page.route(shapeCase.apiPattern, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(shapeCase.malformedBody),
      }),
    );

    // Resolve relative to the configured baseURL rather than hard-coding a
    // host; a leading "/" would drop any sub-path prefix a target may use.
    await page.goto(new URL(shapeCase.url.replace(/^\//, ""), baseURL).toString());
    await waitForAppReady(page);

    // The page reached a real UI state, not an empty root or a crash fallback.
    const rendered = await page.evaluate(() => ({
      rootChildren: document.querySelector("#root")?.childElementCount ?? 0,
      text: document.body.innerText,
    }));
    expect(rendered.rootChildren, "the route left #root empty").toBeGreaterThan(0);
    // Match the visible degraded state via innerText: the antd Empty image also
    // carries a hidden `<title>No data</title>`, which a bare getByText matches.
    expect(rendered.text).toMatch(shapeCase.expectedText);
    expect(rendered.text).not.toContain("Something went wrong");

    const fatal = errors.filter((message) =>
      /toLocaleString|Cannot read properties of undefined|error boundary/i.test(message),
    );
    expect(fatal, `shape guard regression on ${shapeCase.name}: ${fatal.join("\n")}`).toEqual([]);
  });
}
