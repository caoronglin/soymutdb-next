// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { defineComponent, h, nextTick } from "vue";
import { describe, expect, it, vi } from "vitest";

// The facade pulls in the Antdv Next runtime, which does not resolve under
// vitest's node resolver on pnpm 12 (see packages/ui-vue/src/facade.test.ts).
vi.mock("@soymutdb/ui-vue", () => ({
  Button: defineComponent({
    name: "Button",
    emits: ["click"],
    setup(_props, { emit, slots }) {
      return () => h("button", { onClick: () => emit("click") }, slots.default?.());
    },
  }),
}));

import AppErrorBoundary from "./AppErrorBoundary.vue";

const Ok = defineComponent({
  setup: () => () => h("div", { "data-testid": "recovered" }, "recovered"),
});

const Boom = defineComponent({
  setup() {
    throw new Error("kaboom");
  },
  render: () => h("div"),
});

/**
 * The slot is rendered *inside* AppErrorBoundary (a host component owns the
 * slot function) so a throwing child is a descendant of the boundary — the
 * same shape as `<AppErrorBoundary><RouterView /></AppErrorBoundary>`.
 */
const Host = defineComponent({
  props: { broken: { type: Boolean, default: true } },
  setup(props) {
    return () =>
      h(AppErrorBoundary, null, {
        default: () => h(props.broken ? Boom : Ok),
      });
  },
});

/**
 * Regression guard: without an `onErrorCaptured` boundary a render error
 * unmounts the whole tree and the portal serves a blank page (the React portal
 * wrapped its router in an ErrorBoundary; the Vue cutover dropped it).
 */
describe("AppErrorBoundary", () => {
  it("renders the fallback, not a blank page, when the subtree throws", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const wrapper = mount(Host, { props: { broken: true } });
    await nextTick();

    const fallback = wrapper.find('[data-testid="app-error-boundary"]');
    expect(fallback.exists()).toBe(true);
    expect(fallback.text()).toContain("kaboom");
    expect(wrapper.find('[data-testid="app-error-retry"]').exists()).toBe(true);
    spy.mockRestore();
  });

  it("remounts the subtree when Retry is pressed", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const wrapper = mount(Host, { props: { broken: true } });
    await nextTick();

    expect(wrapper.find('[data-testid="app-error-boundary"]').exists()).toBe(true);

    await wrapper.setProps({ broken: false });
    await wrapper.find('[data-testid="app-error-retry"]').trigger("click");
    await nextTick();

    expect(wrapper.find('[data-testid="app-error-boundary"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="recovered"]').exists()).toBe(true);
    spy.mockRestore();
  });
});
