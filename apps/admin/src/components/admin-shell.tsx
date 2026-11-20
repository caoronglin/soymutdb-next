import * as React from "react";
import { useTranslation } from "react-i18next";
import { Link, useRouterState } from "@tanstack/react-router";
import { motionTokens } from "@soymutdb/ui-react";
import { ConfigProvider, Grid, ProLayout, theme } from "../lib/antd";
import { useAdminMotion } from "../lib/motion-preference";
import { NAV_SECTIONS, type NavItem } from "./admin-sidebar";

/** The subset of ProLayout's menu item contract this shell builds. */
interface AdminMenuItem {
  key: string;
  name: string;
  icon?: React.ReactNode;
  path?: string;
  type?: "group";
  children?: AdminMenuItem[];
}

type Translate = (key: string, options?: { defaultValue?: string }) => string;

function label(item: Pick<NavItem, "label" | "labelKey">, t: Translate): string {
  return t(item.labelKey, { defaultValue: item.label });
}

/**
 * A submenu needs a path even though it is not itself a destination.
 * `transformRoute` resolves a pathless node inside a pathless group to `/`,
 * so every submenu would register `/` in the flat menu map — the last one
 * wins, and on `/` the match lands on Settings instead of Welcome. Pointing
 * the submenu at its first leaf keeps the flat map collision-free; the
 * renderer still treats it as a toggle because only leaves are links.
 */
function firstLeafPath(item: NavItem): string | undefined {
  if (item.path) return item.path;
  for (const child of item.children ?? []) {
    const hit = firstLeafPath(child);
    if (hit) return hit;
  }
  return undefined;
}

function menuItems(items: NavItem[], t: Translate): AdminMenuItem[] {
  return items.map((item) => {
    const path = item.children ? firstLeafPath(item) : item.path;
    const entry: AdminMenuItem = {
      key: item.path ?? `menu:${item.labelKey}`,
      name: label(item, t),
      path,
      icon: item.icon ? React.createElement(item.icon, { "aria-hidden": true }) : undefined,
    };
    return item.children ? { ...entry, children: menuItems(item.children, t) } : entry;
  });
}

function routes(items: NavItem[], t: Translate): Array<Record<string, unknown>> {
  return items.map((item) => ({
    path: item.path,
    name: label(item, t),
    icon: item.icon ? React.createElement(item.icon, { "aria-hidden": true }) : undefined,
    routes: item.children ? routes(item.children, t) : undefined,
  }));
}

/** Paths without a submenu, the only entries that are links. */
function leafPaths(items: NavItem[]): string[] {
  return items.flatMap((item) => [
    ...(item.path ? [item.path] : []),
    ...(item.children ? leafPaths(item.children) : []),
  ]);
}

/**
 * The currently selected destination, matched by the longest prefix so
 * `/settings/security` selects itself rather than the `/settings` overview.
 * `/` is matched exactly: as a prefix it would match every route.
 */
function selectedKey(pathname: string): string | undefined {
  return leafPaths(NAV_SECTIONS.flatMap((section) => section.items))
    .filter((path) => (path === "/" ? pathname === "/" : pathname === path || pathname.startsWith(`${path}/`)))
    .sort((a, b) => b.length - a.length)[0];
}

/**
 * Admin shell built on ProLayout.
 *
 * ProLayout supplies the parts this console kept hand-rolling: the sider menu,
 * the mobile drawer (driven by the controlled `collapsed` prop), the selected
 * menu keys derived from the location, and the breadcrumb map that
 * `PageContainer` reads. The console keeps its own top bar because it carries
 * instance context, the command palette, notifications, theme and the user menu
 * — controls that belong to this product, not to a template.
 *
 * `NAV_SECTIONS` stays the one navigation source of truth; the reachability
 * and render regression tests read it directly.
 */
export function AdminShell({ children }: {
  children: React.ReactNode | ((toggleNavigation: () => void) => React.ReactNode);
}) {
  const { t } = useTranslation();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const screens = Grid.useBreakpoint();
  const isDesktop = screens.lg ?? true;
  // ProLayout opens the mobile drawer when `collapsed` is false and treats a
  // controlled `collapsed` as the single source of truth, so the shell owns it.
  const [collapsed, setCollapsed] = React.useState(() => !isDesktop);

  React.useEffect(() => {
    setCollapsed(!isDesktop);
  }, [isDesktop]);

  const menuData = React.useMemo<AdminMenuItem[]>(
    () =>
      NAV_SECTIONS.map((section) => ({
        key: `section:${section.labelKey}`,
        name: label(section, t),
        type: "group" as const,
        children: menuItems(section.items, t),
      })),
    [t],
  );

  const route = React.useMemo(
    () => ({
      path: "/",
      routes: NAV_SECTIONS.map((section) => ({
        name: label(section, t),
        routes: routes(section.items, t),
      })),
    }),
    [t],
  );

  const selectedKeys = React.useMemo(() => {
    const hit = selectedKey(pathname);
    return hit ? [hit] : [];
  }, [pathname]);

  const { token } = theme.useToken();
  // Ant Design 6 derives component transitions from its fast/mid/slow duration
  // tokens, so setting them here is the only place the console needs to change
  // to honour the motion preference, including `prefers-reduced-motion`.
  const motion = useAdminMotion();
  const durations = motionTokens(motion.effective);

  const toggleNavigation = React.useCallback(() => {
    setCollapsed((value) => !value);
  }, []);

  const brand = React.useCallback(
    () => (
      <Link
        to="/"
        aria-label="SoyMutDB"
        onClick={() => setCollapsed(!isDesktop)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: token.marginXS,
          overflow: "hidden",
          whiteSpace: "nowrap",
          justifyContent: collapsed && isDesktop ? "center" : "flex-start",
        }}
      >
        <span
          aria-hidden
          style={{
            flex: "0 0 auto",
            width: 28,
            height: 28,
            borderRadius: 6,
            background: token.colorPrimary,
            color: token.colorTextLightSolid,
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
            fontSize: 15,
          }}
        >
          S
        </span>
        {collapsed && isDesktop ? null : (
          <span style={{ fontWeight: 600, fontSize: 16, lineHeight: 1 }}>SoyMutDB</span>
        )}
      </Link>
    ),
    [collapsed, isDesktop, token.marginXS, token.colorPrimary, token.colorTextLightSolid],
  );

  return (
    <ConfigProvider
      theme={{
        token: {
          motionDurationFast: `${durations.fast}s`,
          motionDurationMid: `${durations.mid}s`,
          motionDurationSlow: `${durations.slow}s`,
        },
      }}
    >
      <div data-motion={motion.effective} style={{ minHeight: "100vh" }}>
        <a className="admin-skip-link" href="#admin-main-content">
          {t("admin.shell.skipToContent", { defaultValue: "Skip to main content" })}
        </a>
        <ProLayout
          layout="side"
          title="SoyMutDB"
          logo={false}
          siderWidth={232}
          collapsed={collapsed}
          onCollapse={setCollapsed}
          location={{ pathname }}
          route={route}
          menu={{ type: "group" }}
          menuDataRender={() => menuData}
          selectedKeys={selectedKeys}
          headerRender={false}
          footerRender={false}
          contentStyle={{ padding: 0 }}
          menuHeaderRender={() => brand()}
          menuItemRender={(item, dom) =>
            item.path && !item.children ? (
              <Link
                to={item.path}
                onClick={() => setCollapsed(!isDesktop)}
                aria-current={selectedKeys.includes(item.path) ? "page" : undefined}
              >
                {dom}
              </Link>
            ) : (
              dom
            )
          }
        >
          <div
            id="admin-main-content"
            tabIndex={-1}
            style={{
              padding: isDesktop ? token.paddingLG : token.paddingMD,
              minHeight: "100vh",
              minWidth: 0,
            }}
          >
            {typeof children === "function" ? children(toggleNavigation) : children}
          </div>
        </ProLayout>
      </div>
    </ConfigProvider>
  );
}