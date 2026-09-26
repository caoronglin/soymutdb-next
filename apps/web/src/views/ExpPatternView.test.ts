// @vitest-environment jsdom
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@soymutdb/ui-vue", () => ({
  ConfigProvider: { template: "<div><slot /></div>" },
  createThemeConfig: () => ({}),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    getAssemblies: vi.fn(),
    runExpPattern: vi.fn(),
  };
});

import { getAssemblies, runExpPattern } from "@soymutdb/api-client";
import ExpPatternView from "./ExpPatternView.vue";

const mockedAssemblies = vi.mocked(getAssemblies);
const mockedRunExpPattern = vi.mocked(runExpPattern);

function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/tools/exppattern", component: ExpPatternView }],
  });
  router.push("/tools/exppattern");
  return mount(ExpPatternView, {
    // jsdom only dispatches `submit` for a form that is part of the document.
    attachTo: document.body,
    global: {
      plugins: [
        router,
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
      ],
    },
  });
}

const ASSEMBLIES = [
  { id: 4, name: "Wm82.v4", species: "Glycine max", version: "v4", is_default: false },
  { id: 5, name: "Wm82.v5", species: "Glycine max", version: "v5", is_default: true },
];

beforeEach(() => {
  mockedAssemblies.mockReset().mockResolvedValue(ASSEMBLIES);
  mockedRunExpPattern.mockReset().mockResolvedValue({
    assembly_id: 5,
    release_id: 7,
    assembly_name: "Wm82.v5",
    assembly_version: "v5",
    genes: ["G1"],
    conditions: ["leaf"],
    matrix: [[-1]],
    row_order: [0],
    clustering: "input",
    value_range: [-1, -1],
    missing_genes: [],
    scale: "zscore",
  });
});

describe("ExpPatternView", () => {
  it("submits deduplicated genes with the selected assembly and labels the result", async () => {
    const wrapper = mountView();
    await flushPromises();
    await wrapper.get('[data-testid="exppattern-genes"]').setValue("G1, G1\nG2");
    await wrapper.get('[data-testid="exppattern-submit"]').trigger("click");
    await flushPromises();

    expect(mockedRunExpPattern).toHaveBeenCalledWith({
      assembly_id: 5,
      genes: ["G1", "G2"],
      cluster_rows: false,
      scale: "zscore",
    });
    expect(wrapper.get('[data-testid="exppattern-summary"]').text()).toContain(
      "Wm82.v5 · v5 · Release 7",
    );
    wrapper.unmount();
  });

  it("rejects an empty gene list before making a request", async () => {
    const wrapper = mountView();
    await flushPromises();
    await wrapper.get('[data-testid="exppattern-submit"]').trigger("click");

    expect(mockedRunExpPattern).not.toHaveBeenCalled();
    expect(wrapper.get('[role="alert"]').text()).toContain("at least one gene");
    wrapper.unmount();
  });

  it("renders clustered rows in the server-provided order", async () => {
    mockedRunExpPattern.mockResolvedValueOnce({
      assembly_id: 5,
      release_id: 7,
      assembly_name: "Wm82.v5",
      assembly_version: "v5",
      genes: ["G1", "G2"],
      conditions: ["leaf"],
      matrix: [[-1], [1]],
      row_order: [1, 0],
      clustering: "hierarchical",
      value_range: [-1, 1],
      missing_genes: [],
      scale: "zscore",
    });
    const wrapper = mountView();
    await flushPromises();
    await wrapper.get('[data-testid="exppattern-genes"]').setValue("G1, G2");
    await wrapper.get('[data-testid="exppattern-submit"]').trigger("click");
    await flushPromises();

    expect(wrapper.findAll('tbody th[scope="row"]').map((row) => row.text())).toEqual(["G2", "G1"]);
    wrapper.unmount();
  });
});
