
/**
 * SiteHeader — sticky top navigation with logo, grouped dropdown primary nav,
 * search trigger, language switch, theme toggle, animation control, and auth
 * menu.
 *
 * Ant Design is the only UI library used here (`@/lib/antd` + `@ant-design/icons`).
 *
 * Features:
 * - Scroll-reactive backdrop blur / shadow (RAF-throttled)
 * - Two-level primary nav: Explore / Tools / Downloads / Resources.
 *   Explore, Tools and Resources open dropdown panels (the "secondary menu");
 *   Downloads is a single direct link (no dropdown).
 * - Animated underline on active nav links
 * - Cmd+K quick search trigger
 * - Smooth mobile drawer with a sectioned two-level menu
 */
import * as React from "react";
import { Link, useRouterState, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useSiteContent } from "../lib/site-content";
import { IS_INTERNAL_SITE } from "../lib/site-variant";
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
import { Affix, Button, Input } from "@/lib/antd";
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
  | { kind: "link"; to: string; labelKey: string }
  | { kind: "separator" };

interface NavGroupDef {
  key: string;
  labelKey: string;
  /** Direct link (rendered as a flat top-level item, no dropdown). */
  to?: string;
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
    key: "explore",
    labelKey: "nav.explore",
    children: [
      { kind: "link", to: "/genes", labelKey: "nav.genes" },
      { kind: "link", to: "/variants", labelKey: "nav.variants" },
      { kind: "link", to: "/mutants", labelKey: "nav.mutantLines" },
      { kind: "link", to: "/browser", labelKey: "nav.browser" },
      { kind: "link", to: "/sra", labelKey: "nav.sra" },
      { kind: "link", to: "/compare", labelKey: "nav.compare" },
      { kind: "link", to: "/analytics", labelKey: "nav.analytics" },
    ],
  },
  {
    key: "tools",
    labelKey: "nav.tools",
    children: [
      { kind: "link", to: "/blast", labelKey: "nav.blast" },
      { kind: "link", to: "/analyses", labelKey: "nav.analyses" },
      { kind: "separator" },
      { kind: "link", to: "/tools/seqfetch", labelKey: "tools.seqfetch.title" },
      { kind: "link", to: "/tools/enrichment", labelKey: "tools.enrichment.title" },
      { kind: "link", to: "/tools/exppattern", labelKey: "tools.exppattern.title" },
      { kind: "separator" },
      { kind: "link", to: "/tools", labelKey: "nav.allTools" },
    ],
  },
  {
    key: "downloads",
    labelKey: "nav.downloads",
    to: "/downloads",
  },
  {
    key: "resources",
    labelKey: "nav.resources",
    children: [
      { kind: "link", to: "/guide", labelKey: "nav.guide" },
      { kind: "link", to: "/help", labelKey: "nav.help" },
      { kind: "link", to: "/news", labelKey: "nav.news" },
      { kind: "link", to: "/publications", labelKey: "nav.publications" },
      { kind: "link", to: "/seed-request", labelKey: "nav.seedRequest" },
      { kind: "link", to: "/about", labelKey: "nav.about" },
    ],
  },
];

export function SiteHeader() {
  const { t } = useTranslation();
  const { get } = useSiteContent();
  const navigate = useNavigate();
  const routerState = useRouterState();
  const currentPath = routerState.location.pathname;
  const { theme, toggleTheme } = useTheme();
  const { currentLanguage, changeLanguage } = useI18n();
  const isDesktop = useIsDesktop();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [openMenu, setOpenMenu] = React.useState<string | null>(null);
  const [langOpen, setLangOpen] = React.useState(false);
  const [scrolled, setScrolled] = React.useState(false);
  const [searchValue, setSearchValue] = React.useState("");
  const headerRef = React.useRef<HTMLElement | null>(null);
  const navRef = React.useRef<HTMLElement | null>(null);
  const menuButtonRef = React.useRef<HTMLButtonElement | null>(null);
  const firstMobileLinkRef = React.useRef<HTMLAnchorElement | null>(null);

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

  // Escape closes the mobile menu / dropdown and returns focus to the toggle
  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (mobileOpen) {
        setMobileOpen(false);
        menuButtonRef.current?.focus();
      } else if (openMenu) {
        setOpenMenu(null);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen, openMenu]);

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

  // Focus the first link when the mobile menu opens
  React.useEffect(() => {
    if (mobileOpen) firstMobileLinkRef.current?.focus();
  }, [mobileOpen]);

  const onSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = searchValue.trim();
    if (!q) return;
    navigate({ to: "/search", search: { q, tissue: "", treatment: "", min_fpkm: undefined } });
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
      (child) => child.kind === "link" && isRouteActive(child.to),
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
      <div className="container-prose flex h-16 items-center gap-4">
        {/* Logo */}
        <Link
          to="/"
          className="flex shrink-0 items-center gap-2 rounded-md outline-none transition-opacity hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="SoyMutDB home"
        >
          <span className="flex size-8 items-center justify-center rounded-lg bg-gradient-to-br from-[var(--primary-gradient-start)] to-[var(--primary-gradient-end)] text-primary-foreground shadow-sm">
            <DeploymentUnitOutlined className="size-5" aria-hidden />
          </span>
          <span className="font-display text-lg font-semibold tracking-tight">
            Soy<span className="text-gradient">Mut</span>DB
          </span>
          {IS_INTERNAL_SITE ? (
            <span
              className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-amber-700 dark:text-amber-300"
              title="Private internal site artifact"
            >
              Internal
            </span>
          ) : null}
        </Link>

        {/* Desktop grouped nav — two-level dropdown menu */}
        <nav
          ref={navRef}
          className="mx-auto hidden items-center gap-1 lg:flex"
          aria-label="Primary"
        >
          {NAV_GROUPS.map((group) => {
            if (group.to) {
              return (
                <Link
                  key={group.key}
                  to={group.to}
                  data-active={isRouteActive(group.to)}
                  className={cn(
                    "nav-link whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                    isRouteActive(group.to)
                      ? "text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {get(group.labelKey, t(group.labelKey))}
                </Link>
              );
            }

            const active = isGroupActive(group);
            const open = openMenu === group.key;
            return (
              <div key={group.key} className="relative">
                <button
                  type="button"
                  data-active={active}
                  aria-haspopup="menu"
                  aria-expanded={open}
                  onClick={() => setOpenMenu(open ? null : group.key)}
                  className={cn(
                    "nav-link flex items-center gap-1 whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                    active
                      ? "text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {get(group.labelKey, t(group.labelKey))}
                  <DownOutlined
                    className={cn("size-3.5 transition-transform", open && "rotate-180")}
                    aria-hidden
                  />
                </button>
                {open ? (
                  <div
                    role="menu"
                    className="absolute left-1/2 top-full z-50 mt-2 w-60 -translate-x-1/2 rounded-xl border bg-popover p-1.5 shadow-lg"
                    style={{ animation: "fade-down 160ms cubic-bezier(0.16,1,0.3,1)" }}
                  >
                    {(group.children ?? []).map((child, i) =>
                      child.kind === "separator" ? (
                        <div key={`sep-${group.key}-${i}`} className="my-1 h-px bg-border" aria-hidden />
                      ) : (
                        <Link
                          key={child.to}
                          to={child.to}
                          role="menuitem"
                          onClick={() => setOpenMenu(null)}
                          className={cn(
                            "block rounded-lg px-3 py-2 text-sm text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring",
                            isRouteActive(child.to) && "bg-accent/60 font-medium text-foreground",
                          )}
                        >
                          {get(child.labelKey, t(child.labelKey))}
                        </Link>
                      ),
                    )}
                  </div>
                ) : null}
              </div>
            );
          })}
        </nav>

        {/* Right cluster */}
        <div className="ml-auto flex items-center gap-1 md:ml-2">
          {/* Search (desktop) — triggers command palette */}
          <button
            type="button"
            onClick={openPalette}
            className="hidden h-9 items-center gap-2.5 rounded-lg border border-input/70 bg-muted/40 px-3 text-sm text-muted-foreground shadow-sm outline-none transition-colors hover:border-border hover:bg-muted/70 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:flex md:w-44 lg:w-56"
            aria-label="Quick search (Cmd+K)"
          >
            <SearchOutlined className="size-4 shrink-0" aria-hidden />
            <span className="min-w-0 flex-1 truncate text-left">
              <span className="hidden lg:inline">{t("home.searchPlaceholder")}</span>
              <span className="lg:hidden">Search…</span>
            </span>
            <span className="ml-auto flex shrink-0 items-center gap-1" aria-hidden>
              <kbd className="hidden sm:inline-flex">⌘</kbd>
              <kbd className="hidden sm:inline-flex">K</kbd>
            </span>
          </button>
          <LanguageSwitcher
            open={langOpen}
            setOpen={setLangOpen}
            current={currentLanguage as SupportedLanguage}
            onChange={changeLanguage}
          />
          <Button
            type="text"
            aria-label={t("nav.theme")}
            onClick={toggleTheme}
            icon={theme === "dark" ? <SunOutlined /> : <MoonOutlined />}
          />

          {/* Mobile menu toggle */}
          <Button
            type="text"
            className="lg:hidden"
            aria-label={mobileOpen ? "Close menu" : "Open menu"}
            aria-expanded={mobileOpen}
            aria-controls="mobile-nav"
            onClick={() => setMobileOpen((v) => !v)}
            icon={mobileOpen ? <CloseOutlined /> : <MenuOutlined />}
          />
        </div>
      </div>

      {/* Mobile drawer — sectioned two-level menu */}
      {mobileOpen ? (
        <div
          id="mobile-nav"
          className="mobile-menu-enter max-h-[calc(100dvh-4rem)] overflow-y-auto overscroll-contain border-t bg-background/95 backdrop-blur-xl lg:hidden"
        >
          <div className="container-prose flex flex-col py-5">
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
            <nav aria-label="Primary" className="flex flex-col">
              {NAV_GROUPS.map((group) => {
                if (group.to) {
                  return (
                    <Link
                      key={group.key}
                      to={group.to}
                      onClick={() => setMobileOpen(false)}
                      ref={(el) => {
                        if (el && !firstMobileLinkRef.current) firstMobileLinkRef.current = el;
                      }}
                      className={cn(
                        "flex items-center rounded-xl px-4 py-3 text-[15px] font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                        isRouteActive(group.to)
                          ? "bg-primary/10 text-primary"
                          : "text-foreground/80 hover:bg-accent",
                      )}
                    >
                      {get(group.labelKey, t(group.labelKey))}
                    </Link>
                  );
                }

                return (
                  <div key={group.key} className="mt-5 first:mt-0">
                    <p className="px-1 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
                      {get(group.labelKey, t(group.labelKey))}
                    </p>
                    <div className="flex flex-col">
                      {(group.children ?? []).map((child, i) =>
                        child.kind === "separator" ? (
                          <div key={`sep-${group.key}-${i}`} className="my-1 h-px bg-border" aria-hidden />
                        ) : (
                          <Link
                            key={child.to}
                            to={child.to}
                            onClick={() => setMobileOpen(false)}
                            ref={(el) => {
                              if (el && !firstMobileLinkRef.current) firstMobileLinkRef.current = el;
                            }}
                            className={cn(
                              "flex items-center rounded-xl px-4 py-3 text-[15px] font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                              isRouteActive(child.to)
                                ? "bg-primary/10 text-primary"
                                : "text-foreground/80 hover:bg-accent",
                            )}
                          >
                            {get(child.labelKey, t(child.labelKey))}
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
      ) : null}
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
  const ref = React.useRef<HTMLDivElement | null>(null);
  React.useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open, setOpen]);

  const languages: ReadonlyArray<{ code: SupportedLanguage; label: string }> = [
    { code: "en", label: "English" },
    { code: "zh", label: "中文" },
  ];

  return (
    <div className="relative" ref={ref}>
      <Button
        type="text"
        aria-label="Language"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        icon={<GlobalOutlined />}
      />
      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-2 w-36 origin-top-right rounded-xl border bg-popover p-1 shadow-lg"
          style={{ animation: "fade-down 160ms cubic-bezier(0.16,1,0.3,1)" }}
        >
          {languages.map((lang) => (
            <button
              key={lang.code}
              role="menuitemradio"
              aria-checked={current === lang.code}
              onClick={() => {
                onChange(lang.code);
                setOpen(false);
              }}
              className={cn(
                "flex w-full items-center justify-between rounded-md px-3 py-2 text-sm outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
                current === lang.code && "bg-accent/60",
              )}
            >
              {lang.label}
              {current === lang.code ? <DownOutlined className="size-3 -rotate-90" aria-hidden /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
