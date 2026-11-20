/**
 * The consolidated site-appearance surface.
 *
 * Two product claims are load-bearing here and both are cheap to get wrong:
 *
 * 1. The public site is the only default. The internal editors must not mount
 *    until the operator opens the explicit override, so `/settings/appearance`
 *    cannot become the two-peer-variant tabs it replaced.
 * 2. The footer editor writes the *existing* footer contract: the
 *    `footer_external` settings document with `navigation_json` and the
 *    per-language copyright lines, at the version it read (optimistic locking).
 *    A footer UI that invented its own key would render and save nothing.
 */
import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("@/lib/antd", async () => (await import("../../test/antd-double")));
vi.mock("@/components/media-picker", () => ({ MediaPicker: () => null }));

const api = vi.hoisted(() => ({
  settingsGet: vi.fn(),
  settingsPatch: vi.fn(),
  brandGet: vi.fn(),
  brandPatch: vi.fn(),
  siteNavigation: vi.fn(),
  features: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    adminSettingsApi: {
      ...actual.adminSettingsApi,
      get: api.settingsGet,
      patch: api.settingsPatch,
    },
    capabilitiesApi: { ...actual.capabilitiesApi, adminGet: api.features },
    getSiteNavigation: api.siteNavigation,
    getAdminSiteBranding: api.brandGet,
    patchAdminSiteBranding: api.brandPatch,
  };
});

const { messageCalls } = await import("../../test/antd-double");
const { SiteAppearanceSections } = await import("./site-appearance");

const FOOTER_NAVIGATION = {
  schema_version: 1,
  groups: [
    {
      id: "explore",
      title_en: "Explore",
      title_zh: "浏览",
      enabled: true,
      order: 0,
      links: [
        {
          id: "genes",
          label_en: "Genes",
          label_zh: "基因",
          target: "internal",
          href: "/genes",
          enabled: true,
          order: 0,
        },
      ],
    },
  ],
};

const HEADER_NAVIGATION = {
  schema_version: 1,
  groups: [
    { id: "main", title_en: "Main", title_zh: "主导航", enabled: true, order: 0, links: [] },
  ],
};

const FOOTER_EXTERNAL_VERSION = 3;
const HEADER_EXTERNAL_VERSION = 2;

function settingsDocument(section: string) {
  if (section === "footer_external" || section === "footer_internal") {
    return {
      section,
      version: FOOTER_EXTERNAL_VERSION,
      values: {
        navigation_json: JSON.stringify(FOOTER_NAVIGATION),
        copyright_en: "",
        copyright_zh: "",
        copyright: "© {{year}} SoyMutDB. All rights reserved.",
      },
    };
  }
  if (section === "header_external" || section === "header_internal") {
    return {
      section,
      version: HEADER_EXTERNAL_VERSION,
      values: { navigation_json: JSON.stringify(HEADER_NAVIGATION) },
    };
  }
  throw new Error(`unexpected settings section ${section}`);
}

/**
 * The surface links to the media library with the router `Link`, so the test
 * needs a real router with that destination registered — a stub `Link` would
 * stop exercising the one cross-page navigation the page ships.
 */
async function renderSurface() {
  const rootRoute = createRootRoute({ component: () => <Outlet /> });
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    component: () => <SiteAppearanceSections />,
  });
  const mediaRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/media",
    component: () => null,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([indexRoute, mediaRoute]),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  // `router.load()` settles the route tree; without it the first assertion races
  // the router's own match resolution rather than the query it is about.
  await router.load();
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

function requestedSections(): string[] {
  return api.settingsGet.mock.calls.map(([section]) => String(section));
}

beforeEach(() => {
  messageCalls.length = 0;
  api.settingsGet.mockReset().mockImplementation(async (section: string) => settingsDocument(section));
  api.settingsPatch
    .mockReset()
    .mockImplementation(async (section: string) => ({
      ...settingsDocument(section),
      version: FOOTER_EXTERNAL_VERSION + 1,
    }));
  api.brandGet.mockReset().mockResolvedValue({
    variant: "external",
    version: 1,
    values: { name_zh: "大豆突变体数据库", name_en: "SoyMutDB", icon_url: "" },
  });
  api.brandPatch.mockReset();
  api.siteNavigation.mockReset().mockResolvedValue({ variant: "external", groups: [] });
  api.features.mockReset().mockResolvedValue({ features: [] });
});

describe("site appearance sections", () => {
  it("edits the public site first and never mounts the internal editors by itself", async () => {
    await renderSurface();

    // Both public editors hydrated from their own settings documents.
    expect(await screen.findByDisplayValue("Genes")).toBeTruthy();
    expect(await screen.findByDisplayValue("Main")).toBeTruthy();

    expect(requestedSections()).toContain("footer_external");
    expect(requestedSections()).toContain("header_external");
    expect(requestedSections()).not.toContain("footer_internal");
    expect(requestedSections()).not.toContain("header_internal");
    expect(screen.queryByTestId("site-variant-internal-panel")).toBeNull();
  });

  it("reveals the internal editors only after the explicit override is switched on", async () => {
    await renderSurface();
    await screen.findByDisplayValue("Genes");

    fireEvent.click(screen.getByTestId("site-variant-internal-switch"));

    await waitFor(() => {
      expect(requestedSections()).toContain("footer_internal");
      expect(requestedSections()).toContain("header_internal");
    });
    expect(screen.getByTestId("site-variant-internal-panel")).toBeTruthy();
  });

  it("saves the footer through the existing footer contract at the version it read", async () => {
    await renderSurface();
    const labelInput = await screen.findByDisplayValue("Genes");

    fireEvent.change(labelInput, { target: { value: "All genes" } });
    fireEvent.click(
      screen.getByRole("button", { name: "admin.siteAppearance.footer.save" }),
    );

    await waitFor(() => expect(api.settingsPatch).toHaveBeenCalledTimes(1));
    const [section, expectedVersion, values] = api.settingsPatch.mock.calls[0] as [
      string,
      number,
      { navigation_json: string; copyright_en: string; copyright_zh: string },
    ];
    expect(section).toBe("footer_external");
    expect(expectedVersion).toBe(FOOTER_EXTERNAL_VERSION);
    expect(values.copyright_en).toBe("");
    expect(values.copyright_zh).toBe("");
    const saved = JSON.parse(values.navigation_json) as typeof FOOTER_NAVIGATION;
    expect(saved.groups[0].links[0]).toEqual({
      id: "genes",
      label_en: "All genes",
      label_zh: "基因",
      target: "internal",
      href: "/genes",
      enabled: true,
      order: 0,
    });
  });

  it("reports a rejected footer save instead of looking successful", async () => {
    await renderSurface();
    const labelInput = await screen.findByDisplayValue("Genes");

    api.settingsPatch.mockRejectedValueOnce(new Error("422 validation failed"));
    fireEvent.change(labelInput, { target: { value: "All genes" } });
    fireEvent.click(
      screen.getByRole("button", { name: "admin.siteAppearance.footer.save" }),
    );

    await waitFor(() =>
      expect(messageCalls.some((call) => call.level === "error")).toBe(true),
    );
    expect(messageCalls.find((call) => call.level === "error")?.content).toContain(
      "422 validation failed",
    );
    expect(messageCalls.some((call) => call.level === "success")).toBe(false);
  });
});