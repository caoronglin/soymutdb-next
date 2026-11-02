// @vitest-environment jsdom
/**
 * SoyMutDbWidget tests.
 *
 * The security-relevant assertion is the negative one: a widget fragment is HTML
 * from the API (rendered by a Jinja2 template from third-party NCBI runinfo data),
 * so the component must hand it to the DOM only after DOMPurify has stripped
 * executable markup. Everything else here covers the two ways this component can
 * otherwise lie to the reader: rendering an empty box under a heading that promises
 * content, and requesting the wrong endpoint or parameter encoding.
 */
import * as React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import enCommon from "@soymutdb/i18n-core/locales/en/common.json";
import zhCommon from "@soymutdb/i18n-core/locales/zh/common.json";

const resources: Record<string, Record<string, unknown>> = { en: enCommon, zh: zhCommon };

/** Minimal key resolver backed by the real catalogs, so a missing key fails the test. */
function resolveKey(key: string, options?: Record<string, unknown>) {
  let value: unknown = resources.en;
  for (const part of key.split(".")) {
    value = value && typeof value === "object" ? (value as Record<string, unknown>)[part] : undefined;
  }
  if (typeof value !== "string") return key;
  return value.replace(/\{\{(\w+)\}\}/g, (_match, name: string) => String(options?.[name] ?? ""));
}

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: resolveKey }),
}));

// Only `apiBaseUrl` is used by the component; stubbing the rest keeps this suite
// from loading the whole transport while still exercising the real URL building.
vi.mock("@soymutdb/api-client", () => ({ apiBaseUrl: "/api/v1" }));

import { SoyMutDbWidget } from "./soymutdb-widget";

const fetchMock = vi.fn();

function respondWith(body: string) {
  fetchMock.mockResolvedValueOnce({
    ok: true,
    status: 200,
    statusText: "OK",
    text: () => Promise.resolve(body),
  });
}

function respondWithStatus(status: number, statusText: string) {
  fetchMock.mockResolvedValueOnce({ ok: false, status, statusText, text: () => Promise.resolve("") });
}

/** Global the injected payloads would touch if they ever executed. */
function xssSentinel() {
  return (globalThis as unknown as { __widgetXss?: number }).__widgetXss;
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  delete (globalThis as unknown as { __widgetXss?: number }).__widgetXss;
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SoyMutDbWidget", () => {
  it("renders the sanitized fragment returned by the API", async () => {
    respondWith(
      '<div class="widget widget-sra-run" data-widget="sra_run">' +
        '<h3 class="widget-sra-run__title"><a href="https://trace.ncbi.nlm.nih.gov/Traces/sra?run=SRR30334525" target="_blank" rel="noopener noreferrer">SRR30334525</a></h3>' +
        '<span class="widget-sra-run__org">Glycine max</span>' +
        "</div>",
    );

    render(<SoyMutDbWidget name="sra_run" params={{ run: "SRR30334525" }} />);

    const content = await screen.findByTestId("soymutdb-widget-content");
    expect(content.querySelector("[data-widget='sra_run']")).toBeTruthy();
    expect(content.querySelector("h3")?.textContent).toBe("SRR30334525");
    expect(content.textContent).toContain("Glycine max");
    expect(content.querySelector("a")?.getAttribute("href")).toContain("trace.ncbi.nlm.nih.gov");
    expect(screen.queryByTestId("soymutdb-widget-error")).toBeNull();
  });

  it("strips executable markup instead of injecting it", async () => {
    respondWith(
      '<div class="widget widget-sra-run">' +
        "<p>keep this text</p>" +
        "<script>window.__widgetXss = (window.__widgetXss || 0) + 1;</scr" + "ipt>" +
        '<img src="x" onerror="window.__widgetXss = (window.__widgetXss || 0) + 1">' +
        '<a href="javascript:window.__widgetXss=(window.__widgetXss||0)+1">click</a>' +
        "</div>",
    );

    render(<SoyMutDbWidget name="sra_run" params={{ run: "SRR30334525" }} />);

    const content = await screen.findByTestId("soymutdb-widget-content");

    // No live markup survives: no script element, no event handler, no javascript: URL.
    expect(content.querySelector("script")).toBeNull();
    expect(content.innerHTML).not.toContain("onerror");
    expect(content.innerHTML).not.toContain("javascript:");
    expect(content.querySelector('a[href^="javascript:"]')).toBeNull();

    // Nothing executed. jsdom never runs innerHTML scripts or img error handlers on
    // its own, so the DOM-shape assertions above are the real guard; this proves
    // the payload also never reached a handler.
    expect(xssSentinel()).toBeUndefined();

    // Sanitization is not a blanket drop: inert content is preserved.
    expect(content.textContent).toContain("keep this text");
    expect(content.textContent).toContain("click");
  });

  it("shows an error when the request fails instead of rendering a blank", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    render(<SoyMutDbWidget name="sra_run" params={{ run: "SRR30334525" }} />);

    const error = await screen.findByTestId("soymutdb-widget-error");
    expect(error.textContent).toContain("Error");
    expect(error.textContent).toContain("Failed to fetch");
    expect(error.textContent).toContain("Retry");
    expect(screen.queryByTestId("soymutdb-widget-content")).toBeNull();
  });

  it("treats a non-OK widget response as a failure and keeps its body out of the DOM", async () => {
    respondWithStatus(404, "Not Found");

    render(<SoyMutDbWidget name="sra_run" params={{ run: "SRR30334525" }} />);

    const error = await screen.findByTestId("soymutdb-widget-error");
    expect(error.textContent).toContain("HTTP 404");
    expect(error.textContent).not.toContain("Widget error");
    expect(screen.queryByTestId("soymutdb-widget-content")).toBeNull();
  });

  it("treats an empty fragment as a failure rather than a silent blank", async () => {
    respondWith("   ");

    render(<SoyMutDbWidget name="sra_run" params={{ run: "SRR30334525" }} />);

    const error = await screen.findByTestId("soymutdb-widget-error");
    expect(error.textContent).toContain("No data available");
    expect(screen.queryByTestId("soymutdb-widget-content")).toBeNull();
  });

  it("requests /api/v1/widget/sra_run with the JSON-encoded params", async () => {
    respondWith("<div class=\"widget widget-sra-run\">ok</div>");

    render(<SoyMutDbWidget name="sra_run" params={{ run: "SRR30334525" }} />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [rawUrl, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const url = new URL(rawUrl);

    expect(url.pathname).toBe("/api/v1/widget/sra_run");
    expect(url.searchParams.get("params")).toBe('{"run":"SRR30334525"}');
    expect(JSON.parse(url.searchParams.get("params") as string)).toEqual({ run: "SRR30334525" });
    expect((init.headers as Record<string, string>).Accept).toBe("text/html");

    await screen.findByTestId("soymutdb-widget-content");
  });

  it("refetches only when the parameters change, and aborts on unmount", async () => {
    respondWith("<div class=\"widget\">one</div>");
    const { rerender, unmount } = render(<SoyMutDbWidget name="sra_run" params={{ run: "SRR30334525" }} />);
    await screen.findByTestId("soymutdb-widget-content");

    // A fresh object literal with identical content must not restart the fetch.
    respondWith("<div class=\"widget\">two</div>");
    rerender(<SoyMutDbWidget name="sra_run" params={{ run: "SRR30334525" }} />);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    respondWith("<div class=\"widget\">three</div>");
    rerender(<SoyMutDbWidget name="sra_run" params={{ run: "SRR30334526" }} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(new URL(fetchMock.mock.calls[1][0] as string).searchParams.get("params")).toBe('{"run":"SRR30334526"}');

    const signal = (fetchMock.mock.calls[1][1] as RequestInit).signal;
    expect(signal?.aborted).toBe(false);
    unmount();
    expect(signal?.aborted).toBe(true);
  });
});