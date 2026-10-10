import { MenuFoldOutlined } from "@ant-design/icons";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { Grid, Layout, Menu, theme } from "../lib/antd";
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
export function AdminShell({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const screens = useBreakpoint();
  const [collapsed, setCollapsed] = React.useState(false);
  const isDesktop = screens.lg ?? true;

  // Open a group when the current page lives inside it, so a deep link never
  // lands on a route whose heading is folded away.
  const openKeys = React.useMemo(
    () =>
      NAV_SECTIONS.filter((section) =>
        section.items.some((item) => item.path !== "/" && pathname.startsWith(item.path)),
      ).map((section) => t(section.labelKey, { defaultValue: section.label })),
    [pathname, t],
  );

  const menuItems = React.useMemo(
    () =>
      NAV_SECTIONS.map((section) => ({
        key: t(section.labelKey, { defaultValue: section.label }),
        label: t(section.labelKey, { defaultValue: section.label }),
        type: "group" as const,
        children: section.items.map((item) => ({
          key: item.path,
          icon: React.createElement(item.icon),
          label: <Link to={item.path}>{t(item.labelKey, { defaultValue: item.label })}</Link>,
        })),
      })),
    [t],
  );

  // `/` must not prefix-match every route, so it is matched exactly.
  const selectedKeys = React.useMemo(() => {
    const hit = NAV_SECTIONS.flatMap((s) => s.items).find((item) =>
      item.path === "/" ? pathname === "/" : pathname.startsWith(item.path),
    );
    return hit ? [hit.path] : [];
  }, [pathname]);

  const { token } = theme.useToken();

  return (
    <Layout style={{ minHeight: "100vh" }}>
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
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: "100%",
            height: 40,
            border: 0,
            borderBlockStart: `1px solid ${token.colorBorderSecondary}`,
            background: "transparent",
            color: token.colorTextSecondary,
            cursor: "pointer",
          }}
        >
          <MenuFoldOutlined aria-hidden />
        </button>

        <Menu
          mode="inline"
          items={menuItems}
          selectedKeys={selectedKeys}
          defaultOpenKeys={openKeys}
          style={{ borderInlineEnd: "none", paddingBlock: token.paddingXS }}
        />
      </Sider>

      <Layout>
        <Content
          style={{
            padding: isDesktop ? token.paddingLG : token.paddingMD,
            minHeight: "calc(100vh - 56px)",
          }}
        >
          {children}
        </Content>
      </Layout>
    </Layout>
  );
}