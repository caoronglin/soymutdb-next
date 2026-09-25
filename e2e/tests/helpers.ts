/**
 * Shared helpers for the public-artifact suites.
 *
 * The web artifact is a replacement-render SPA: the build-time prerendered
 * markup is inert and only becomes interactive after Vue's first commit
 * ("handoff"). `apps/web/src/main.ts` announces that boundary on
 * `<html data-app-ready>`, so a spec must wait for it before interacting —
 * otherwise a click can land on the static fallback and be silently discarded.
 */
import { expect, type Page } from "@playwright/test";

/**
 * Wait until the SPA owns the document. Fails with a clear message instead of
 * letting subsequent locator actions time out on inert markup.
 */
export async function waitForAppReady(page: Page): Promise<void> {
  await expect
    .poll(
      () => page.evaluate(() => document.documentElement.dataset.appReady ?? null),
      {
        message:
          "the SPA never announced readiness (<html data-app-ready>) — the artifact stayed on inert SSG markup",
        timeout: 15_000,
      },
    )
    .toBe("true");
}

/** Navigate to a route and wait for the interactive document. */
export async function gotoReady(page: Page, url: string): Promise<void> {
  await page.goto(url);
  await waitForAppReady(page);
}
