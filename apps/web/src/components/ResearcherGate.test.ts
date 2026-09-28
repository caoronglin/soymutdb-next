// @vitest-environment jsdom
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { computed } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Mount the design-system buttons as native elements so the assertion is about
// the gate contract, not the component library.
vi.mock("@soymutdb/ui-vue", () => ({
  Button: {
    props: ["type", "size"],
    emits: ["click"],
    template: '<button type="button" @click="$emit(\'click\')"><slot /></button>',
  },
}));

const useCurrentUser = vi.fn();
vi.mock("../lib/current-user", () => ({
  useCurrentUser: () => useCurrentUser(),
}));

import ResearcherGate from "./ResearcherGate.vue";

function setAuthState(state: { isLoading: boolean; isResearcher: boolean }) {
  useCurrentUser.mockReturnValue({
    user: computed(() => null),
    isResearcher: computed(() => state.isResearcher),
    isLoading: computed(() => state.isLoading),
  });
}

async function mountGate() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/analyses", component: ResearcherGate },
      { path: "/login", component: { template: "<div>Login</div>" } },
      { path: "/", component: { template: "<div>Home</div>" } },
    ],
  });
  await router.push("/analyses");
  await router.isReady();
  const wrapper = mount(ResearcherGate, {
    global: { plugins: [router] },
    slots: { default: '<div data-testid="gate-content">pipeline form</div>' },
    attachTo: document.body,
  });
  return { wrapper, router };
}

describe("ResearcherGate", () => {
  beforeEach(() => {
    useCurrentUser.mockReset();
    document.body.innerHTML = "";
  });

  it("renders a loading state while the role is unresolved", async () => {
    setAuthState({ isLoading: true, isResearcher: false });

    const { wrapper } = await mountGate();

    expect(wrapper.find('[data-testid="researcher-gate-loading"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="researcher-gate-denied"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="gate-content"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("renders the denied empty state with sign-in and home actions", async () => {
    setAuthState({ isLoading: false, isResearcher: false });

    const { wrapper, router } = await mountGate();

    const denied = wrapper.get('[data-testid="researcher-gate-denied"]');
    expect(denied.text()).toContain("Research access required");
    expect(denied.text()).toContain("researcher accounts and above");
    expect(wrapper.find('[data-testid="gate-content"]').exists()).toBe(false);

    // Sign in carries the current path so the login page returns here.
    await wrapper.get('[data-testid="researcher-gate-sign-in"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/login");
    expect(router.currentRoute.value.query.redirect).toBe("/analyses");

    wrapper.unmount();
  });

  it("returns to the home page from the denied state", async () => {
    setAuthState({ isLoading: false, isResearcher: false });

    const { wrapper, router } = await mountGate();

    await wrapper.get('[data-testid="researcher-gate-back-home"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/");

    wrapper.unmount();
  });

  it("renders the default slot for a researcher", async () => {
    setAuthState({ isLoading: false, isResearcher: true });

    const { wrapper } = await mountGate();

    expect(wrapper.get('[data-testid="gate-content"]').text()).toBe("pipeline form");
    expect(wrapper.find('[data-testid="researcher-gate-loading"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="researcher-gate-denied"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
