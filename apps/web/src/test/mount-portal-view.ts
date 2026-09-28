// @vitest-environment jsdom
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { mount, type VueWrapper } from "@vue/test-utils";
import { createMemoryHistory, createRouter, type RouteRecordRaw } from "vue-router";
import { createPinia } from "pinia";
import { beforeEach, vi } from "vitest";
import type { Component } from "vue";

vi.mock("@soymutdb/ui-vue", () => ({
  ConfigProvider: { template: "<div><slot /></div>" },
  createThemeConfig: () => ({}),
  // Antdv Next primitives used by the portal pages. Mounted as thin native
  // elements so a test asserts the app contract, not the component library.
  //
  // The `value` + `update:value` pair is the REAL antdv-next contract: the
  // library declares no `modelValue` on any component, so a stub that answers
  // `v-model` is a stub that lies. It hid a shipped bug where the global search
  // box and the mutagen filter were bound with a bare `v-model` and therefore
  // never updated their ref. Keep these stubs faithful; the static guard in
  // `src/regression/antdv-input-binding.test.ts` keeps the templates honest.
  Button: {
    props: ["disabled", "type", "htmlType", "size"],
    emits: ["click"],
    template:
      '<button :type="htmlType ?? type ?? \'button\'" :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  Input: {
    props: ["value", "placeholder", "type", "disabled"],
    emits: ["update:value"],
    template:
      '<input :value="value" :type="type ?? \'text\'" :placeholder="placeholder" :disabled="disabled" @input="$emit(\'update:value\', ($event.target as HTMLInputElement).value)" />',
  },
  Select: {
    props: ["value", "options"],
    emits: ["update:value", "change"],
    template:
      '<select :value="value" @change="$emit(\'update:value\', ($event.target as HTMLSelectElement).value); $emit(\'change\', $event)"><option /><slot /></select>',
  },
  Card: {
    props: ["title", "hoverable", "size", "bordered"],
    template: '<div><slot name="extra" /><slot /></div>',
  },
  Space: { props: ["size", "direction", "wrap", "align"], template: '<div><slot /></div>' },
  Tag: { props: ["color"], template: '<span><slot /></span>' },
  Table: { template: '<table><slot /></table>' },
  Empty: { template: '<div><slot /></div>' },
  Spin: { template: '<div><slot /></div>' },
}));

/**
 * Mount one portal view with the router, Pinia, and an isolated query client.
 *
 * `attachTo` matters: jsdom only dispatches `submit` for a form that is part
 * of the document, so a detached wrapper would silently never fire a form
 * submit handler (the regression this helper exists to prevent).
 */
export function mountPortalView(
  component: Component,
  options: { path: string; query?: Record<string, string> } = { path: "/" },
): { wrapper: VueWrapper; router: ReturnType<typeof createRouter>; pinia: ReturnType<typeof createPinia> } {
  const routes: RouteRecordRaw[] = [
    { path: options.path, name: options.path, component },
    { path: "/:pathMatch(.*)*", component },
  ];
  const router = createRouter({ history: createMemoryHistory(), routes });
  router.push({ path: options.path, query: options.query ?? {} });
  const pinia = createPinia();
  const wrapper = mount(component, {
    attachTo: document.body,
    global: {
      plugins: [
        pinia,
        router,
        [
          VueQueryPlugin,
          {
            queryClient: new QueryClient({
              defaultOptions: { queries: { retry: false } },
            }),
          },
        ],
      ],
    },
  });
  return { wrapper, router, pinia };
}

beforeEach(() => {
  document.body.innerHTML = "";
  vi.clearAllMocks();
});
