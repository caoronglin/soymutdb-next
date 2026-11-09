import * as React from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { createMemoryHistory, createRootRoute, createRoute, createRouter, Outlet, RouterProvider } from "@tanstack/react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminLayout from "../routes/__root";
import { NAV_SECTIONS, type NavItem } from "../components/admin-sidebar";

const viewport = vi.hoisted(() => ({ desktop: true }));

// The shared double, imported inside the factory: `vi.mock` is hoisted above
// the imports, so a factory that closes over a top-level import hits the TDZ.
// An inline `useTranslation: () => ({ t: ... })` is banned by
// test_ci_job_contracts (a new `t` every render re-fires every effect).
vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
vi.mock("../components/admin-header", () => ({
  AdminHeader: ({ onToggleSidebar }: { onToggleSidebar?: () => void }) => (
    <header data-testid="shell-header"><button aria-label="Toggle sidebar" onClick={onToggleSidebar} /></header>
  ),
}));
// The shell is built on ProLayout. The double keeps the contract the shell
// relies on — `menuDataRender` supplies nested items, `menuItemRender` wraps a
// leaf in the router `Link`, and the mobile drawer is driven by the controlled
// `collapsed` prop — while the real Router and `Link` stay in place, so the
// click-cancellation and reachability assertions still exercise production code.
vi.mock("../lib/antd", () => {
  // A React component's first argument is its props, so the passthrough has to
  // read `children` off them — rendering the props object itself would drop the
  // router outlet.
  const passthrough = () => ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  interface MenuItem {
    key: string;
    name: string;
    icon?: React.ReactNode;
    path?: string;
    children?: MenuItem[];
  }
  function renderMenu(
    items: MenuItem[],
    menuItemRender?: (item: MenuItem, dom: React.ReactNode) => React.ReactNode,
  ): React.ReactNode {
    return items.map((item) => {
      if (item.children?.length) {
        return (
          <div key={item.key} data-submenu={item.name}>
            <div>{item.name}</div>
            {renderMenu(item.children, menuItemRender)}
          </div>
        );
      }
      const dom = <span>{item.name}</span>;
      return <React.Fragment key={item.key}>{menuItemRender ? menuItemRender(item, dom) : dom}</React.Fragment>;
    });
  }
  return {
    ConfigProvider: passthrough(),
    Grid: { useBreakpoint: () => ({ lg: viewport.desktop }) },
    ProLayout: ({
      children,
      menuDataRender,
      menuItemRender,
      menuHeaderRender,
      collapsed,
      onCollapse,
    }: {
      children?: React.ReactNode;
      menuDataRender?: () => MenuItem[];
      menuItemRender?: (item: MenuItem, dom: React.ReactNode) => React.ReactNode;
      menuHeaderRender?: () => React.ReactNode;
      collapsed?: boolean;
      onCollapse?: (collapsed: boolean) => void;
    }) => {
      const items = menuDataRender?.() ?? [];
      const menu = <nav data-menu="inline">{renderMenu(items, menuItemRender)}</nav>;
      const drawerOpen = !viewport.desktop && !collapsed;
      return (
        <div>
          {menuHeaderRender?.()}
          {viewport.desktop ? (
            menu
          ) : drawerOpen ? (
            <div role="dialog">
              <button aria-label="Close navigation" onClick={() => onCollapse?.(true)} />
              {menu}
            </div>
          ) : null}
          <main>{children}</main>
        </div>
      );
    },
    theme: { defaultAlgorithm: () => ({}), darkAlgorithm: () => ({}), useToken: () => ({ token: { colorPrimary: "#000", colorTextLightSolid: "#fff", colorBorderSecondary: "#eee", marginXS: 4, paddingLG: 24, paddingMD: 16 } }) },
  };
});

afterEach(() => { cleanup(); viewport.desktop = true; });

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
  it("opens mobile navigation from the header and closes it after navigating", async () => {
    viewport.desktop = false;
    const router = await renderNavigation();
    expect(screen.queryByRole("dialog")).toBeNull();
    await act(async () => { screen.getByRole("button", { name: "Toggle sidebar" }).click(); });
    expect(screen.getByRole("dialog")).toBeTruthy();
    await act(async () => { screen.getByRole("link", { name: "Usage guide" }).click(); });
    await waitFor(() => expect(router.state.location.pathname).toBe("/guide"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(await screen.findByText("guide-body")).toBeTruthy();
  });

  it("announces the current destination after client navigation", async () => {
    const router = await renderNavigation();
    const welcome = screen.getByRole("link", { name: "Welcome" });
    const guide = screen.getByRole("link", { name: "Usage guide" });
    expect(welcome.getAttribute("aria-current")).toBe("page");
    expect(guide.hasAttribute("aria-current")).toBe(false);

    await act(async () => { guide.click(); });
    await waitFor(() => expect(router.state.location.pathname).toBe("/guide"));
    expect(guide.getAttribute("aria-current")).toBe("page");
    expect(welcome.hasAttribute("aria-current")).toBe(false);
  });

  it("closes the mobile drawer from its own close control", async () => {
    viewport.desktop = false;
    await renderNavigation();
    await act(async () => { screen.getByRole("button", { name: "Toggle sidebar" }).click(); });
    expect(screen.getByRole("dialog")).toBeTruthy();
    await act(async () => { screen.getByRole("button", { name: "Close navigation" }).click(); });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("provides a keyboard skip link to main content", async () => {
    await renderNavigation();
    const link = screen.getByRole("link", { name: "Skip to main content" });
    expect(link.getAttribute("href")).toBe("#admin-main-content");
  });

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
    const flatten = (items: NavItem[]): NavItem[] =>
      items.flatMap((item) => [item, ...(item.children ? flatten(item.children) : [])]);
    const leaves = NAV_SECTIONS.flatMap((section) => flatten(section.items)).filter((item) => item.path);
    for (const item of leaves) {
      expect(hrefs).toContain(item.path);
    }
    // The old shell flattened NAV_SECTIONS, so the sidebar rendered as one
    // undifferentiated list of destinations with no group headings. Grouping
    // is the point of the section list, so it is asserted rather than assumed.
    // "Overview" is both a section heading and the first `/settings/*`
    // destination, so the headings are asserted by presence, not by uniqueness.
    for (const heading of ["Overview", "Data Management", "Content", "Administration"]) {
      expect(screen.getAllByText(heading).length).toBeGreaterThan(0);
    }
    // Multi-level navigation: each submenu renders as its own branch above its
    // children, instead of every destination sitting at the top level. The
    // branch marker is asserted rather than the label text, because "Pages" is
    // both a submenu and one of its destinations.
    const submenus = Array.from(document.querySelectorAll("[data-submenu]")).map((node) =>
      node.getAttribute("data-submenu"),
    );
    for (const label of ["Dashboards", "Imports", "Pages", "News", "Settings"]) {
      expect(submenus).toContain(label);
    }
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
