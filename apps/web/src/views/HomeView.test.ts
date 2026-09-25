// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";

import { mountPortalView } from "../test/mount-portal-view";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getAssemblies, getFeaturedNews, listNews } from "@soymutdb/api-client";
import HomeView from "./HomeView.vue";
import { useSiteContextStore } from "../stores/site-context";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, getAssemblies: vi.fn(), listNews: vi.fn(), getFeaturedNews: vi.fn() };
});

const mocked = vi.mocked(getAssemblies);

const ASSEMBLIES = [
  { id: 5, name: "Wm82", version: "v5", species: "Glycine max", is_default: true },
  { id: 4, name: "Wm82", version: "v4", species: "Glycine max", is_default: false },
];

beforeEach(() => {
  mocked.mockReset().mockResolvedValue(ASSEMBLIES as never);
  vi.mocked(listNews).mockReset().mockResolvedValue({ items: [], total: 0 } as never);
  vi.mocked(getFeaturedNews).mockReset().mockResolvedValue([] as never);
});

async function mountHome() {
  const result = mountPortalView(HomeView, { path: "/" });
  await flushPromises();
  await flushPromises();
  return result;
}

describe("HomeView (database entry point)", () => {
  it("puts the identifier search and the five task entries above everything else", async () => {
    const { wrapper } = await mountHome();

    // The search comes first in document order: the database workflow leads,
    // the content sections follow.
    expect(wrapper.find('[data-testid="home-search-input"]').exists()).toBe(true);
    const taskEntries = wrapper.findAll('[data-testid="task-entries"] > li > *');
    expect(taskEntries).toHaveLength(5);
    expect(taskEntries[0]!.attributes("data-testid")).toBe("task-gene-search");
    expect(taskEntries.map((entry) => entry.attributes("data-testid"))).toEqual([
      "task-gene-search",
      "task-location-search",
      "task-jbrowse",
      "task-blast",
      "task-primer",
    ]);
    // The news section comes after the task entries in document order: a
    // database portal must not put editorial content above the identifier
    // search. (jsdom has no layout, so the assertion is on DOM order.)
    const headings = wrapper.findAll("h2").map((heading) => heading.text());
    expect(headings.indexOf("home.tasks")).toBeLessThan(headings.indexOf("Latest News"));
    wrapper.unmount();
  });

  it("renders assemblies with the default marker", async () => {
    const { wrapper } = await mountHome();

    expect(wrapper.findAll('[data-testid="assemblies-list"] li')).toHaveLength(2);
    expect(wrapper.text()).toContain("Wm82 · v5");
    expect(wrapper.text()).toContain("default");
    expect(wrapper.find('[data-testid="portal-context"]').text()).toContain("external");
    wrapper.unmount();
  });

  it("records the selected assembly in the deployment context store", async () => {
    const { wrapper, pinia } = await mountHome();

    await wrapper.get('[data-testid="assemblies-list"] button').trigger("click");
    expect(useSiteContextStore(pinia).assemblyKey).toBe("Wm82");
    wrapper.unmount();
  });

  it("routes the identifier search into the global search", async () => {
    const { wrapper, router } = await mountHome();
    await wrapper.get('[data-testid="home-search-input"]').setValue("Glyma.01G000100");
    await wrapper.get('[data-testid="home-search-submit"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.query).toMatchObject({
      q: "Glyma.01G000100",
    });
    wrapper.unmount();
  });
});
