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
  AdminHeader: () => <header data-testid="shell-header" />,
}));
// The shell renders native antd 6 `Layout`/`Menu` now. Only the presentational
// antd surface is doubled here: the real Router and `Link` stay in place, so the
// click-cancellation and reachability assertions still exercise production code.
vi.mock("../lib/antd", () => {
  // A React component's first argument is its props, so the passthrough has to
  // read `children` off them — rendering the props object itself would drop the
  // router outlet.
  const passthrough = () => ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    Grid: { useBreakpoint: () => ({ lg: true }) },
    Layout: Object.assign(passthrough(), { Sider: passthrough(), Content: passthrough() }),
    Menu: ({ items, children }: {
      items?: Array<{
        key: string;
        label?: React.ReactNode;
        type?: string;
        children?: Array<{ key: string; label?: React.ReactNode }>;
      }>;
      children?: React.ReactNode;
    }) => (
      <nav data-menu="inline">
        {items?.flatMap((item) => item.children ?? [item]).map((entry) => (
          <React.Fragment key={entry.key}>{entry.label}</React.Fragment>
        ))}
        {children}
      </nav>
    ),
    theme: { useToken: () => ({ token: { colorPrimary: "#000", colorTextLightSolid: "#fff", colorBorderSecondary: "#eee" } }) },
  };
});

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

  it("retains every NAV_SECTIONS destination, under its section group", async () => {
    await renderNavigation();
    // The sider also carries a brand link back to "/", so this asserts that
    // every destination is reachable, not that these are the only links.
    const hrefs = screen.getAllByRole("link").map((link) => link.getAttribute("href"));
    for (const item of NAV_SECTIONS.flatMap((section) => section.items)) {
      expect(hrefs).toContain(item.path);
    }
    // The old shell flattened NAV_SECTIONS, so the sidebar rendered as one
    // undifferentiated list of 19 destinations with no group headings. Grouping
    // is the point of the section list, so it is asserted rather than assumed.
    expect(screen.getByText("Overview")).toBeTruthy();
    expect(screen.getByText("Data Management")).toBeTruthy();
    expect(screen.getByText("Administration")).toBeTruthy();
  });

  it("leaves the page name to the page, not the shell", async () => {
    // The shell used to resolve a title from a path-keyed `PAGE_TITLES` map and
    // render it in the top bar, duplicating the `PageContainer` heading every
    // feature page already owns. A second authority for one page name is the
    // divergence slice A1 removed, so the bar must stay title-free — including
    // for the dashboard, whose "Dashboard" heading now comes from its own
    // PageContainer. (2026-10-01 admin Pro migration §3.1)
    await renderNavigation();
    const header = screen.getByTestId("shell-header");
    expect(header.textContent).toBe("");
    expect(header.querySelector("h1")).toBeNull();
  });
});
