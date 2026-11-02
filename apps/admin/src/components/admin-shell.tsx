import { MenuFoldOutlined, MenuUnfoldOutlined } from "@ant-design/icons";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { ConfigProvider, Drawer, Grid, Layout, Menu, theme } from "../lib/antd";
import { motionTokens } from "@soymutdb/ui-react";
import { useAdminMotion } from "../lib/motion-preference";
import { Link, useRouterState } from "@tanstack/react-router";
import { NAV_SECTIONS } from "./admin-sidebar";

const { Sider, Content } = Layout;
const { useBreakpoint } = Grid;

/**
 * Admin shell built from native Ant Design 6 components.
 *
 * This replaced `ProLayout`, whose 7.x package declares
 * `peerDependencies: { antd: "^4.24.15 || ^5.11.2" }`. The workspace pins antd
 * 6.6.5, so pnpm installed a second, private `antd@4.24.16` copy to satisfy
 * ProLayout alone. Two Ant Design runtimes then shared one DOM while each kept
 * its own CSS-in-JS cache and `ConfigProvider` context, so theme tokens, locale,
 * motion and dark mode never reached the sider. Restyling it could not have
 * fixed that; using antd 6 directly removes the duplicate runtime.
 *
 * `NAV_SECTIONS` stays the one navigation source of truth — it is what the
 * reachability and render regression tests assert against. The previous shell
 * flattened those sections with `flatMap`, which is why every destination
 * rendered as one flat list with no group headings.
 */
export function AdminShell({ children }: {
  children: React.ReactNode | ((toggleNavigation: () => void) => React.ReactNode);
}) {
  const { t } = useTranslation();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const screens = useBreakpoint();
  const [collapsed, setCollapsed] = React.useState(false);
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const isDesktop = screens.lg ?? true;

  // `/` must not prefix-match every route, so it is matched exactly.
  const selectedKeys = React.useMemo(() => {
    const hit = NAV_SECTIONS.flatMap((s) => s.items)
      .filter((item) => item.path === "/" ? pathname === "/" :
        pathname === item.path || pathname.startsWith(`${item.path}/`))
      .sort((a, b) => b.path.length - a.path.length)[0];
    return hit ? [hit.path] : [];
  }, [pathname]);

  const menuItems = React.useMemo(
    () =>
      NAV_SECTIONS.map((section) => ({
        key: t(section.labelKey, { defaultValue: section.label }),
        label: t(section.labelKey, { defaultValue: section.label }),
        type: "group" as const,
        children: section.items.map((item) => ({
          key: item.path,
          icon: React.createElement(item.icon),
          label: (
            <Link
              to={item.path}
              onClick={() => setMobileOpen(false)}
              aria-current={selectedKeys.includes(item.path) ? "page" : undefined}
            >
              {t(item.labelKey, { defaultValue: item.label })}
            </Link>
          ),
        })),
      })),
    [selectedKeys, t],
  );

  const { token } = theme.useToken();
  // Ant Design 6 derives component transitions from its fast/mid/slow duration
  // tokens, so setting them here is the only place the console needs to change
  // to honour the motion preference, including `prefers-reduced-motion`.
  const motion = useAdminMotion();
  const durations = motionTokens(motion.effective);

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
    <Layout
      data-motion={motion.effective}
      style={{ minHeight: "100vh" }}
    >
      <a className="admin-skip-link" href="#admin-main-content">
        {t("admin.shell.skipToContent", { defaultValue: "Skip to main content" })}
      </a>
      {isDesktop ? (
      <Sider
        theme="light"
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        trigger={null}
        width={232}
        collapsedWidth={64}
        breakpoint="lg"
        style={{
          borderInlineEnd: `1px solid ${token.colorBorderSecondary}`,
          position: isDesktop ? "sticky" : undefined,
          top: 0,
          height: isDesktop ? "100vh" : undefined,
          overflow: "auto",
        }}
      >
        <Link
          to="/"
          aria-label="SoyMutDB"
          className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
          style={{
            display: "flex",
            alignItems: "center",
            gap: token.marginXS,
            height: 56,
            paddingInline: collapsed ? 0 : token.paddingMD,
            justifyContent: collapsed ? "center" : "flex-start",
            borderBlockEnd: `1px solid ${token.colorBorderSecondary}`,
            overflow: "hidden",
            whiteSpace: "nowrap",
          }}
        >
          {/* Decorative mark: the product name beside it already names the app,
              so the glyph is hidden from assistive tech. */}
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
          {!collapsed && (
            <span style={{ fontWeight: 600, fontSize: 16, lineHeight: 1 }}>SoyMutDB</span>
          )}
        </Link>

        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          aria-label={collapsed ? t("admin.shell.expandSidebar", { defaultValue: "Expand sidebar" }) : t("admin.shell.collapseSidebar", { defaultValue: "Collapse sidebar" })}
          aria-expanded={!collapsed}
          aria-controls="admin-navigation"
          title={collapsed ? t("admin.shell.expandSidebar", { defaultValue: "Expand sidebar" }) : t("admin.shell.collapseSidebar", { defaultValue: "Collapse sidebar" })}
          className="mx-auto flex h-11 w-[calc(100%-16px)] items-center justify-center rounded-md border-0 bg-transparent text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
          style={{
            marginBlock: token.marginXS,
            transitionDuration: `${durations.fast}s`,
            cursor: "pointer",
          }}
        >
          {collapsed ? <MenuUnfoldOutlined aria-hidden /> : <MenuFoldOutlined aria-hidden />}
        </button>

        <Menu
          id="admin-navigation"
          mode="inline"
          items={menuItems}
          selectedKeys={selectedKeys}
          style={{ borderInlineEnd: "none", paddingBlock: token.paddingXS }}
        />
      </Sider>
      ) : (
        <Drawer
          title="SoyMutDB"
          placement="left"
          open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          size="min(280px, calc(100vw - 32px))"
          styles={{ body: { padding: 0 } }}
        >
          <Menu
            mode="inline"
            items={menuItems}
            selectedKeys={selectedKeys}
            style={{ borderInlineEnd: "none", paddingBlock: token.paddingXS }}
          />
        </Drawer>
      )}

      <Layout style={{ minWidth: 0 }}>
        <Content
          id="admin-main-content"
          tabIndex={-1}
          style={{
            padding: isDesktop ? token.paddingLG : token.paddingMD,
            minHeight: "calc(100vh - 56px)",
            minWidth: 0,
          }}
        >
          {typeof children === "function"
            ? children(() => isDesktop ? setCollapsed((value) => !value) : setMobileOpen((value) => !value))
            : children}
        </Content>
      </Layout>
    </Layout>
    </ConfigProvider>
  );
}
