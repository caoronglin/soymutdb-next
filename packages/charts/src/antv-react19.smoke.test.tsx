/**
 * A1 feasibility smoke for the `@ant-design/plots` engine under React 19.
 *
 * Coverage is deliberately split, because this host cannot draw pixels:
 * `jsdom` ships no canvas backend, so `HTMLCanvasElement.getContext("2d")`
 * returns `null` and G2's `@antv/g-canvas` renderer throws when it initialises.
 * Claiming "the chart rendered" from this environment would be a mock reporting
 * on itself.
 *
 *   - "engine import"   -> the real module graph evaluates under React 19.
 *   - "component shape" -> the plan's chart names are real React component
 *                          types (they are `memo()` objects, not functions).
 *   - "lazy boundary"   -> the approved `React.lazy` + `<Suspense>` mechanism
 *                          resolves the engine module under React 19.
 *   - "canvas failure"  -> the real engine is exercised and the observed failure
 *                          is pinned to the absent canvas context, which proves
 *                          it is environmental and not a React 19 break.
 *   - NOT covered      -> actual drawing, resize, dispose, theming, animation.
 */

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

const DATA = [
  { category: "missense", value: 4 },
  { category: "frameshift", value: 2 },
  { category: "synonymous", value: 1 },
];

let roots: Array<{ root: Root; host: HTMLDivElement }> = [];

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

afterEach(async () => {
  await act(async () => {
    for (const { root, host } of roots) {
      root.unmount();
      host.remove();
    }
  });
  roots = [];
});

describe("@ant-design/plots under React 19 (A1 feasibility)", () => {
  it("runs the exact React runtime the catalog pins", async () => {
    expect((await import("react")).version).toBe("19.3.1");
    expect((await import("react-dom")).version).toBe("19.3.1");
  });

  it("imports the chart components the migration plan names", async () => {
    const plots = await import("@ant-design/plots");
    // React 19 element types are the symbol-tagged `memo`/`forwardRef` objects
    // the engine ships, so identity is asserted structurally rather than with
    // `typeof === "function"`, which would be the wrong contract.
    for (const name of ["Column", "Line", "Area", "Heatmap"] as const) {
      const component = plots[name] as unknown as { $$typeof?: symbol; render?: unknown };
      expect(typeof component).toBe("object");
      expect(typeof component.$$typeof).toBe("symbol");
      expect(component.render).toBeDefined();
      expect(React.isValidElement(React.createElement(component as never))).toBe(true);
    }
  });

  it("resolves the engine through the approved React.lazy + Suspense boundary", async () => {
    // The gate is held closed so the Suspense fallback is observed
    // deterministically. Asserting a fallback without controlling resolution
    // timing is a race: once the module is cached the fallback never paints.
    let releaseGate!: () => void;
    const gate = new Promise<void>((resolve) => {
      releaseGate = resolve;
    });
    const LazyColumn = React.lazy(async () => {
      await gate;
      const plots = await import("@ant-design/plots");
      return { default: plots.Column };
    });

    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    roots.push({ root, host });
    const caught: Array<Error> = [];

    class EngineBoundary extends React.Component<{ children: React.ReactNode }> {
      override state = { failed: false };
      static getDerivedStateFromError() {
        return { failed: true };
      }
      override componentDidCatch(error: Error) {
        caught.push(error);
      }
      override render() {
        return this.state.failed ? null : this.props.children;
      }
    }

    // The fallback must render first: this is the loading affordance the
    // approved plan relies on, and it is observable without a canvas.
    await act(async () => {
      root.render(
        React.createElement(
          EngineBoundary,
          null,
          React.createElement(
            React.Suspense,
            { fallback: React.createElement("div", { "data-testid": "chart-loading" }, "Loading chart…") },
            React.createElement(LazyColumn, {
              data: DATA,
              xField: "category",
              yField: "value",
            }),
          ),
        ),
      );
    });
    expect(host.querySelector('[data-testid="chart-loading"]')).not.toBeNull();

    // The boundary tripping is the positive proof that the lazy import resolved
    // and React 19 actually rendered the engine component — the failure it
    // reports is this environment's missing canvas backend, not a lazy or
    // React 19 defect.
    await act(async () => {
      releaseGate();
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(caught).toHaveLength(1);
    expect(caught[0]!.message).toMatch(/clearRect|getContext|canvas/i);
  });

  it("pins the engine's real failure to the absent canvas context, not React 19", async () => {
    const { Column } = await import("@ant-design/plots");
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    roots.push({ root, host });

    let renderError: unknown = null;
    try {
      await act(async () => {
        root.render(
          React.createElement(Column as never, {
            data: DATA,
            xField: "category",
            yField: "value",
            height: 280,
            autoFit: false,
          }),
        );
        await new Promise((resolve) => setTimeout(resolve, 50));
      });
    } catch (error) {
      renderError = error;
    }

    // The engine was really executed: it reached `@antv/g-canvas`, which needs
    // a 2d context this environment cannot provide. If React 19 were the
    // breakage, the error would come from react-dom instead.
    expect(renderError).toBeInstanceOf(Error);
    const message = (renderError as Error).message;
    const tracesToCanvas = /clearRect|getContext|canvas/i.test(message);
    const tracesToReact = /react-dom|ReactDOM|is not a function element type/i.test(message);
    expect(tracesToReact).toBe(false);
    expect(tracesToCanvas).toBe(true);
  });

  it("states the uncovered boundary: jsdom cannot rasterise", async () => {
    const host = document.createElement("div");
    document.body.append(host);
    const canvas = host.appendChild(document.createElement("canvas"));
    // Asserted, not assumed. This single fact is why every drawing claim in
    // this file is scoped to lifecycle and import only.
    expect(canvas.getContext("2d")).toBeNull();
  });
});