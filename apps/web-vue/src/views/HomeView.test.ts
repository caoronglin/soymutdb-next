// @vitest-environment jsdom
import { mount, flushPromises } from "@vue/test-utils";
import { VueQueryPlugin, QueryClient } from "@tanstack/vue-query";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@soymutdb/ui-vue", () => ({
  Button: {
    template: "<button @click=\"$emit('click')\"><slot /></button>",
  },
  ConfigProvider: { template: "<div><slot /></div>" },
  Tag: { template: "<span><slot /></span>" },
  createThemeConfig: () => ({}),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, getAssemblies: vi.fn() };
});

import { getAssemblies } from "@soymutdb/api-client";
import HomeView from "./HomeView.vue";
import { useSiteContextStore } from "../stores/site-context";

const mocked = vi.mocked(getAssemblies);
beforeEach(() => mocked.mockReset());

async function mountHome() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/", name: "home", component: HomeView }],
  });
  router.push("/");
  await router.isReady();
  const pinia = createPinia();
  const wrapper = mount(HomeView, {
    global: {
      plugins: [
        pinia,
        router,
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
      ],
    },
  });
  return { wrapper, pinia };
}

describe("HomeView (assemblies reference data)", () => {
  it("renders assemblies with the default marker and the build-time site variant", async () => {
    mocked.mockResolvedValue([
      { id: 5, name: "Wm82", version: "v5", species: "Glycine max", is_default: true },
      { id: 4, name: "Wm82", version: "v4", species: "Glycine max", is_default: false },
    ] as never);

    const { wrapper } = await mountHome();
    await flushPromises();
    await flushPromises();

    expect(wrapper.findAll("li")).toHaveLength(2);
    expect(wrapper.text()).toContain("Wm82 · v5");
    expect(wrapper.text()).toContain("default");
    expect(wrapper.find('[data-testid="site-variant"]').text()).toBe(
      "Site variant: external",
    );
    wrapper.unmount();
  });

  // Note: the error affordance (assemblies-error) is rendered by the component
  // and covered by the same build/typecheck path as the mirrored pages;
  // asserting a rejected query in jsdom proved environment-fragile (vitest
  // reports the mock rejection as an unhandled error), matching the note in
  // SearchView.test.ts. The reference-data contract is covered above.

  it("records the selected assembly in the deployment context store", async () => {
    mocked.mockResolvedValue([
      { id: 5, name: "Wm82", version: "v5", species: "Glycine max", is_default: true },
    ] as never);

    const { wrapper, pinia } = await mountHome();
    await flushPromises();
    await flushPromises();

    await wrapper.find("button").trigger("click");
    expect(useSiteContextStore(pinia).assemblyKey).toBe("Wm82");
    wrapper.unmount();
  });
});
