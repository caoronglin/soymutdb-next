// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { describe, expect, it, vi } from "vitest";

vi.mock("@soymutdb/ui-vue", () => ({
  ConfigProvider: { template: "<div><slot /></div>" },
  createThemeConfig: () => ({}),
}));

import ToolsView from "./ToolsView.vue";

describe("ToolsView", () => {
  it("links to the assembly-aware sequence fetch tool", async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/tools", component: ToolsView },
        { path: "/tools/seqfetch", component: { template: "<div>SeqFetch</div>" } },
        { path: "/tools/exppattern", component: { template: "<div>ExpPattern</div>" } },
        { path: "/tools/enrichment", component: { template: "<div>Enrichment</div>" } },
        { path: "/", component: { template: "<div>Home</div>" } },
      ],
    });
    await router.push("/tools");
    const wrapper = mount(ToolsView, { global: { plugins: [router] } });

    expect(wrapper.get('[data-testid="seqfetch-tool-link"]').attributes("href")).toBe(
      "/tools/seqfetch",
    );
    expect(wrapper.text()).toContain("up to 200 genes");
    expect(wrapper.get('[data-testid="exppattern-tool-link"]').attributes("href")).toBe(
      "/tools/exppattern",
    );
    expect(wrapper.get('[data-testid="enrichment-tool-link"]').attributes("href")).toBe(
      "/tools/enrichment",
    );
    wrapper.unmount();
  });
});
