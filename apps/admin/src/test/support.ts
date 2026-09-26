// @vitest-environment jsdom
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { mount, type VueWrapper } from "@vue/test-utils";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter, type RouteRecordRaw } from "vue-router";
import { beforeEach, vi } from "vitest";
import type { Component } from "vue";

vi.mock("@soymutdb/ui-vue", () => ({
  ConfigProvider: { template: "<div><slot /></div>" },
  createThemeConfig: () => ({}),
  Button: {
    props: ["disabled", "type", "htmlType", "size"],
    emits: ["click"],
    template:
      '<button :type="htmlType ?? type ?? \'button\'" :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  Tag: { props: ["color"], template: "<span><slot /></span>" },
  Table: { template: "<table><slot /></table>" },
}));

/**
 * Mount one admin view with the router, Pinia and an isolated query client.
 *
 * `attachTo` matters: jsdom only dispatches `submit` for a form that is part of
 * the document, so a detached wrapper would never fire a submit handler.
 */
export function mountAdminView(
  component: Component,
  options: { path: string; query?: Record<string, string>; push?: string } = { path: "/" },
): { wrapper: VueWrapper; router: ReturnType<typeof createRouter>; pinia: ReturnType<typeof createPinia> } {
  const routes: RouteRecordRaw[] = [
    { path: options.path, name: options.path, component },
    { path: "/:pathMatch(.*)*", component },
  ];
  const router = createRouter({ history: createMemoryHistory(), routes });
  void router.push({ path: options.push ?? options.path, query: options.query ?? {} });
  const pinia = createPinia();
  const wrapper = mount(component, {
    attachTo: document.body,
    global: {
      plugins: [
        pinia,
        router,
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
      ],
    },
  });
  return { wrapper, router, pinia };
}

beforeEach(() => {
  document.body.innerHTML = "";
  vi.clearAllMocks();
});
