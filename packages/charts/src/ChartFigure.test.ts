import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChartFigure, categoryBarChart, trendAreaChart } from "./index";
import type { ChartDefinition } from "./definitions";
import { shouldAnimate } from "./ChartCanvas";

/**
 * jsdom ships no canvas backend, so the real engine cannot rasterise here.
 * These tests drive ChartCanvas against a fake engine module and assert the
 * lifecycle and the degradation contract around it. They do NOT claim that a
 * chart drew pixels; real rendering is a separate gate.
 */
const engine = vi.hoisted(() => ({
  create: vi.fn(),
  destroy: vi.fn(),
  render: vi.fn(),
  resize: vi.fn(),
  options: vi.fn(),
  failOnCreate: false,
  calls: [] as string[],
}));

vi.mock("./g2-runtime", async () => {
  const actual = await vi.importActual<typeof import("./g2-runtime")>("./g2-runtime");
  return {
    ...actual,
    createChart: (
      _container: HTMLElement,
      _width: number,
      _height: number,
      options: Record<string, unknown>,
    ) => {
      engine.calls.push("create");
      if (engine.failOnCreate) throw new Error("mock chart renderer failure");
      engine.create(options);
      return {
        options: (next: Record<string, unknown>) => engine.options(next),
        render: () => {
          engine.calls.push("render");
          return engine.render();
        },
        resize: (width?: number, height?: number) => engine.resize(width, height),
        destroy: () => {
          engine.calls.push("destroy");
          return engine.destroy();
        },
      };
    },
  };
});

interface TestDatum {
  category: string;
  value: number;
  series?: string;
}

type FigureProps = React.ComponentProps<typeof ChartFigure<TestDatum>>;

let roots: Array<{ root: Root; host: HTMLDivElement }> = [];
let resizeCallbacks: Array<() => void> = [];
const originalResizeObserver = globalThis.ResizeObserver;

/**
 * The first test that touches the engine pays a cold module-graph transform
 * that is far slower than the default wait, so every engine wait is widened.
 */
const WAIT = { timeout: 30_000, interval: 25 } as const;

/** Render into a root created here, so the test can drive updates and unmount. */
async function mount(element: React.ReactElement) {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  roots.push({ root, host });
  await act(async () => {
    root.render(element);
    await settle();
  });
  return { host, root };
}

/** Flush microtasks so the lazy engine import and render promise complete. */
async function settle() {
  await vi.dynamicImportSettled();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function figure(overrides: Partial<FigureProps> = {}) {
  const data: TestDatum[] = [{ category: "missense", value: 4 }];
  return React.createElement(ChartFigure<TestDatum>, {
    definition: categoryBarChart<TestDatum>(data),
    data,
    label: "Variant types",
    tableColumns: ["Type", "Count"],
    tableRow: (datum) => [datum.category, String(datum.value)],
    ...overrides,
  });
}

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  engine.create.mockClear();
  engine.destroy.mockClear();
  engine.render.mockClear();
  engine.resize.mockClear();
  engine.options.mockClear();
  engine.calls.length = 0;
  engine.failOnCreate = false;
  engine.render.mockResolvedValue(undefined);
  resizeCallbacks = [];

  globalThis.ResizeObserver = class {
    constructor(callback: () => void) {
      resizeCallbacks.push(callback);
    }
    observe() {}
    disconnect() {}
    unobserve() {}
  } as unknown as typeof ResizeObserver;
});

afterEach(async () => {
  await act(async () => {
    for (const { root, host } of roots) {
      root.unmount();
      host.remove();
    }
  });
  roots = [];
  globalThis.ResizeObserver = originalResizeObserver;
});

describe("chart definitions", () => {
  it("honors reduced motion even when a definition enables animation", () => {
    const definition = categoryBarChart<TestDatum>([]);
    expect(shouldAnimate({ ...definition, animate: true }, { reduced: true })).toBe(false);
    expect(shouldAnimate({ ...definition, animate: true }, { intensity: "off" })).toBe(false);
  });
  it("builds an interval chart over a category field", () => {
    const definition = categoryBarChart<TestDatum>([
      { category: "missense", value: 4 },
      { category: "frameshift", value: 2 },
    ]);
    expect(definition).toMatchObject({
      kind: "interval",
      x: "category",
      y: "value",
      categoryOrder: "appearance",
    });
    expect(definition.color).toBeUndefined();
  });

  it("groups bars by a named series field", () => {
    const definition = categoryBarChart<TestDatum>(
      [
        { category: "leaf", value: 3, series: "v4" },
        { category: "leaf", value: 5, series: "v5" },
      ],
      { seriesKey: "series" },
    );
    expect(definition).toMatchObject({ kind: "interval", color: "series", legend: true });
  });

  it("keeps a categorical x axis for trends, not a time scale", () => {
    const definition = trendAreaChart([{ date: "2026-09-26", value: 2 }]);
    expect(definition).toMatchObject({ kind: "area", x: "date", y: "value" });
    expect(definition.kind).not.toBe("polar");
  });

  it("stays serializable, so a definition survives a JSON round trip", () => {
    const definition = categoryBarChart<TestDatum>([{ category: "a", value: 1 }]);
    expect(JSON.parse(JSON.stringify(definition))).toEqual(definition);
  });
});

describe("ChartFigure accessibility and degradation contract", () => {
  it("updates new data with an unchanged definition without recreating the engine", async () => {
    const definition = categoryBarChart<TestDatum>([]);
    const { root } = await mount(figure({ definition }));
    await vi.waitFor(() => expect(engine.create).toHaveBeenCalledTimes(1), WAIT);
    await act(settle);
    const creates = engine.create.mock.calls.length;
    engine.options.mockClear();
    await act(async () => {
      root.render(figure({ definition, data: [{ category: "frameshift", value: 9 }] }));
      await settle();
    });
    expect(engine.create).toHaveBeenCalledTimes(creates);
    expect(engine.options).toHaveBeenCalledWith(expect.objectContaining({
      data: [{ category: "frameshift", value: 9 }],
    }));
  });
  it("shows an empty state instead of creating an empty chart", async () => {
    const { host } = await mount(figure({ definition: categoryBarChart<TestDatum>([]), data: [] }));

    expect(host.querySelector('[data-testid="chart-empty"]')?.textContent).toContain("No data");
    expect(host.querySelector('[data-testid="chart-values"]')).toBeNull();
    expect(engine.create).not.toHaveBeenCalled();
  });

  it("keeps role=img, aria-label and the exact-value table when the chart renders", async () => {
    const { host } = await mount(figure({ description: "Variant counts by consequence" }));

    const graphic = host.querySelector('[role="img"]');
    expect(graphic?.getAttribute("aria-label")).toBe("Variant types");
    expect(graphic?.textContent).toContain("Variant counts by consequence");
    expect(host.querySelector('[data-testid="chart-values"]')?.textContent).toContain("missense");
    expect(host.querySelector('[data-testid="chart-unavailable"]')).toBeNull();
  });

  it("degrades to the value table when the engine cannot be created", async () => {
    engine.failOnCreate = true;
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const { host } = await mount(figure({ description: "Variant counts by consequence" }));

    await vi.waitFor(() => {
      expect(host.querySelector('[data-testid="chart-unavailable"]')).not.toBeNull();
    }, WAIT);
    expect(host.querySelector('[data-testid="chart-unavailable"]')?.textContent).toContain(
      "could not be drawn",
    );
    // The fallback renders no role="img" wrapper, so the description stays
    // reachable as visually hidden text rather than via aria-describedby.
    expect(host.querySelector('[data-testid="chart-unavailable"]')?.textContent).toContain(
      "Variant counts by consequence",
    );
    expect(host.querySelector('[data-testid="chart-values"]')?.textContent).toContain("4");
    consoleError.mockRestore();
  });

  it("moves between empty and populated data without leaving a stale chart", async () => {
    const definition: ChartDefinition = categoryBarChart<TestDatum>([]);
    const { host, root } = await mount(figure({ definition, data: [] }));

    expect(host.querySelector('[data-testid="chart-empty"]')).not.toBeNull();
    expect(engine.create).not.toHaveBeenCalled();

    await act(async () => {
      root.render(figure({ definition, data: [{ category: "missense", value: 4 }] }));
      await settle();
    });
    await vi.waitFor(() => expect(engine.create).toHaveBeenCalledTimes(1), WAIT);
    expect(host.querySelector('[data-testid="chart-empty"]')).toBeNull();

    await act(async () => {
      root.render(figure({ definition, data: [] }));
      await settle();
    });
    expect(host.querySelector('[data-testid="chart-empty"]')).not.toBeNull();
    expect(engine.destroy).toHaveBeenCalled();
  });

  it("disposes the chart on unmount", async () => {
    const { root } = await mount(figure());
    await vi.waitFor(() => expect(engine.create).toHaveBeenCalledTimes(1), WAIT);
    expect(engine.create).toHaveBeenCalledTimes(1);

    await act(async () => {
      root.unmount();
    });
    expect(engine.destroy).toHaveBeenCalledTimes(1);
  });

  it("rebuilds on a theme change, because the engine holds the theme as plot state", async () => {
    const { root } = await mount(figure({ theme: { mode: "light" } }));
    await vi.waitFor(() => expect(engine.create).toHaveBeenCalledTimes(1), WAIT);
    expect(engine.create).toHaveBeenCalledTimes(1);

    await act(async () => {
      root.render(
        figure({ theme: { mode: "dark", palette: ["#111111", "#222222", "#333333"] } }),
      );
      await settle();
    });
    await vi.waitFor(() => expect(engine.create).toHaveBeenCalledTimes(2), WAIT);
    expect(engine.create).toHaveBeenCalledTimes(2);
    expect(engine.destroy).toHaveBeenCalledTimes(1);
  });

  it("does not rebuild when an equivalent theme object is passed again", async () => {
    const { root } = await mount(figure({ theme: { mode: "light" } }));
    await vi.waitFor(() => expect(engine.create).toHaveBeenCalledTimes(1), WAIT);
    await act(async () => {
      root.render(figure({ theme: { mode: "light" } }));
      await settle();
    });
    expect(engine.create).toHaveBeenCalledTimes(1);
  });

  it("resizes with the measured element", async () => {
    await mount(figure());
    await vi.waitFor(() => expect(engine.create).toHaveBeenCalledTimes(1), WAIT);
    expect(resizeCallbacks.length).toBeGreaterThan(0);

    await act(async () => {
      for (const callback of resizeCallbacks) callback();
    });
    expect(engine.resize).toHaveBeenCalled();
  });
});
