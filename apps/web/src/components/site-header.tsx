/**
 * SiteHeader — sticky top navigation with logo, grouped nav, search trigger,
 * language switch, theme toggle, animation control, and auth menu.
 *
 * Features:
 * - Scroll-reactive backdrop blur / shadow (RAF-throttled)
 * - Four nav groups (Explore / Tools / Downloads / Resources) with dropdowns
 * - Animated underline on active nav links
 * - Cmd+K quick search trigger
 * - Smooth mobile drawer with slide-down animation
 */
import * as React from "react";
import { Link, useRouterState, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  Search,
  Menu,
  X,
  Sun,
  Moon,
  Globe,
  ChevronDown,
  Dna,
} from "lucide-react";
import { Button, cn } from "@soymutdb/ui";
import { useTheme } from "../lib/theme-provider";
import { useI18n, type SupportedLanguage } from "../lib/i18n";
import { AnimationControl } from "./animation-control";
import { NotificationBell } from "./notifications/notification-bell";

interface NavItem {
  to?: string;
  labelKey?: string;
  divider?: boolean;
}

interface NavGroup {
  labelKey: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    labelKey: "nav.explore",
    items: [
      { to: "/genes", labelKey: "nav.genes" },
      { to: "/variants", labelKey: "nav.variants" },
      { to: "/browser", labelKey: "nav.browser" },
      { to: "/sra", labelKey: "nav.sra" },
      { to: "/compare", labelKey: "nav.compare" },
      { to: "/analytics", labelKey: "nav.analytics" },
    ],
  },
  {
    labelKey: "nav.tools",
    items: [
      { to: "/blast", labelKey: "nav.blast" },
      { to: "/analyses", labelKey: "nav.analyses" },
      { divider: true },
      { to: "/tools/seqfetch", labelKey: "tools.seqfetch.title" },
      { to: "/tools/enrichment", labelKey: "tools.enrichment.title" },
      { to: "/tools/exppattern", labelKey: "tools.exppattern.title" },
      { divider: true },
      { to: "/tools", labelKey: "nav.allTools" },
    ],
  },
  {
    labelKey: "nav.resources",
    items: [
      { to: "/guide", labelKey: "nav.guide" },
      { to: "/help", labelKey: "nav.help" },
      { to: "/news", labelKey: "nav.news" },
      { to: "/publications", labelKey: "nav.publications" },
      { to: "/seed-request", labelKey: "nav.seedRequest" },
      { to: "/about", labelKey: "nav.about" },
    ],
  },
];

/** Mobile menu sections — 4 flat blocks in order. */
const MOBILE_SECTIONS: ReadonlyArray<{ labelKey: string; items: NavItem[] }> = [
  { labelKey: "nav.explore", items: NAV_GROUPS[0].items },
  { labelKey: "nav.tools", items: NAV_GROUPS[1].items },
  { labelKey: "nav.downloads", items: [{ to: "/downloads", labelKey: "nav.downloads" }] },
  { labelKey: "nav.resources", items: NAV_GROUPS[2].items },
];

export function SiteHeader() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const routerState = useRouterState();
  const currentPath = routerState.location.pathname;
  const { theme, toggleTheme } = useTheme();
  const { currentLanguage, changeLanguage } = useI18n();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [openMenu, setOpenMenu] = React.useState<string | null>(null);
  const [langOpen, setLangOpen] = React.useState(false);
  const [scrolled, setScrolled] = React.useState(false);
  const [searchValue, setSearchValue] = React.useState("");
  const headerRef = React.useRef<HTMLElement | null>(null);
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

  // Close mobile menu and dropdowns on route change
  React.useEffect(() => {
    setMobileOpen(false);
    setOpenMenu(null);
  }, [currentPath]);

  // Escape closes dropdowns; closes the mobile menu and returns focus to the toggle
  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (mobileOpen) {
        setMobileOpen(false);
        menuButtonRef.current?.focus();
      }
      setOpenMenu(null);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen]);

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
    // Dispatch a synthetic Cmd+K so the existing keyboard listener catches it
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }),
    );
  };

  const isActive = (to: string): boolean =>
    currentPath === to || (to !== "/" && currentPath.startsWith(to));

  return (
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
            <Dna className="size-5" aria-hidden />
          </span>
          <span className="font-display text-lg font-semibold tracking-tight">
            Soy<span className="text-gradient">Mut</span>DB
          </span>
        </Link>

        {/* Desktop grouped nav */}
        <nav className="hidden items-center gap-1 lg:flex" aria-label="Primary">
          <NavDropdown
            menuId="nav.explore"
            labelKey="nav.explore"
            items={NAV_GROUPS[0].items}
            currentPath={currentPath}
            open={openMenu === "nav.explore"}
            onOpenChange={(open) => setOpenMenu(open ? "nav.explore" : null)}
          />
          <NavDropdown
            menuId="nav.tools"
            labelKey="nav.tools"
            items={NAV_GROUPS[1].items}
            currentPath={currentPath}
            open={openMenu === "nav.tools"}
            onOpenChange={(open) => setOpenMenu(open ? "nav.tools" : null)}
          />
          <Link
            to="/downloads"
            data-active={isActive("/downloads")}
            className={cn(
              "nav-link rounded-md px-3 py-2 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
              isActive("/downloads")
                ? "text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t("nav.downloads")}
          </Link>
          <NavDropdown
            menuId="nav.resources"
            labelKey="nav.resources"
            items={NAV_GROUPS[2].items}
            currentPath={currentPath}
            open={openMenu === "nav.resources"}
            onOpenChange={(open) => setOpenMenu(open ? "nav.resources" : null)}
          />
        </nav>

        {/* Search (desktop) — triggers command palette */}
        <button
          type="button"
          onClick={openPalette}
          className="ml-auto hidden h-9 items-center gap-2.5 rounded-lg border border-input/70 bg-muted/40 px-3 text-sm text-muted-foreground shadow-sm transition-all hover:border-border hover:bg-muted/70 hover:text-foreground md:flex md:w-44 lg:w-56"
          aria-label="Quick search (Cmd+K)"
        >
          <Search className="size-4 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1 truncate text-left">
            <span className="hidden lg:inline">{t("home.searchPlaceholder")}</span>
            <span className="lg:hidden">Search…</span>
          </span>
          <span className="ml-auto flex shrink-0 items-center gap-1" aria-hidden>
            <kbd className="hidden sm:inline-flex">⌘</kbd>
            <kbd className="hidden sm:inline-flex">K</kbd>
          </span>
        </button>

        {/* Right cluster */}
        <div className="ml-auto flex items-center gap-1 md:ml-2">
          <NotificationBell />
          <LanguageSwitcher
            open={langOpen}
            setOpen={setLangOpen}
            current={currentLanguage as SupportedLanguage}
            onChange={changeLanguage}
          />
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("nav.theme")}
            onClick={toggleTheme}
          >
            {theme === "dark" ? <Sun className="size-4" aria-hidden /> : <Moon className="size-4" aria-hidden />}
          </Button>
          <AnimationControl />

          {/* Mobile search button */}
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            aria-label="Search"
            onClick={openPalette}
          >
            <Search className="size-5" aria-hidden />
          </Button>

          {/* Mobile menu toggle */}
          <Button
            ref={menuButtonRef}
            variant="ghost"
            size="icon"
            className="lg:hidden"
            aria-label={mobileOpen ? "Close menu" : "Open menu"}
            aria-expanded={mobileOpen}
            aria-controls="mobile-nav"
            onClick={() => setMobileOpen((v) => !v)}
          >
            {mobileOpen ? <X className="size-5" aria-hidden /> : <Menu className="size-5" aria-hidden />}
          </Button>
        </div>
      </div>

      {/* Mobile drawer — smooth slide-down with flat grouped sections */}
      {mobileOpen ? (
        <div
          id="mobile-nav"
          className="mobile-menu-enter max-h-[calc(100dvh-4rem)] overflow-y-auto overscroll-contain border-t bg-background/95 backdrop-blur-xl lg:hidden"
        >
          <div className="container-prose flex flex-col py-5">
            <form onSubmit={onSearchSubmit} role="search" className="mb-5 md:hidden">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
                <input
                  type="search"
                  value={searchValue}
                  onChange={(e) => setSearchValue(e.target.value)}
                  placeholder={t("home.searchPlaceholder")}
                  aria-label={t("nav.search")}
                  className="h-11 w-full rounded-xl border border-input bg-background pl-10 pr-3 text-sm shadow-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring"
                />
              </div>
            </form>

            {MOBILE_SECTIONS.map((section, sectionIndex) => (
              <div key={section.labelKey} className={cn(sectionIndex > 0 && "mt-5")}>
                <h2 className="px-1 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
                  {t(section.labelKey)}
                </h2>
                <nav aria-label={t(section.labelKey)} className="flex flex-col gap-1">
                  {section.items.map((item, itemIndex) =>
                    item.divider || !item.to || !item.labelKey ? null : (
                      <Link
                        key={item.to}
                        to={item.to}
                        onClick={() => setMobileOpen(false)}
                        ref={sectionIndex === 0 && itemIndex === 0 ? firstMobileLinkRef : undefined}
                        className={cn(
                          "flex items-center rounded-xl px-4 py-3 text-[15px] font-medium transition-colors",
                          isActive(item.to)
                            ? "bg-primary/10 text-primary"
                            : "text-foreground/80 hover:bg-accent",
                        )}
                      >
                        {t(item.labelKey)}
                      </Link>
                    ),
                  )}
                </nav>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </header>
  );
}

function NavDropdown({
  menuId,
  labelKey,
  items,
  currentPath,
  open,
  onOpenChange,
}: {
  menuId: string;
  labelKey: string;
  items: NavItem[];
  currentPath: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const ref = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onOpenChange(false);
    };
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open, onOpenChange]);

  const isActive = (to: string): boolean =>
    currentPath === to || (to !== "/" && currentPath.startsWith(to));
  const groupActive = items.some((item) => item.to && isActive(item.to));

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        data-active={groupActive}
        onClick={() => onOpenChange(!open)}
        className={cn(
          "nav-link flex items-center gap-1 rounded-md px-3 py-2 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
          groupActive ? "text-foreground" : "text-muted-foreground hover:text-foreground",
        )}
      >
        {t(labelKey)}
        <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute left-1/2 top-full z-50 mt-2 w-60 -translate-x-1/2 rounded-xl border bg-popover p-1.5 shadow-lg"
          style={{ animation: "fade-down 160ms cubic-bezier(0.16,1,0.3,1)" }}
        >
          {items.map((item, i) =>
            item.divider || !item.to || !item.labelKey ? (
              <div key={`${menuId}-divider-${i}`} className="my-1 h-px bg-border" aria-hidden />
            ) : (
              <Link
                key={item.to}
                to={item.to}
                role="menuitem"
                onClick={() => onOpenChange(false)}
                className={cn(
                  "flex items-center rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
                  isActive(item.to) && "bg-accent/60 font-medium text-foreground",
                )}
              >
                {t(item.labelKey)}
              </Link>
            ),
          )}
        </div>
      ) : null}
    </div>
  );
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
        variant="ghost"
        size="icon"
        aria-label="Language"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Globe className="size-4" aria-hidden />
      </Button>
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
                "flex w-full items-center justify-between rounded-md px-3 py-2 text-sm transition-colors hover:bg-accent",
                current === lang.code && "bg-accent/60",
              )}
            >
              {lang.label}
              {current === lang.code ? <ChevronDown className="size-3 -rotate-90" aria-hidden /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
