/**
 * A1 regression: the selective G2 Runtime must be able to resolve the theme
 * G2 asks for by default.
 *
 * Root cause this pins: in `@antv/g2` 5.4.8 `inferTheme()` defaults the theme
 * `type` to `'light'` (`esm/runtime/plot.js`), and `useLibrary('theme', lib)`
 * resolves it as `lib['theme.light']`, throwing `Unknown Component: theme.light`
 * when the selective library only registered `theme.classic`. In a real browser
 * that made all six probe samples fail and paint nothing.
 *
 * `jsdom` cannot rasterise, so nothing here claims "the chart drew pixels".
 * What is asserted is the resolution path that used to throw.
 */

import { useLibrary } from "@antv/g2/esm/runtime/library";
import { describe, expect, it } from "vitest";
import { library } from "./a1-runtime";

describe("A1 selective G2 Runtime theme resolution", () => {
  it("resolves the default light theme, the key G2 5.4.8 asks for", () => {
    const [, create] = useLibrary("theme", library);

    // This is the exact lookup that threw `Unknown Component: theme.light`.
    const theme = create("light" as never);

    expect(theme).toBeTypeOf("function");
    expect(create).not.toThrow();
    expect((theme as (options?: unknown) => Record<string, unknown>)({})).toBeTypeOf("object");
  });

  it("keeps the pre-existing classic registration working", () => {
    const [, create] = useLibrary("theme", library);
    expect(create("classic" as never)).toBeTypeOf("function");
  });

  it("registers the same light theme G2 itself ships", async () => {
    const { Light } = await import("@antv/g2/esm/theme/index");
    const [, create] = useLibrary("theme", library);
    expect(create("light" as never)).toBe(Light);
  });
});
