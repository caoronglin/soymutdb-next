import * as React from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from "@tanstack/react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminLayout from "../routes/__root";
import { NAV_SECTIONS } from "../components/admin-sidebar";

// The shared double, imported inside the factory: `vi.mock` is hoisted above
// the imports, so a factory that closes over a top-level import hits the TDZ.
// An inline `useTranslation: () => ({ t: ... })` is banned by
// test_ci_job_contracts (a new `t` every render re-fires every effect).
vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
vi.mock("../components/admin-header", () => ({
  AdminHeader: ({ title }: { title: string }) => <header>{title}</header>,
}));
// Keep the production menuItemRender callback, with the real Router and Link.
// Only the unrelated ProLayout presentation shell is replaced.
vi.mock("../lib/antd", () => ({
  ProLayout: ({ route, menuItemRender, headerRender, children }: {
    route: { routes: Array<{ path: string; name: string }> };
    menuItemRender: (item: { path?: string }, dom: React.ReactNode) => React.ReactNode;
    headerRender: false;
    children: React.ReactNode;
  }) => <div data-header-render={String(headerRender)}>
    <nav>{route.routes.map((item) => <React.Fragment key={item.path}>
      {menuItemRender(item, item.name)}
    </React.Fragment>)}</nav>
    {children}
  </div>,
}));

afterEach(cleanup);

async function renderNavigation() {
  const root = createRootRoute({ component: () => <AdminLayout><Outlet /></AdminLayout> });
  const index = createRoute({ getParentRoute: () => root, path: "/", component: () => <p>dashboard-body</p> });
  const guide = createRoute({ getParentRoute: () => root, path: "/guide", component: () => <p>guide-body</p> });
  const router = createRouter({ routeTree: root.addChildren([index, guide]), history: createMemoryHistory({ initialEntries: ["/"] }) });
  await act(async () => { await router.load(); });
  render(<RouterProvider router={router} />);
  await screen.findByText("dashboard-body");
  return router;
}

describe("admin root navigation rendering", () => {
  it("uses client navigation and cancels the browser document-navigation default", async () => {
    const router = await renderNavigation();
    const link = screen.getByRole("link", { name: "Usage guide" });
    const event = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    await act(async () => { link.dispatchEvent(event); });
    expect(event.defaultPrevented).toBe(true);
    await waitFor(() => expect(router.state.location.pathname).toBe("/guide"));
    expect(await screen.findByText("guide-body")).toBeTruthy();
    expect(screen.queryByText("dashboard-body")).toBeNull();
  });

  it("retains every NAV_SECTIONS destination and the disabled Pro header", async () => {
    await renderNavigation();
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual(
      NAV_SECTIONS.flatMap((section) => section.items.map((item) => item.path)),
    );
    expect(document.querySelector('[data-header-render="false"]')).toBeTruthy();
    expect(screen.getByRole("banner").textContent).toBe("Dashboard");
  });
});
