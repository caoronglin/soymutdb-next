/**
 * SiteHeader — sticky top navigation with logo, primary nav, search trigger,
 * language switch, theme toggle, animation control, and auth menu.
 *
 * Features:
 * - Scroll-reactive backdrop blur / shadow (RAF-throttled)
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
  ChevronRight,
  Dna,
} from "lucide-react";
import { Button, cn } from "@soymutdb/ui";
import { useTheme } from "../lib/theme-provider";
import { useI18n, type SupportedLanguage } from "../lib/i18n";
import { AnimationControl } from "./animation-control";

interface NavItem {
  to: string;
  labelKey: string;
}

const PRIMARY_NAV: NavItem[] = [
  { to: "/genes", labelKey: "nav.genes" },
  { to: "/variants", labelKey: "nav.variants" },
  { to: "/browser", labelKey: "nav.browser" },
  { to: "/blast", labelKey: "nav.blast" },
  { to: "/analytics", labelKey: "nav.analytics" },
  { to: "/downloads", labelKey: "nav.downloads" },
];

const SECONDARY_NAV: NavItem[] = [
  { to: "/sra", labelKey: "nav.sra" },
  { to: "/compare", labelKey: "nav.compare" },
  { to: "/news", labelKey: "nav.news" },
  { to: "/publications", labelKey: "nav.publications" },
  { to: "/seed-request", labelKey: "nav.seedRequest" },
  { to: "/guide", labelKey: "nav.guide" },
  { to: "/help", labelKey: "nav.help" },
];

export function SiteHeader() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const routerState = useRouterState();
  const currentPath = routerState.location.pathname;
  const { theme, toggleTheme } = useTheme();
  const { currentLanguage, changeLanguage } = useI18n();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [langOpen, setLangOpen] = React.useState(false);
  const [scrolled, setScrolled] = React.useState(false);
  const [searchValue, setSearchValue] = React.useState("");
  const headerRef = React.useRef<HTMLElement | null>(null);

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

  // Close mobile menu on route change
  React.useEffect(() => {
    setMobileOpen(false);
  }, [currentPath]);

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

        {/* Desktop primary nav */}
        <nav className="hidden items-center gap-1 lg:flex" aria-label="Primary">
          {PRIMARY_NAV.map((item) => (
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

      {/* Mobile drawer — smooth slide-down with staggered items */}
      {mobileOpen ? (
        <div
          id="mobile-nav"
          className="mobile-menu-enter max-h-[calc(100dvh-4rem)] overflow-y-auto overscroll-contain border-t bg-background/95 backdrop-blur-xl lg:hidden"
        >
          <div className="container-prose flex flex-col gap-5 py-5">
            <form onSubmit={onSearchSubmit} role="search" className="md:hidden">
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

            {/* Primary destinations — large touch targets */}
            <nav aria-label="Mobile primary" className="flex flex-col gap-1">
              {PRIMARY_NAV.map((item, i) => (
                <Link
                  key={item.to}
                  to={item.to}
                  onClick={() => setMobileOpen(false)}
                  style={{ animationDelay: `${i * 35}ms` }}
                  className={cn(
                    "mobile-menu-item flex items-center justify-between rounded-xl px-4 py-3 text-[15px] font-medium transition-colors",
                    isActive(item.to)
                      ? "bg-primary/10 text-primary shadow-[inset_3px_0_0_var(--primary)]"
                      : "text-foreground/80 hover:bg-accent hover:text-foreground",
                  )}
                >
                  {t(item.labelKey)}
                  <ChevronRight className={cn("size-4", isActive(item.to) ? "text-primary/70" : "text-muted-foreground/40")} aria-hidden />
                </Link>
              ))}
            </nav>

            {/* Secondary destinations — compact grid */}
            <div>
              <div className="mb-2 flex items-center gap-3">
                <span className="h-px flex-1 bg-border/70" aria-hidden />
                <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">{t("nav.more")}</span>
                <span className="h-px flex-1 bg-border/70" aria-hidden />
              </div>
              <nav aria-label="Mobile secondary" className="grid grid-cols-2 gap-1.5">
                {SECONDARY_NAV.map((item, i) => (
                  <Link
                    key={item.to}
                    to={item.to}
                    onClick={() => setMobileOpen(false)}
                    style={{ animationDelay: `${(PRIMARY_NAV.length + i) * 35}ms` }}
                    className={cn(
                      "mobile-menu-item rounded-lg border border-border/60 px-3 py-2.5 text-sm transition-colors",
                      isActive(item.to)
                        ? "border-primary/30 bg-primary/5 font-medium text-primary"
                        : "text-muted-foreground hover:bg-accent hover:text-foreground",
                    )}
                  >
                    {t(item.labelKey)}
                  </Link>
                ))}
              </nav>
            </div>
          </div>
        </div>
      ) : null}
    </header>
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
