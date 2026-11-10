
/**
 * SiteHeader — sticky top navigation with logo, grouped dropdown primary nav,
 * search trigger, language switch, theme toggle, animation control, and auth
 * menu.
 *
 * Ant Design is the only UI library used here (`@/lib/antd` + `@ant-design/icons`).
 *
 * Features:
 * - Scroll-reactive backdrop blur / shadow (RAF-throttled)
 * - Two-level primary nav: Search / Tools / Downloads / Resources.
 *   Search, Tools and Resources open dropdown panels (the "secondary menu");
 *   Downloads is a single direct link (no dropdown).
 * - Animated underline on active nav links
 * - Cmd+K quick search trigger
 * - Smooth mobile drawer with a sectioned two-level menu
 */
import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useRouterState, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { getSiteNavigation } from "@soymutdb/api-client";
import { useSiteContent } from "../lib/site-content-react";
import { IS_INTERNAL_SITE, SITE_VARIANT } from "../lib/site-variant";
import {
  brandWordmarkParts,
  databaseKindLabelKey,
  useSiteIdentity,
} from "../lib/site-identity";
import { safeExternalUrl } from "../lib/url-safety";
import {
  SearchOutlined,
  MenuOutlined,
  CloseOutlined,
  SunOutlined,
  MoonOutlined,
  GlobalOutlined,
  DownOutlined,
  DeploymentUnitOutlined,
} from "@ant-design/icons";
import { cn } from "../lib/cn";
import { Affix, Button, Input, Menu } from "@/lib/antd";
// Per-component deep imports: the package root also imports antd-mobile's
// global stylesheet, which would override the site's html/body font, link
// colours and background. The component entry points only pull their own
// `.adm-*`-scoped CSS.
import Popup from "antd-mobile/es/components/popup";
import NavBar from "antd-mobile/es/components/nav-bar";
import { useTheme } from "../lib/theme-provider";
import { useI18n, type SupportedLanguage } from "../lib/i18n";

/** True at the AntD/Tailwind `lg` breakpoint (>=1024px). */
function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = React.useState(
    () => typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches,
  );
  React.useEffect(() => {
    const mql = window.matchMedia("(min-width: 1024px)");
    const onChange = (e: MediaQueryListEvent) => setIsDesktop(e.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return isDesktop;
}

type NavChild =
  | { kind: "link"; href: string; target: "internal" | "external"; labelKey?: string; labelEn?: string; labelZh?: string }
  | { kind: "separator" };

interface NavGroupDef {
  key: string;
  labelKey: string;
  labelEn?: string;
  labelZh?: string;
  /** Direct link (rendered as a flat top-level item, no dropdown). */
  to?: string;
  toTarget?: "internal" | "external";
  /** Dropdown children (the secondary menu). */
  children?: NavChild[];
}

/**
 * Two-level primary navigation.
 *
 * Explore / Tools / Resources open a dropdown ("secondary menu"); Downloads is a
 * direct top-level link. This replaces the previous single row of flat items
 * and the footer link map (the footer nav is no longer rendered).
 */
const NAV_GROUPS: ReadonlyArray<NavGroupDef> = [
  {
    key: "search",
    labelKey: "nav.search",
    // The four search entries kept per the operator's reference (Gene ID /
    // Physical Location / JBrowse 2 / BLAST). The routes that used to live in
    // this group (variants / mutants / browser / SRA / compare / analytics)
    // remain reachable by direct URL as optional features.
    children: [
      { kind: "link", href: "/search/genes", target: "internal", labelKey: "search.tabGenes" },
      { kind: "link", href: "/search/location", target: "internal", labelKey: "search.tabLocation" },
      { kind: "link", href: "/search/gbrowse", target: "internal", labelKey: "search.tabGbrowse" },
      { kind: "link", href: "/blast", target: "internal", labelKey: "nav.blast" },
    ],
  },
  {
    key: "tools",
    labelKey: "nav.tools",
    children: [
      { kind: "link", href: "/blast", target: "internal", labelKey: "nav.blast" },
      { kind: "link", href: "/comparative", target: "internal", labelKey: "nav.comparative" },
      { kind: "separator" },
      { kind: "link", href: "/tools/seqfetch", target: "internal", labelKey: "tools.seqfetch.title" },
      { kind: "link", href: "/tools/enrichment", target: "internal", labelKey: "tools.enrichment.title" },
      { kind: "link", href: "/tools/exppattern", target: "internal", labelKey: "tools.exppattern.title" },
      { kind: "separator" },
      // Data browsers (not tools with a form): released expression libraries
      // and recorded phenotype observations.
      { kind: "link", href: "/expression", target: "internal", labelKey: "nav.expression" },
      { kind: "link", href: "/phenotypes", target: "internal", labelKey: "nav.phenotypes" },
      { kind: "separator" },
      { kind: "link", href: "/tools", target: "internal", labelKey: "nav.allTools" },
    ],
  },
  {
    key: "downloads",
    labelKey: "nav.downloads",
    to: "/downloads",
    toTarget: "internal",
  },
  {
    key: "resources",
    labelKey: "nav.resources",
    children: [
      { kind: "link", href: "/guide", target: "internal", labelKey: "nav.guide" },
      { kind: "link", href: "/help", target: "internal", labelKey: "nav.help" },
      { kind: "link", href: "/news", target: "internal", labelKey: "nav.news" },
      { kind: "link", href: "/publications", target: "internal", labelKey: "nav.publications" },
      { kind: "link", href: "/seed-request", target: "internal", labelKey: "nav.seedRequest" },
      { kind: "link", href: "/about", target: "internal", labelKey: "nav.about" },
    ],
  },
];

const STATIC_NAV_GROUPS: NavGroupDef[] = NAV_GROUPS.map((group) => ({ ...group }));

/**
 * Project the admin-managed `/site/navigation` document into the same shape the
 * static definition uses. A group with one link whose label equals the group
 * title (the Downloads default) stays a direct top-level link; anything else
 * opens a dropdown so operator-added links stay reachable.
 */
function toNavGroups(
  groups: ReadonlyArray<{
    id: string;
    title_en: string;
    title_zh: string;
    enabled: boolean;
    order: number;
    links: ReadonlyArray<{
      id: string;
      label_en: string;
      label_zh: string;
      target: "internal" | "external";
      href: string;
      enabled: boolean;
      order: number;
    }>;
  }>,
): NavGroupDef[] {
  return groups
    .filter((group) => group.enabled)
    .sort((a, b) => a.order - b.order || a.id.localeCompare(b.id))
    .map((group): NavGroupDef => {
      const links = group.links
        .filter((link) => link.enabled)
        .sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
      const first = links[0];
      const singleDirect =
        links.length === 1 &&
        first !== undefined &&
        first.label_en.trim().toLowerCase() === group.title_en.trim().toLowerCase();
      return {
        key: group.id,
        labelKey: group.id,
        labelEn: group.title_en,
        labelZh: group.title_zh,
        ...(singleDirect && first
          ? { to: first.href, toTarget: first.target }
          : {
              children: links.map(
                (link): NavChild => ({
                  kind: "link",
                  href: link.href,
                  target: link.target,
                  labelEn: link.label_en,
                  labelZh: link.label_zh,
                }),
              ),
            }),
      };
    })
    .filter((group) => group.to !== undefined || (group.children ?? []).length > 0);
}

function usePrimaryNavigation(): NavGroupDef[] {
  const navigation = useQuery({
    queryKey: ["site-navigation", SITE_VARIANT],
    queryFn: () => getSiteNavigation(SITE_VARIANT),
    staleTime: 60_000,
    retry: false,
  });
  return React.useMemo(
    () => (navigation.data ? toNavGroups(navigation.data.groups) : STATIC_NAV_GROUPS),
    [navigation.data],
  );
}

export function SiteHeader() {
  const { t } = useTranslation();
  const { get } = useSiteContent();
  const navigate = useNavigate();
  const routerState = useRouterState();
  const currentPath = routerState.location.pathname;
  const { theme, toggleTheme } = useTheme();
  const { currentLanguage, changeLanguage } = useI18n();
  const isDesktop = useIsDesktop();
  const navGroups = usePrimaryNavigation();
  const { branding, databaseKind } = useSiteIdentity();
  const isZh = currentLanguage.toLowerCase().startsWith("zh");
  const brandName = (
    isZh
      ? branding?.name_zh || branding?.name_en
      : branding?.name_en || branding?.name_zh
  )?.trim();
  const brandIcon = safeExternalUrl(branding?.icon_url);
  const wordmark = brandName ? brandWordmarkParts(brandName) : null;
  const kindKey = databaseKindLabelKey(databaseKind);
  const navLabel = (entry: { labelEn?: string; labelZh?: string; labelKey?: string }): string => {
    if (entry.labelEn || entry.labelZh) {
      return (
        (currentLanguage.toLowerCase().startsWith("zh")
          ? entry.labelZh || entry.labelEn
          : entry.labelEn || entry.labelZh) ?? ""
      );
    }
    return entry.labelKey ? get(entry.labelKey, t(entry.labelKey)) : "";
  };
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [openMenu, setOpenMenu] = React.useState<string | null>(null);
  const [langOpen, setLangOpen] = React.useState(false);
  const [scrolled, setScrolled] = React.useState(false);
  const [searchValue, setSearchValue] = React.useState("");
  const headerRef = React.useRef<HTMLElement | null>(null);
  const navRef = React.useRef<HTMLElement | null>(null);
  const menuButtonRef = React.useRef<HTMLButtonElement | null>(null);

  // Scroll-reactive header: RAF-throttled for 60fps
  React.useEffect(() => {
    let rafId = 0;
    const onScroll = () => {
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        setScrolled(window.scrollY > 8);
        rafId = 0;
      });
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, []);

  // Close the mobile menu and any open dropdown on route change
  React.useEffect(() => {
    setMobileOpen(false);
    setOpenMenu(null);
  }, [currentPath]);

  // The drawer has no reason to stay open once the desktop nav is available.
  React.useEffect(() => {
    if (isDesktop) setMobileOpen(false);
  }, [isDesktop]);

  const closeMobileMenu = React.useCallback(() => {
    setMobileOpen(false);
    // Return focus to the toggle when the drawer is dismissed explicitly
    // (mask, close button, Escape); the popup portal unmounts after the
    // closing animation and would otherwise drop focus to <body>.
    menuButtonRef.current?.focus();
  }, []);

  // Escape closes the mobile menu / dropdown and returns focus to the toggle
  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (mobileOpen) {
        closeMobileMenu();
      } else if (openMenu) {
        setOpenMenu(null);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen, openMenu, closeMobileMenu]);

  // Close an open dropdown when clicking outside the desktop nav
  React.useEffect(() => {
    if (!openMenu) return;
    const onPointerDown = (e: PointerEvent) => {
      if (navRef.current && !navRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [openMenu]);

  // Move focus into the drawer once it is in the DOM. The popup mounts its
  // portal content in a follow-up render, so the drawer can still be missing
  // when this effect first runs; retry on the next frame instead of dropping
  // focus to <body>.
  React.useEffect(() => {
    if (!mobileOpen) return;
    let raf = 0;
    const focusFirstLink = () => {
      const firstLink = document.querySelector<HTMLAnchorElement>("#mobile-nav a");
      if (firstLink) {
        firstLink.focus();
        return;
      }
      raf = requestAnimationFrame(focusFirstLink);
    };
    focusFirstLink();
    return () => cancelAnimationFrame(raf);
  }, [mobileOpen]);

  const onSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = searchValue.trim();
    if (!q) return;
    // Only the parameters /search declares are sent: tissue/treatment/
    // min_fpkm were silently discarded by the route validator.
    navigate({ to: "/search", search: { q } });
    setMobileOpen(false);
    setSearchValue("");
  };

  // Open command palette via Cmd+K is handled globally by CommandPalette;
  // this button is a visible affordance.
  const openPalette = () => {
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }),
    );
  };

  const isRouteActive = (to: string): boolean =>
    currentPath === to || (to !== "/" && currentPath.startsWith(to));

  const isGroupActive = (group: NavGroupDef): boolean => {
    if (group.to) return isRouteActive(group.to);
    return (group.children ?? []).some(
      (child) => child.kind === "link" && isRouteActive(child.href),
    );
  };

  const header = (
    <header
      ref={headerRef}
      className={cn(
        "sticky top-0 z-40 border-b transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
        "border-border/[var(--header-border-opacity)]",
        "bg-background/[var(--header-bg-opacity)]",
        "backdrop-blur-[length:var(--header-blur)] backdrop-saturate-150",
        "shadow-[0_1px_var(--header-shadow-opacity,0)_oklch(0_0_0/0.06)]",
        scrolled && "site-header--scrolled",
      )}
    >
      <div className="container-prose flex h-16 items-center gap-2 sm:gap-4">
        {/* Logo */}
        <Link
          to="/"
          className="flex min-h-11 shrink-0 items-center gap-2 rounded-md outline-none transition-opacity hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={t("common.home")}
        >
          {brandIcon ? (
            <img
              src={brandIcon}
              alt=""
              aria-hidden
              className="size-8 rounded-lg object-contain"
            />
          ) : (
            <span className="flex size-8 items-center justify-center rounded-lg bg-gradient-to-br from-[var(--primary-gradient-start)] to-[var(--primary-gradient-end)] text-primary-foreground shadow-sm">
              <DeploymentUnitOutlined className="size-5" aria-hidden />
            </span>
          )}
          <span className="font-display text-lg font-semibold tracking-tight">
            {wordmark ? (
              <>
                {wordmark.before}
                {wordmark.accent ? <span className="text-gradient">{wordmark.accent}</span> : null}
                {wordmark.after}
              </>
            ) : (
              <>
                {t("brand.soy")}
                <span className="text-gradient">{t("brand.mut")}</span>
                {t("brand.db")}
              </>
            )}
          </span>
          {kindKey ? (
            <span
              className="hidden rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-primary sm:inline-block"
              title={t(kindKey)}
            >
              {t(kindKey)}
            </span>
          ) : null}
          {IS_INTERNAL_SITE ? (
            <span
              className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-amber-700 dark:text-amber-300"
              title={t("site.internalBadgeTitle")}
            >
              {t("site.internalBadge")}
            </span>
          ) : null}
        </Link>

        {/* Desktop grouped nav — two-level dropdown menu */}
        <nav
          ref={navRef}
          className="mx-auto hidden items-center gap-1 lg:flex"
          aria-label={t("nav.primaryLabel")}
        >
          {navGroups.map((group) => {
            if (group.to) {
              const label = navLabel(group);
              const directClass = cn(
                "nav-link whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                isRouteActive(group.to)
                  ? "text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              );
              if (group.toTarget === "external") {
                return (
                  <a
                    key={group.key}
                    href={group.to}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-active={isRouteActive(group.to)}
                    className={directClass}
                  >
                    {label}
                  </a>
                );
              }
              return (
                <Link
                  key={group.key}
                  to={group.to}
                  data-active={isRouteActive(group.to)}
                  className={directClass}
                >
                  {label}
                </Link>
              );
            }

            const active = isGroupActive(group);
            const open = openMenu === group.key;
            const activeChild = (group.children ?? []).find(
              (child) => child.kind !== "separator" && isRouteActive(child.href),
            );
            // antd's `Dropdown` was tried here first and could not be used: its
            // portal + open-state handling rebuilt the panel on mousedown, so the
            // `click` never reached a menu item and every navigation was
            // silently dropped. Rendering antd's `Menu` directly keeps the
            // component native while leaving open/close under our control.
            return (
              <div key={group.key} className="relative">
                <Button
                  type="text"
                  data-active={active}
                  aria-haspopup="menu"
                  aria-expanded={open}
                  onClick={() => setOpenMenu(open ? null : group.key)}
                  // No `px-3 py-2` here: antd injects `.ant-btn` padding at
                  // runtime into the unlayered cascade, which outranks every
                  // Tailwind utility, so such a class is a silent no-op on this
                  // element (the `<Link>` sibling above is a plain <a> and keeps
                  // its own). Detected by
                  // .validation/probe/audit-antd-spacing.mjs.
                  className={cn(
                    "nav-link flex items-center gap-1 whitespace-nowrap rounded-md text-sm font-medium",
                    active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {navLabel(group)}
                  <DownOutlined
                    className={cn("size-3.5 transition-transform", open && "rotate-180")}
                    aria-hidden
                  />
                </Button>
                {open ? (
                  // The panel chrome (border / radius / shadow) lives on this
                  // wrapper: antd's `ant-menu-vertical` styles outrank a
                  // Tailwind utility on the Menu itself, which flattened the
                  // shadow and left the right border nearly transparent.
                  //
                  // That same specificity rule is why the Menu also carries an
                  // inline `border: 0`: `.ant-menu-vertical` sets
                  // `border-inline-end`, and a Tailwind `border-0` class loses to
                  // it, so the panel drew a second vertical rule inside its own
                  // outline. An inline style is the only thing that outranks the
                  // injected stylesheet here.
                  <div className="absolute left-1/2 top-full z-50 mt-2 w-60 -translate-x-1/2 rounded-xl border bg-popover p-1.5 shadow-lg">
                    <Menu
                      mode="vertical"
                      style={{ border: 0 }}
                      className="bg-transparent"
                      selectedKeys={activeChild && activeChild.kind !== "separator" ? [activeChild.href] : []}
                      items={(group.children ?? []).map((child, i) =>
                        child.kind === "separator"
                          ? { type: "divider" as const, key: `sep-${group.key}-${i}` }
                          : { key: child.href, label: navLabel(child) },
                      )}
                      onClick={({ key }) => {
                        const target = (group.children ?? []).find(
                          (child) => child.kind !== "separator" && child.href === key,
                        );
                        setOpenMenu(null);
                        if (!target || target.kind === "separator") return;
                        if (target.target === "external") {
                          window.open(target.href, "_blank", "noopener,noreferrer");
                        } else {
                          void navigate({ to: target.href });
                        }
                      }}
                    />
                  </div>
                ) : null}
              </div>
            );
          })}
        </nav>

        {/* Keep responsive visibility on a plain wrapper: AntD's unlayered
            Button display rule takes precedence over Tailwind utilities. */}
        <div className="ml-auto flex shrink-0 items-center gap-1 md:ml-2">
          <div className="hidden md:block">
            <Button
              onClick={openPalette}
              aria-label={t("nav.quickSearchLabel")}
              className="site-header-search"
            >
              <SearchOutlined className="size-4 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1 truncate text-left">
                {t("nav.searchPlaceholder")}
              </span>
              <kbd className="shrink-0 text-xs" aria-hidden>Ctrl K</kbd>
            </Button>
          </div>
          <LanguageSwitcher
            open={langOpen}
            setOpen={setLangOpen}
            current={currentLanguage as SupportedLanguage}
            onChange={changeLanguage}
          />
          <Button
            type="text"
            size="small"
            className="site-header-control"
            aria-label={t("nav.theme")}
            onClick={toggleTheme}
            icon={theme === "dark" ? <SunOutlined /> : <MoonOutlined />}
          />

          {/* Mobile menu toggle — below the lg breakpoint only. The rule lives
              on a wrapper on purpose: antd's own Button `display` rule outranks
              a Tailwind utility applied to the same element, so `lg:hidden` on
              the Button itself never took effect and the icon stayed visible on
              desktop next to the full navigation. */}
          <div className="lg:hidden">
            <Button
              ref={menuButtonRef}
              type="text"
              size="small"
              className="site-header-control"
              aria-label={mobileOpen ? t("nav.closeMenu") : t("nav.openMenu")}
              aria-expanded={mobileOpen}
              aria-controls="mobile-nav"
              onClick={() => setMobileOpen((v) => !v)}
              icon={mobileOpen ? <CloseOutlined /> : <MenuOutlined />}
            />
          </div>
        </div>
      </div>

      {/* Mobile drawer — antd-mobile Popup + NavBar shell around the same
          sectioned two-level menu as before. The popup portals to <body>, so
          it is not clipped by the sticky header's backdrop-filter containing
          block. */}
      <Popup
        visible={mobileOpen}
        position="right"
        onMaskClick={closeMobileMenu}
        onClose={closeMobileMenu}
        destroyOnClose
        bodyStyle={{
          width: "min(88vw, 384px)",
          height: "100dvh",
          backgroundColor: "var(--background)",
          color: "var(--foreground)",
        }}
      >
        <div
          id="mobile-nav"
          role="dialog"
          aria-modal="true"
          aria-label={t("nav.mobileNavigation")}
          className="flex h-full flex-col"
        >
          <NavBar
            back={null}
            className="shrink-0"
            style={
              {
                "--height": "56px",
                "--border-bottom": "1px solid var(--border)",
              } as React.CSSProperties
            }
            right={
              <button
                type="button"
                onClick={closeMobileMenu}
                aria-label={t("nav.closeMenu")}
                className="flex size-10 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <CloseOutlined aria-hidden />
              </button>
            }
          >
            {t("nav.mobileNavigation")}
          </NavBar>

          <div className="flex-1 overflow-y-auto overscroll-contain pb-[env(safe-area-inset-bottom)]">
            <div className="flex flex-col px-4 py-5">
            <form onSubmit={onSearchSubmit} role="search" className="mb-5 md:hidden">
              <Input
                allowClear
                type="search"
                value={searchValue}
                onChange={(e) => setSearchValue(e.target.value)}
                placeholder={t("home.searchPlaceholder")}
                aria-label={t("nav.search")}
                prefix={<SearchOutlined aria-hidden />}
              />
            </form>

            {/* Sectioned two-level nav (mirrors the desktop groups) */}
            <nav aria-label={t("nav.primaryLabel")} className="flex flex-col">
              {navGroups.map((group) => {
                if (group.to) {
                  const label = navLabel(group);
                  const directClass = cn(
                    "flex items-center rounded-xl px-4 py-3 text-[15px] font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                    isRouteActive(group.to)
                      ? "bg-primary/10 text-primary"
                      : "text-foreground/80 hover:bg-accent",
                  );
                  if (group.toTarget === "external") {
                    return (
                      <a
                        key={group.key}
                        href={group.to}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={closeMobileMenu}
                        className={directClass}
                      >
                        {label}
                      </a>
                    );
                  }
                  return (
                    <Link
                      key={group.key}
                      to={group.to}
                      onClick={closeMobileMenu}
                      className={directClass}
                    >
                      {label}
                    </Link>
                  );
                }

                return (
                  <div key={group.key} className="mt-5 first:mt-0">
                    <p className="px-1 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
                      {navLabel(group)}
                    </p>
                    <div className="flex flex-col">
                      {(group.children ?? []).map((child, i) =>
                        child.kind === "separator" ? (
                          <div key={`sep-${group.key}-${i}`} className="my-1 h-px bg-border" aria-hidden />
                        ) : child.target === "external" ? (
                          <a
                            key={child.href}
                            href={child.href}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={closeMobileMenu}
                            className="flex items-center rounded-xl px-4 py-3 text-[15px] font-medium text-foreground/80 outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            {navLabel(child)}
                          </a>
                        ) : (
                          <Link
                            key={child.href}
                            to={child.href}
                            onClick={closeMobileMenu}
                            className={cn(
                              "flex items-center rounded-xl px-4 py-3 text-[15px] font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                              isRouteActive(child.href)
                                ? "bg-primary/10 text-primary"
                                : "text-foreground/80 hover:bg-accent",
                            )}
                          >
                            {navLabel(child)}
                          </Link>
                        ),
                      )}
                    </div>
                  </div>
                );
              })}
            </nav>
            </div>
          </div>
        </div>
      </Popup>
    </header>
  );

  // Desktop: AntD Affix pins the header (offsetTop=0, placeholder keeps the
  // layout stable). Mobile: the plain CSS-sticky header keeps the existing
  // drawer behavior untouched.
  return isDesktop ? <Affix offsetTop={0}>{header}</Affix> : header;
}

function LanguageSwitcher({
  open,
  setOpen,
  current,
  onChange,
}: {
  open: boolean;
  setOpen: (v: boolean) => void;
  current: SupportedLanguage;
  onChange: (lang: SupportedLanguage) => void;
}) {
  const { t } = useTranslation();
  const ref = React.useRef<HTMLDivElement | null>(null);
  // Outside-click dismissal, which antd's `Dropdown` would otherwise provide.
  React.useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open, setOpen]);

  const languages: ReadonlyArray<{ code: SupportedLanguage; label: string }> = [
    { code: "en", label: "English" },
    { code: "zh", label: "中文" },
  ];

  // Same reasoning as the primary nav: antd's `Dropdown` dropped the menu-item
  // click, so antd's `Menu` is rendered directly and dismissal is handled here.
  return (
    <div className="relative" ref={ref}>
      <Button
        type="text"
        size="small"
        className="site-header-control"
        aria-label={t("nav.language")}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        icon={<GlobalOutlined />}
      />
      {open ? (
        <div className="absolute right-0 top-full z-50 mt-2 w-36 rounded-xl border bg-popover p-1.5 shadow-lg">
          <Menu
            mode="vertical"
            className="border-0 bg-transparent"
            selectedKeys={[current]}
            items={languages.map((lang) => ({ key: lang.code, label: lang.label }))}
            onClick={({ key }) => {
              onChange(key as SupportedLanguage);
              setOpen(false);
            }}
          />
        </div>
      ) : null}
    </div>
  );
}
