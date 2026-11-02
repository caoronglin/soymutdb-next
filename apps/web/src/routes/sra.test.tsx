// @vitest-environment jsdom
import * as React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import enCommon from "@soymutdb/i18n-core/locales/en/common.json";
import zhCommon from "@soymutdb/i18n-core/locales/zh/common.json";

const runtime = vi.hoisted(() => ({
  language: "en",
  search: { run: "SRR30334525" },
  navigate: vi.fn(),
  runQuery: {} as Record<string, unknown>,
  samplesQuery: {} as Record<string, unknown>,
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

function makeSamples(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    Run: `SRR${String(index + 1).padStart(8, "0")}`,
    LibraryStrategy: "RNA-Seq",
    release_date_short: "2025-01-01",
    bases: "1000",
  }));
}

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({
    ...options,
    options,
    useSearch: () => runtime.search,
    useNavigate: () => runtime.navigate,
  }),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: { queryKey: unknown[] }) =>
    options.queryKey[0] === "sra-run" ? runtime.runQuery : runtime.samplesQuery,
}));

vi.mock("@soymutdb/api-client", () => ({
  fetchSraRun: vi.fn(),
  fetchSraSamples: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  // `t` must keep a stable identity across renders: pass the module-level
  // resolver straight through instead of wrapping it in a fresh closure.
  useTranslation: () => ({ t: resolveKey }),
}));

// The restored `sra_run` widget fetches /api/v1/widget/sra_run on mount. These
// tests exercise the rest of the route, so without a stub each one would open a
// real socket to localhost and depend on nothing listening there. The widget has
// its own tests; here it just has to fail fast and quietly into its error state.
beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve(new Response("", { status: 503, statusText: "Service Unavailable" })),
  ));
});

vi.mock("../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
  useReveal: () => undefined,
}));

vi.mock("../lib/view-transitions", () => ({
  startViewTransition: (callback: () => void) => callback(),
}));

import { Route } from "./sra";

type RouteOptions = { component: React.ComponentType };
const SraPage = (Route as unknown as { options: RouteOptions }).options.component;

afterEach(() => cleanup());

beforeEach(() => {
  runtime.language = "zh";
  runtime.search = { run: "SRR30334525" };
  runtime.runQuery = {
    data: {
      run: {
        Run: "SRR30334525",
        bases: "1000",
        spots: "25",
        size_MB: "10",
        avgLength: "150",
        sra_url: "https://www.ncbi.nlm.nih.gov/sra/SRR30334525",
        ScientificName: "Glycine max",
        Experiment: "SRX00000001",
        BioProject: "PRJNA000001",
        BioSample: "SAMN00000001",
        Sample: "SRS00000001",
        Platform: "ILLUMINA",
        Model: "NovaSeq",
        LibraryStrategy: "RNA-Seq",
        LibrarySource: "TRANSCRIPTOMIC",
        LibrarySelection: "cDNA",
        LibraryLayout: "PAIRED",
        CenterName: "SOYMUTDB",
        release_date_short: "2025-01-01",
        TaxID: "3847",
        download_path: "https://example.test/run-data",
      },
      source: "fallback",
      cached: true,
    },
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  };
  runtime.samplesQuery = {
    data: { samples: makeSamples(3) },
    isError: false,
    isLoading: false,
  };
  runtime.resources = { en: enCommon, zh: zhCommon };
  runtime.navigate.mockClear();
  window.localStorage.clear();
  document.title = "";
});

describe("SRA run browser", () => {
  it("localizes metadata and presents short curated lists without a nested scroller", () => {
    render(<SraPage />);

    expect(screen.getByRole("heading", { level: 1, name: "SRA 运行元数据浏览器" })).toBeTruthy();
    expect(document.title).toBe("SRA 运行元数据浏览器 — SoyMutDB");
    expect(screen.getByRole("button", { name: "加载运行记录" })).toBeTruthy();
    expect(screen.getByText("碱基数")).toBeTruthy();
    expect(screen.getByText("生物项目（BioProject）")).toBeTruthy();
    expect(screen.getByText("已缓存")).toBeTruthy();
    expect(screen.getByRole("link", { name: "在 NCBI 中打开" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "从 NCBI 下载数据" })).toBeTruthy();

    const list = screen.getByTestId("curated-sra-runs-list");
    expect(list.className).not.toMatch(/max-h-|overflow-y-auto/);
    expect(screen.getByText("3 条运行记录")).toBeTruthy();
    expect(screen.queryByText("滚动查看全部运行记录")).toBeNull();
    expect(list.querySelector("button")?.className).toMatch(/text-sm/);
  });

  it("shows the item count and scroll cue only when the curated list is long", () => {
    runtime.runQuery = { data: undefined, isError: false, isFetching: false, isLoading: false, refetch: vi.fn() };
    runtime.samplesQuery = { data: { samples: makeSamples(8) }, isError: false, isLoading: false };
    render(<SraPage />);

    const list = screen.getByTestId("curated-sra-runs-list");
    expect(list.className).toMatch(/max-h-80.*overflow-y-auto/);
    expect(screen.getByText("8 条运行记录")).toBeTruthy();
    expect(screen.getByText("滚动查看全部运行记录")).toBeTruthy();
  });
});
