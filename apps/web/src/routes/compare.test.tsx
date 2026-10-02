// @vitest-environment jsdom
import * as React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import enCommon from "@soymutdb/i18n-core/locales/en/common.json";
import zhCommon from "@soymutdb/i18n-core/locales/zh/common.json";

const runtime = vi.hoisted(() => ({
  language: "en",
  search: { ids: "" },
  navigate: vi.fn(),
  resources: {} as Record<string, Record<string, unknown>>,
}));

function resolveKey(key: string, options?: Record<string, unknown>) {
  let value: unknown = runtime.resources[runtime.language];
  for (const part of key.split(".")) {
    value = value && typeof value === "object" ? (value as Record<string, unknown>)[part] : undefined;
  }
  if (typeof value !== "string") return key;
  return value.replace(/\{\{(\w+)\}\}/g, (_match, name: string) => String(options?.[name] ?? ""));
}

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({
    ...options,
    options,
    useSearch: () => runtime.search,
    useNavigate: () => runtime.navigate,
  }),
}));

vi.mock("react-i18next", () => ({
  // `t` must keep a stable identity across renders: pass the module-level
  // resolver straight through instead of wrapping it in a fresh closure.
  useTranslation: () => ({ t: resolveKey }),
}));

vi.mock("../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
  useReveal: () => undefined,
}));

vi.mock("../lib/view-transitions", () => ({
  startViewTransition: (callback: () => void) => callback(),
}));

import { COMPARE_VARIANTS } from "../lib/compare-data";
import { Route } from "./compare";

type RouteOptions = { component: React.ComponentType };
const ComparePage = (Route as unknown as { options: RouteOptions }).options.component;

afterEach(() => cleanup());

beforeEach(() => {
  runtime.language = "en";
  runtime.search = { ids: "" };
  runtime.resources = { en: enCommon, zh: zhCommon };
  runtime.navigate.mockClear();
  document.title = "";
});

describe("curated variant comparison", () => {
  it("renders every selector option in normal page flow without a capped nested scroller", () => {
    render(<ComparePage />);

    const picker = screen.getByTestId("compare-picker");
    expect(picker.querySelectorAll('input[type="checkbox"]')).toHaveLength(COMPARE_VARIANTS.length);
    expect(picker.className).not.toMatch(/max-h-|overflow-y-auto|sticky/);
    for (const variant of COMPARE_VARIANTS) {
      expect(screen.getByRole("checkbox", { name: `Select ${variant.id}` })).toBeTruthy();
    }
  });

  it("keeps the four-variant selection limit and synchronizes selected IDs to the URL", () => {
    runtime.search = { ids: "SMDB-00001,SMDB-00002" };
    render(<ComparePage />);

    fireEvent.click(screen.getByRole("checkbox", { name: "Select SMDB-00003" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select SMDB-00004" }));
    expect(screen.getByRole("checkbox", { name: "Select SMDB-00005" })).toHaveProperty("disabled", true);
    expect(runtime.navigate).toHaveBeenLastCalledWith({
      search: { ids: "SMDB-00001,SMDB-00002,SMDB-00003,SMDB-00004" },
      replace: true,
    });
  });

  it("renders localized copy and localized curated descriptions in Chinese", () => {
    runtime.language = "zh";
    render(<ComparePage />);

    expect(screen.getByRole("heading", { level: 1, name: "大豆突变体变异对比" })).toBeTruthy();
    expect(screen.getByText("开花提前，株高降低")).toBeTruthy();
    expect(document.title).toBe("变异对比 — SoyMutDB");
  });

  it("localizes the empty state when fewer than two variants are selected", () => {
    runtime.search = { ids: "SMDB-00001" };
    runtime.language = "zh";
    render(<ComparePage />);

    expect(screen.getByText("至少选择 2 个变异")).toBeTruthy();
    expect(screen.getByText("从上方网格选择变异以开始对比。")).toBeTruthy();
  });
});
