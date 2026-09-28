// @vitest-environment jsdom
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia } from "pinia";
import { defineComponent, h, nextTick } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The @soymutdb/ui-vue facade pulls in the Antdv Next runtime, which does not
// resolve under vitest's node resolver on pnpm 12 (see
// packages/ui-vue/src/facade.test.ts). The palette itself is dependency-free,
// but the portal mounts the header through the same module graph.
vi.mock("@soymutdb/ui-vue", () => ({
  ConfigProvider: defineComponent({ setup: (_p, { slots }) => () => h("div", slots.default?.()) }),
  createThemeConfig: () => ({}),
}));

import PortalCommandPalette from "./PortalCommandPalette.vue";
import { useSiteContextStore } from "../stores/site-context";

/** Mount the palette on a fresh memory router + Pinia (no shared state). */
function mountPalette(): { wrapper: VueWrapper; router: Router } {
  const routes = [
    { path: "/", name: "home", component: { template: "<div />" } },
    { path: "/browser", name: "browser", component: { template: "<div />" } },
    { path: "/genes", name: "genes", component: { template: "<div />" } },
    { path: "/variants", name: "variants", component: { template: "<div />" } },
    { path: "/blast", name: "blast", component: { template: "<div />" } },
    { path: "/downloads", name: "downloads", component: { template: "<div />" } },
    { path: "/help", name: "help", component: { template: "<div />" } },
    { path: "/search", name: "search", component: { template: "<div />" } },
  ];
  const router = createRouter({ history: createMemoryHistory(), routes });
  void router.push("/");
  const wrapper = mount(PortalCommandPalette, {
    attachTo: document.body,
    global: { plugins: [createPinia(), router] },
  });
  return { wrapper, router };
}

async function pressCtrlK() {
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }));
  // Two ticks for the v-if to mount and one for the open watcher's focus.
  for (let i = 0; i < 3; i += 1) await nextTick();
}

async function openPalette(wrapper: VueWrapper) {
  await pressCtrlK();
  return wrapper.get<HTMLInputElement>('[data-testid="portal-command-palette-input"]');
}

async function type(input: { setValue: (value: string) => Promise<void> }, value: string) {
  await input.setValue(value);
  await nextTick();
}

beforeEach(() => {
  document.body.innerHTML = "";
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("PortalCommandPalette", () => {
  it("is hidden until the shortcut is pressed and toggles from there", async () => {
    const { wrapper } = mountPalette();
    expect(wrapper.find('[data-testid="portal-command-palette"]').exists()).toBe(false);

    await pressCtrlK();
    expect(wrapper.find('[data-testid="portal-command-palette"]').exists()).toBe(true);

    // Cmd/Ctrl+K toggles the open palette closed again.
    await pressCtrlK();
    expect(wrapper.find('[data-testid="portal-command-palette"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("opens on meta+K, focuses the input, and renders every quick action by default", async () => {
    const { wrapper } = mountPalette();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }));
    await nextTick();
    await nextTick();
    await nextTick();

    const input = wrapper.get<HTMLInputElement>('[data-testid="portal-command-palette-input"]');
    expect(document.activeElement).toBe(input.element);

    const panel = wrapper.get('[data-testid="portal-command-palette"]');
    expect(panel.attributes("role")).toBe("dialog");
    expect(panel.attributes("aria-modal")).toBe("true");
    // The search row is absent while the query is empty; all six actions show.
    expect(wrapper.find('[data-testid="portal-command-palette-option-search"]').exists()).toBe(false);
    expect(wrapper.findAll('[role="option"]')).toHaveLength(6);
    expect(input.element.value).toBe("");
    // Every visible string resolves through `defaultValue` while the shared
    // dictionary has no `commandPalette.*` namespace yet — no raw key leaks.
    expect(wrapper.text()).not.toContain("commandPalette.");
    expect(input.attributes("placeholder")).toBe("Search pages, genes, variants…");
    wrapper.unmount();
  });

  it("closes on Escape and resets query and highlight for the next open", async () => {
    const { wrapper } = mountPalette();
    const input = await openPalette(wrapper);
    await type(input, "genes");

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await nextTick();
    expect(wrapper.find('[data-testid="portal-command-palette"]').exists()).toBe(false);

    await pressCtrlK();
    const reopened = wrapper.get<HTMLInputElement>('[data-testid="portal-command-palette-input"]');
    expect(reopened.element.value).toBe("");
    expect(reopened.attributes("aria-activedescendant")).toBe(
      wrapper.get('[role="option"]').attributes("id"),
    );
    wrapper.unmount();
  });

  it("ArrowDown moves the highlight and Enter runs the highlighted action", async () => {
    const { wrapper, router } = mountPalette();
    const input = await openPalette(wrapper);

    const options = wrapper.findAll('[role="option"]');
    expect(options[0].attributes("aria-selected")).toBe("true");

    // Step over the first entry so the highlight is on the second (genes).
    await input.trigger("keydown", { key: "ArrowDown" });
    const selected = wrapper.findAll('[role="option"]').filter((o) => o.attributes("aria-selected") === "true");
    expect(selected).toHaveLength(1);
    expect(selected[0].attributes("id")).toBe(wrapper.findAll('[role="option"]')[1].attributes("id"));

    await input.trigger("keydown", { key: "Enter" });
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/genes");
    // Selecting closes the palette.
    expect(wrapper.find('[data-testid="portal-command-palette"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("ArrowUp does not move above the first entry", async () => {
    const { wrapper } = mountPalette();
    const input = await openPalette(wrapper);

    await input.trigger("keydown", { key: "ArrowUp" });
    expect(wrapper.findAll('[role="option"]')[0].attributes("aria-selected")).toBe("true");
    wrapper.unmount();
  });

  it("offers a search entry for an unmatched query and pushes /search with the trimmed query", async () => {
    const { wrapper, router } = mountPalette();
    const input = await openPalette(wrapper);

    await type(input, "Glyma.01G000100");
    const searchOption = wrapper.get('[data-testid="portal-command-palette-option-search"]');
    expect(searchOption.attributes("aria-selected")).toBe("true");
    expect(searchOption.text()).toContain("Glyma.01G000100");
    expect(wrapper.findAll('[role="option"]')).toHaveLength(1);

    await input.trigger("keydown", { key: "Enter" });
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/search");
    expect(router.currentRoute.value.query).toEqual({ q: "Glyma.01G000100" });
    wrapper.unmount();
  });

  it("carries the site assembly into the search query like the header does", async () => {
    const { wrapper, router } = mountPalette();
    useSiteContextStore().setAssembly("gmax_v5");
    const input = await openPalette(wrapper);

    await type(input, "  Glyma.01G000100  ");
    await input.trigger("keydown", { key: "Enter" });
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/search");
    expect(router.currentRoute.value.query).toEqual({ q: "Glyma.01G000100", assembly: "gmax_v5" });
    wrapper.unmount();
  });

  it("shows the empty state when neither an action nor a distinct search row matches", async () => {
    const { wrapper } = mountPalette();
    const input = await openPalette(wrapper);

    await type(input, "genes");
    // "genes" matches the Browse Genes action, so the empty state is hidden.
    expect(wrapper.find('[data-testid="portal-command-palette-empty"]').exists()).toBe(false);

    await type(input, "zzz-nothing");
    expect(wrapper.find('[data-testid="portal-command-palette-empty"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="portal-command-palette-empty"]').text()).toContain("zzz-nothing");
    wrapper.unmount();
  });

  it("restores focus to the element that was focused before opening", async () => {
    const { wrapper } = mountPalette();
    const trigger = document.createElement("button");
    document.body.append(trigger);
    trigger.focus();

    await pressCtrlK();
    expect(document.activeElement).not.toBe(trigger);

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await nextTick();
    await nextTick();
    expect(document.activeElement).toBe(trigger);
    wrapper.unmount();
  });

  it("hides the genome-browser entry in a core-only deployment", async () => {
    vi.stubEnv("VITE_JBROWSE_ENABLED", "0");
    const { wrapper, router } = mountPalette();
    await openPalette(wrapper);

    const testIds = wrapper.findAll('[role="option"]').map((o) => o.attributes("data-testid"));
    expect(testIds).not.toContain("portal-command-palette-option-browser");
    expect(wrapper.findAll('[role="option"]')).toHaveLength(5);

    // The core entries stay and still route.
    await wrapper.get('[data-testid="portal-command-palette-option-genes"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/genes");
    wrapper.unmount();
  });

  it("keeps the genome-browser entry by default and removes the listener on unmount", async () => {
    vi.stubEnv("VITE_JBROWSE_ENABLED", "1");
    const { wrapper, router } = mountPalette();
    await openPalette(wrapper);

    expect(wrapper.find('[data-testid="portal-command-palette-option-browser"]').exists()).toBe(true);
    await wrapper.get('[data-testid="portal-command-palette-option-browser"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/browser");

    wrapper.unmount();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }));
    await nextTick();
    expect(document.querySelector('[data-testid="portal-command-palette"]')).toBeNull();
  });
});
