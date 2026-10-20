import * as React from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// This app's vitest config does not load src/test/setup.ts, and antd's
// responsive observer calls matchMedia when ProCard mounts. Install the two
// browser APIs jsdom lacks, in the same shape setup.ts does, so the real
// ProCard and Empty are exercised rather than doubled.
if (!window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}

if (!globalThis.ResizeObserver) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

import { ImportThroughputChart } from "./import-throughput";
import { QueryLatencyChart } from "./query-latency";
import { StorageGrowthChart } from "./storage-growth";

/**
 * The facade is doubled, the charts are not.
 *
 * jsdom ships no canvas backend, so the real engine cannot rasterise here and
 * these tests deliberately do not claim that anything was drawn. They drive
 * the seam this migration owns: which rows reach the facade, which definition
 * describes them, what the tooltip prints, and that the empty state, the theme
 * attribute and the motion preference each still reach the chart. The double
 * reproduces ChartCanvas's own rendered contract (role, aria-label,
 * data-testid, data-status) so the accessibility surface is asserted as the
 * facade really renders it.
 */
const facade = vi.hoisted(() => ({ calls: [] as Array<Record<string, unknown>> }));

vi.mock("@soymutdb/charts", async () => {
  const react = await import("react");
  return {
    ChartCanvas: (props: Record<string, unknown>) => {
      facade.calls.push(props);
      return react.createElement(
        "div",
        {
          role: "img",
          "aria-label": String(props.label),
          "data-testid": "chart-canvas",
          "data-status": "rendered",
        },
        null,
      );
    },
  };
});

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);

// The console's motion preference reads matchMedia, which this app's vitest
// setup does not provide, so the policy itself is asserted elsewhere. Here it
// is a stable input the double can read back.
vi.mock("../../lib/motion-preference", () => ({
  useAdminMotion: () => ({ preference: "auto", effective: "off" }),
}));

type FacadeCall = Record<string, unknown>;

function lastCall(): FacadeCall {
  const call = facade.calls[facade.calls.length - 1];
  if (!call) throw new Error("the chart never reached the facade");
  return call;
}

beforeEach(() => {
  facade.calls.length = 0;
  document.documentElement.setAttribute("data-theme", "light");
});

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-theme");
});

describe("ImportThroughputChart", () => {
  const data = [
    { date: "2026-01-01", imported: 10, failed: 1 },
    { date: "2026-01-02", imported: 20, failed: 2 },
  ];

  it("reshapes the wide rows into one row per series", () => {
    render(<ImportThroughputChart data={data} />);

    expect(lastCall().data).toEqual([
      { date: "2026-01-01", series: "Imported", value: 10 },
      { date: "2026-01-01", series: "Failed", value: 1 },
      { date: "2026-01-02", series: "Imported", value: 20 },
      { date: "2026-01-02", series: "Failed", value: 2 },
    ]);
  });

  it("declares both series, the records axis and the colors it always used", () => {
    render(<ImportThroughputChart data={data} />);

    const definition = lastCall().definition as Record<string, unknown>;
    expect(definition.kind).toBe("area");
    expect(definition.color).toBe("series");
    expect(definition.legend).toBe(true);
    expect(definition.palette).toEqual(["#2f7d32", "#c0392b"]);
    expect(definition.axisLabels).toEqual({ y: "Records" });
  });

  it("keeps the accessible name and the drawing height", () => {
    render(<ImportThroughputChart data={data} />);

    expect(lastCall().label).toBe("Import throughput chart");
    expect(lastCall().height).toBe(256);
    expect(screen.getByRole("img", { name: "Import throughput chart" })).toBeTruthy();
  });

  it("swaps between the empty state and the chart as data arrives", () => {
    const view = render(<ImportThroughputChart data={[]} />);
    expect(screen.getByText("No chart data")).toBeTruthy();
    expect(screen.queryByTestId("chart-canvas")).toBeNull();
    expect(facade.calls).toHaveLength(0);

    view.rerender(<ImportThroughputChart data={data} />);
    expect(screen.queryByText("No chart data")).toBeNull();
    expect(screen.getByTestId("chart-canvas")).toBeTruthy();

    view.rerender(<ImportThroughputChart data={[]} />);
    expect(screen.getByText("No chart data")).toBeTruthy();
    expect(screen.queryByTestId("chart-canvas")).toBeNull();
  });

  it("forwards the console motion policy instead of animating by default", () => {
    render(<ImportThroughputChart data={data} />);
    expect(lastCall().animation).toEqual({ intensity: "off" });
  });
});

describe("QueryLatencyChart", () => {
  const data = [
    { date: "2026-01-01", p50: 10, p95: 30, p99: 60 },
    { date: "2026-01-02", p50: 11, p95: 31, p99: 61 },
  ];

  it("keeps the P50/P95/P99 legend labels", () => {
    render(<QueryLatencyChart data={data} />);

    expect(lastCall().data).toEqual([
      { date: "2026-01-01", series: "P50", value: 10 },
      { date: "2026-01-01", series: "P95", value: 30 },
      { date: "2026-01-01", series: "P99", value: 60 },
      { date: "2026-01-02", series: "P50", value: 11 },
      { date: "2026-01-02", series: "P95", value: 31 },
      { date: "2026-01-02", series: "P99", value: 61 },
    ]);

    const definition = lastCall().definition as Record<string, unknown>;
    expect(definition.kind).toBe("line");
    expect(definition.axisLabels).toEqual({ y: "Latency (ms)" });
    expect(definition.palette).toEqual(["#2f7d32", "#e6a817", "#c0392b"]);
  });

  it("prints every percentile of the hovered date in milliseconds", () => {
    render(<QueryLatencyChart data={data} />);

    const formatter = lastCall().tooltipFormatter as (context: {
      datum: Record<string, unknown>;
    }) => string;

    expect(formatter({ datum: { date: "2026-01-01" } })).toBe(
      "2026-01-01 — P50 10 ms · P95 30 ms · P99 60 ms",
    );
  });

  it("shows the empty state until data arrives", () => {
    render(<QueryLatencyChart data={[]} />);
    expect(screen.getByText("No chart data")).toBeTruthy();
    expect(facade.calls).toHaveLength(0);
  });
});

describe("StorageGrowthChart", () => {
  const data = [
    { date: "2026-01-01", bytes: 1024 },
    { date: "2026-01-02", bytes: 1073741824 },
  ];

  it("passes the byte values through unchanged", () => {
    render(<StorageGrowthChart data={data} />);

    expect(lastCall().data).toEqual([
      { date: "2026-01-01", value: 1024 },
      { date: "2026-01-02", value: 1073741824 },
    ]);
  });

  it("formats the tooltip with the console's own file-size formatter", () => {
    render(<StorageGrowthChart data={data} />);

    const formatter = lastCall().tooltipFormatter as (context: {
      datum: Record<string, unknown>;
    }) => string;

    expect(formatter({ datum: { value: 1024 } })).toBe("1.0 KB");
    expect(formatter({ datum: { value: 1073741824 } })).toBe("1.0 GB");
  });

  it("does not claim a value format the console does not use", () => {
    render(<StorageGrowthChart data={data} />);

    // The facade's "bytes" token prints KiB/MiB/GiB. Until it carries an axis
    // formatter, leaving valueFormat unset keeps the mismatch visible here
    // instead of shipping a different unit on the axis.
    const definition = lastCall().definition as Record<string, unknown>;
    expect(definition.valueFormat).toBeUndefined();
    expect(definition.legend).toBe(false);
    expect(definition.palette).toEqual(["#4e9b4a"]);
  });

  it("shows the empty state until data arrives", () => {
    render(<StorageGrowthChart data={[]} />);
    expect(screen.getByText("No chart data")).toBeTruthy();
    expect(facade.calls).toHaveLength(0);
  });
});

describe("theme lifecycle", () => {
  const data = [{ date: "2026-01-01", imported: 1, failed: 0 }];

  it("re-resolves the theme when the console flips data-theme", async () => {
    render(<ImportThroughputChart data={data} />);
    expect(lastCall().theme).toEqual({
      mode: "light",
      palette: ["#2f7d32", "#c0392b"],
    });

    await act(async () => {
      document.documentElement.setAttribute("data-theme", "dark");
    });

    expect(lastCall().theme).toEqual({
      mode: "dark",
      palette: ["#2f7d32", "#c0392b"],
    });
  });

  it("keeps the chart mounted across a theme flip", async () => {
    render(<StorageGrowthChart data={[{ date: "2026-01-01", bytes: 10 }]} />);
    expect(screen.getByTestId("chart-canvas")).toBeTruthy();

    await act(async () => {
      document.documentElement.setAttribute("data-theme", "dark");
    });

    expect(screen.getByTestId("chart-canvas")).toBeTruthy();
  });
});

