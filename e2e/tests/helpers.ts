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

/**
 * Console/pageerror classes that are environment or browser-security noise
 * rather than script bugs. A cross-origin deployment surfaces a failed request
 * as a console error even though the app renders its handled error state, and
 * the SSG CSP meta emits a frame-ancestors warning on every page.
 */
export const TOLERATED_CONSOLE_ERRORS: readonly RegExp[] = [
  /Failed to load resource/i,
  /net::ERR_/i,
  /ERR_ABORTED/i,
  /Failed to fetch/i,
  /NetworkError/i,
  /Load failed/i,
  /frame-ancestors/i,
];

/**
 * Record unexpected console errors and pageerrors until the end of the test.
 * A non-empty result is a regression; compare it with `toEqual([])`.
 */
export function trackErrors(
  page: Page,
  tolerated: readonly RegExp[] = TOLERATED_CONSOLE_ERRORS,
): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (tolerated.some((pattern) => pattern.test(text))) return;
    errors.push(`console: ${text}`);
  });
  return errors;
}
