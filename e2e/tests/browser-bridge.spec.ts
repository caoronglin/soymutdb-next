/**
 * Portal ↔ JBrowse postMessage bridge — offline artifact gate.
 *
 * The portal embeds JBrowse in an iframe and only trusts a `ready` envelope that
 * passed origin, source-window and envelope validation; the embedded app is a
 * separate artifact, so the deployed `portal-embed` gate needs the real genome
 * browser. This gate replaces the iframe document with a small harness served at
 * the baked JBROWSE origin, which lets the browser suite exercise the whole
 * handshake contract offline:
 *
 *   portal -> init (assembly/locus/tracks/release) -> harness records it
 *   harness -> ready -> portal shows the browser and the readiness marker
 *   harness -> locus-change -> portal mirrors the locus into the URL + input
 *   harness -> error -> portal renders the error state (never a silent hang)
 */
import { test, expect, type Page } from "@playwright/test";

import { gotoReady } from "./helpers";

// The artifact resolves VITE_JBROWSE_URL to the same-origin `/jbrowse` path when
// it is unset (the demo build), so the iframe document is served by the static
// server and its origin equals the portal origin.
// The iframe document is either the configured absolute JBrowse origin or the
// same-origin `/jbrowse` fallback (an artifact built without
// VITE_JBROWSE_BASE_URL); serve the harness for both shapes.
const JBROWSE_FRAME = /jbrowse\.soymutdb\.test|\/jbrowse(?:\?|$)/;

/** A minimal JBrowse stand-in that speaks the documented bridge contract. */
const HARNESS = `<!doctype html>
<html><head><meta charset="utf-8"><title>jbrowse harness</title></head>
<body>
<script>
  window.__bridge = { received: [] };
  window.addEventListener("message", function (event) {
    window.__bridge.received.push(event.data);
  });
  function send(type, payload) {
    parent.postMessage({ source: "soymutdb-jbrowse", version: 1, type: type, payload: payload }, "*");
  }
  window.__emitLocus = function (locus) {
    send("locus-change", { assembly: "Wm82.a4.v1", locus: locus });
  };
  window.__emitError = function (message) {
    send("error", { message: message });
  };
  // Reply after the portal's message listener is mounted (the iframe is created
  // during the portal render, so a same-tick message could be missed).
  setTimeout(function () { send("ready", { assembly: "Wm82.a4.v1", locus: "chr01:1000-2000" }); }, 300);
</script>
</body></html>`;

async function stubJbrowseFrame(page: Page): Promise<void> {
  await page.route(JBROWSE_FRAME, (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: HARNESS }),
  );
}

test("bridge handshake feeds the iframe init and mirrors locus changes into the URL", async ({
  page,
}) => {
  await stubJbrowseFrame(page);
  await gotoReady(page, "/browser?assembly=Wm82.a4.v1&locus=chr01:1000-2000&tracks=gene_models&release=R7");

  const iframe = page.getByTestId("browser-iframe");
  await expect(iframe).toHaveAttribute("data-bridge-status", "ready", { timeout: 20_000 });

  // The portal sent the deep-link session into the iframe.
  const frame = page.frameLocator('[data-testid="browser-iframe"]');
  const init = await frame
    .locator("body")
    .evaluate(() =>
      (window as unknown as { __bridge?: { received: Array<{ type?: string; source?: string; version?: number; payload?: Record<string, unknown> }> } }).__bridge?.received.find(
        (message) => message.type === "init",
      ),
    );
  expect(init, "the portal must post a bridge init message").toBeTruthy();
  expect(init!.source).toBe("soymutdb-browser");
  expect(init!.version).toBe(1);
  expect(init!.payload).toMatchObject({
    assembly: "Wm82.a4.v1",
    locus: "chr01:1000-2000",
    tracks: ["gene_models"],
  });

  // A locus change inside JBrowse is mirrored to the shareable URL and input.
  await frame.locator("body").evaluate(() =>
    (window as unknown as { __emitLocus: (locus: string) => void }).__emitLocus("chr02:500-900"),
  );
  await expect
    .poll(() => new URL(page.url()).searchParams.get("locus"), {
      message: "the portal must mirror the iframe locus into the URL",
    })
    .toBe("chr02:500-900");
  await expect(page.getByTestId("browser-locus-input")).toHaveValue("chr02:500-900");
});

test("a bridge error envelope renders the recoverable error state", async ({ page }) => {
  await stubJbrowseFrame(page);
  await gotoReady(page, "/browser?assembly=Wm82.a4.v1&locus=chr01:1000-2000&release=R7");

  const iframe = page.getByTestId("browser-iframe");
  const frame = page.frameLocator('[data-testid="browser-iframe"]');
  // Emit once the iframe is actually present (the harness boot is async).
  await expect
    .poll(async () => {
      try {
        return await frame.locator("body").evaluate(() => typeof window.__emitError);
      } catch {
        return "missing";
      }
    })
    .toBe("function");
  await frame.locator("body").evaluate(() =>
    (window as unknown as { __emitError: (message: string) => void }).__emitError(
      "assembly not found",
    ),
  );

  await expect(iframe).toHaveAttribute("data-bridge-status", "error");
  const errorState = page.getByTestId("browser-error");
  await expect(errorState).toBeVisible();
  await expect(errorState).toContainText("assembly not found");
  await expect(page.getByTestId("browser-open-new-tab-error")).toBeVisible();
});

test("a missing assembly renders the explicit no-context state instead of an iframe", async ({
  page,
}) => {
  await stubJbrowseFrame(page);
  await gotoReady(page, "/browser?locus=chr01:1-100");
  await expect(page.getByTestId("browser-missing-context")).toBeVisible();
  await expect(page.getByTestId("browser-iframe")).toHaveCount(0);
});
