/**
 * SiteHeader — sticky top navigation with logo, flat primary nav, search
 * trigger, language switch, theme toggle, animation control, and auth menu.
 *
 * Features:
 * - Scroll-reactive backdrop blur / shadow (RAF-throttled)
 * - Five flat top-level nav items (Home / Search / Tools / Contact / News),
 *   PPTX V2 design — no secondary dropdowns; deeper pages (Downloads,
 *   Guide, …) remain reachable from the footer.
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
import { Affix } from "antd";
import { useTheme } from "../lib/theme-provider";
import { useI18n, type SupportedLanguage } from "../lib/i18n";
import { AnimationControl } from "./animation-control";
import { NotificationBell } from "./notifications/notification-bell";
import { NAVIGATION_ORDER } from "../page-builder/seed";

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

interface NavItem {
  to: string;
  labelKey: string;
}

/** Map the fixed seed labels to the app's i18n keys. */
const NAV_LABEL_KEYS: Record<string, string> = {
  Home: "nav.home",
  Search: "nav.search",
  Tools: "nav.tools",
  "Latest News": "nav.latestNews",
  Contact: "nav.contact",
};

/**
 * Primary navigation — five flat items in the approved reference order
 * (Home / Search / Tools / Latest News / Contact). The order comes from the
 * PageDefinition navigation (page-builder/seed.ts fallback) and is a single
 * source of truth for both desktop and mobile drawers. On definition/API
 * failure the same immutable five-item order is the fallback.
 */
const NAV_ITEMS: NavItem[] = NAVIGATION_ORDER.map((item) => ({
  to: item.route,
  labelKey: NAV_LABEL_KEYS[item.label] ?? item.label,
}));

export function SiteHeader() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const routerState = useRouterState();
  const currentPath = routerState.location.pathname;
  const { theme, toggleTheme } = useTheme();
  const { currentLanguage, changeLanguage } = useI18n();
  const isDesktop = useIsDesktop();
  const [mobileOpen, setMobileOpen] = React.useState(false);
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

  // Close the mobile menu on route change
  React.useEffect(() => {
    setMobileOpen(false);
  }, [currentPath]);

  // Escape closes the mobile menu and returns focus to the toggle
  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (mobileOpen) {
        setMobileOpen(false);
        menuButtonRef.current?.focus();
      }
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
            <Dna className="size-5" aria-hidden />
          </span>
          <span className="font-display text-lg font-semibold tracking-tight">
            Soy<span className="text-gradient">Mut</span>DB
          </span>
        </Link>

        {/* Desktop flat nav — five primary items, centered (PPTX V2) */}
        <nav className="mx-auto hidden items-center gap-1 lg:flex" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              data-active={isActive(item.to)}
              className={cn(
                "nav-link rounded-md px-3 py-2 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                isActive(item.to)
                  ? "text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t(item.labelKey)}
            </Link>
          ))}
        </nav>

        {/* Right cluster */}
        <div className="ml-auto flex items-center gap-1 md:ml-2">
          {/* Search (desktop) — triggers command palette */}
          <button
            type="button"
            onClick={openPalette}
            className="hidden h-9 items-center gap-2.5 rounded-lg border border-input/70 bg-muted/40 px-3 text-sm text-muted-foreground shadow-sm transition-all hover:border-border hover:bg-muted/70 hover:text-foreground md:flex md:w-44 lg:w-56"
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

            {/* Flat five-item nav (mirrors the desktop primary nav) */}
            <nav aria-label="Primary" className="flex flex-col gap-1">
              {NAV_ITEMS.map((item, itemIndex) => (
                <Link
                  key={item.to}
                  to={item.to}
                  onClick={() => setMobileOpen(false)}
                  ref={itemIndex === 0 ? firstMobileLinkRef : undefined}
                  className={cn(
                    "flex items-center rounded-xl px-4 py-3 text-[15px] font-medium transition-colors",
                    isActive(item.to)
                      ? "bg-primary/10 text-primary"
                      : "text-foreground/80 hover:bg-accent",
                  )}
                >
                  {t(item.labelKey)}
                </Link>
              ))}
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
