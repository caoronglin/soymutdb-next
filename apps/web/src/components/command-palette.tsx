/**
 * CommandPalette — Cmd+K / Ctrl+K quick search modal.
 *
 * Keyboard-triggered overlay that lets users jump to primary routes or start
 * an identifier search. It behaves like the modal it claims to be:
 *
 *  - focus moves into the field on open and returns to whatever opened the
 *    palette when it closes (Escape, the backdrop, or picking a row);
 *  - Tab / Shift+Tab cycle inside the panel instead of walking out of the
 *    `aria-modal` overlay into the page behind it;
 *  - the field is an ARIA combobox: `aria-activedescendant` names the
 *    highlighted row, so the active option is announced instead of only being
 *    highlighted with CSS.
 *
 * Every visible string comes from the shared catalogs
 * (`commandPalette.<id>.label` / `commandPalette.<id>.description`, present in
 * both `en` and `zh`); the English text kept in `QUICK_ACTIONS` is only the
 * fallback for a missing key.
 *
 * No external deps — pure React + a few antd icons.
 */
import * as React from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "@tanstack/react-router";
import { SearchOutlined, CloseOutlined, DeploymentUnitOutlined, ArrowRightOutlined, ControlOutlined as CmdIcon } from "@ant-design/icons";
import { Button, Input, type InputRef } from "@/lib/antd";
import { cn } from "../lib/cn";

interface QuickAction {
  id: string;
  /** Locale key for the row title (`commandPalette.<id>.label`). */
  labelKey: string;
  /** English fallback for the row title, used when the key is missing. */
  label: string;
  /** Locale key for the one-line description under the title. */
  descriptionKey: string;
  /** English fallback for the description, used when the key is missing. */
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  to?: string;
  searchQuery?: boolean;
}

/**
 * The rows are data, not copy: the visible label and description are read
 * from the catalogs at render time. The English strings stay as the fallback
 * for a missing key and as extra search terms, so typing "blast" still finds
 * the BLAST row in a Chinese console.
 */
const QUICK_ACTIONS: QuickAction[] = [
  {
    id: "browser",
    labelKey: "commandPalette.browser.label",
    label: "Open Genome Browser",
    descriptionKey: "commandPalette.browser.description",
    description: "Navigate to JBrowse viewer",
    icon: DeploymentUnitOutlined,
    to: "/search/gbrowse",
  },
  {
    id: "genes",
    labelKey: "commandPalette.genes.label",
    label: "Browse Genes",
    descriptionKey: "commandPalette.genes.description",
    description: "Search gene models",
    icon: DeploymentUnitOutlined,
    to: "/genes",
  },
  {
    id: "variants",
    labelKey: "commandPalette.variants.label",
    label: "Search Variants",
    descriptionKey: "commandPalette.variants.description",
    description: "Query SNP/INDEL catalog",
    icon: DeploymentUnitOutlined,
    to: "/variants",
  },
  {
    id: "blast",
    labelKey: "commandPalette.blast.label",
    label: "BLAST Search",
    descriptionKey: "commandPalette.blast.description",
    description: "Sequence similarity search",
    icon: DeploymentUnitOutlined,
    to: "/blast",
  },
  {
    id: "downloads",
    labelKey: "commandPalette.downloads.label",
    label: "Download Data",
    descriptionKey: "commandPalette.downloads.description",
    description: "Bulk VCF/FASTA downloads",
    icon: ArrowRightOutlined,
    to: "/downloads",
  },
  {
    id: "help",
    labelKey: "commandPalette.help.label",
    label: "Help & Documentation",
    descriptionKey: "commandPalette.help.description",
    description: "User guides & tutorials",
    icon: ArrowRightOutlined,
    to: "/help",
  },
];

/** One row of the list: either the search submission or a quick action. */
type PaletteEntry =
  | { kind: "search"; id: string }
  | { kind: "action"; id: string; action: QuickAction; label: string; description: string };

/**
 * Everything that can take focus inside the panel. The rows themselves are
 * excluded: they carry `tabindex="-1"` because the combobox keeps focus in
 * the field and points at the active row with `aria-activedescendant`.
 */
const FOCUSABLE_SELECTOR = [
  'a[href]:not([tabindex="-1"])',
  'button:not([disabled]):not([tabindex="-1"])',
  'input:not([disabled]):not([tabindex="-1"])',
  'select:not([disabled]):not([tabindex="-1"])',
  'textarea:not([disabled]):not([tabindex="-1"])',
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

export function CommandPalette() {
  const { t } = useTranslation();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [activeIndex, setActiveIndex] = React.useState(0);
  const navigate = useNavigate();
  // antd's Input exposes its own imperative handle (`focus`/`blur`).
  const inputRef = React.useRef<InputRef>(null);
  const panelRef = React.useRef<HTMLDivElement | null>(null);
  /** The element that had focus when the palette opened; focus goes back there. */
  const openerRef = React.useRef<HTMLElement | null>(null);
  const reactId = React.useId();
  const listboxId = `command-palette-listbox-${reactId.replace(/[^a-zA-Z0-9_-]/g, "")}`;

  const resetPalette = React.useCallback(() => {
    setQuery("");
    setActiveIndex(0);
  }, []);

  /**
   * Give focus back to the element that opened the palette.
   *
   * The trigger may be gone by the time the palette closes — picking a row can
   * navigate away and unmount it. Focusing a detached node silently drops
   * focus on `<body>`, which is exactly the failure this restore exists to
   * prevent, so a disconnected trigger is skipped instead.
   */
  const restoreFocus = React.useCallback(() => {
    const opener = openerRef.current;
    openerRef.current = null;
    if (!opener) return;
    if (!opener.isConnected) return;
    if (opener === document.body || opener === document.documentElement) return;
    opener.focus();
  }, []);

  const closePalette = React.useCallback(() => {
    resetPalette();
    setOpen(false);
  }, [resetPalette]);

  const openPalette = React.useCallback(() => {
    const active = document.activeElement;
    openerRef.current = active instanceof HTMLElement ? active : null;
    resetPalette();
    setOpen(true);
  }, [resetPalette]);

  const togglePalette = React.useCallback(() => {
    if (open) closePalette();
    else openPalette();
  }, [closePalette, open, openPalette]);

  // Keyboard shortcut: Cmd+K / Ctrl+K
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        togglePalette();
      }
      if (e.key === "Escape" && open) {
        e.preventDefault();
        closePalette();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [closePalette, open, togglePalette]);

  // Focus input when opened. Resetting the palette happens in the open/close
  // actions above, avoiding an extra render caused by an effect-side state sync.
  React.useEffect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [open]);

  // Closing restores focus; unmounting does too, for the same reason.
  React.useEffect(() => {
    if (open) return;
    restoreFocus();
  }, [open, restoreFocus]);

  React.useEffect(() => () => restoreFocus(), [restoreFocus]);

  const trimmedQuery = query.trim();

  // Filter actions by query. The haystack carries the rendered copy and the
  // English fallback, so the palette stays searchable in either language.
  const filtered = React.useMemo(() => {
    const q = trimmedQuery.toLowerCase();
    const actions = QUICK_ACTIONS.map((action) => ({
      action,
      label: t(action.labelKey, { defaultValue: action.label }),
      description: t(action.descriptionKey, { defaultValue: action.description }),
    }));
    if (!q) return actions;
    return actions.filter(({ action, label, description }) =>
      [label, description, action.label, action.description]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [t, trimmedQuery]);

  // One ordered list of rows, so the active index means the same thing for the
  // arrow keys, `aria-activedescendant` and Enter.
  const entries = React.useMemo<PaletteEntry[]>(() => {
    const actionEntries = filtered.map(({ action, label, description }) => ({
      kind: "action" as const,
      id: action.id,
      action,
      label,
      description,
    }));
    if (!trimmedQuery) return actionEntries;
    return [{ kind: "search" as const, id: "search" }, ...actionEntries];
  }, [filtered, trimmedQuery]);

  const lastIndex = Math.max(entries.length - 1, 0);
  const clampIndex = (index: number) => Math.max(0, Math.min(index, lastIndex));
  const active = entries[clampIndex(activeIndex)];
  const activeOptionId = active ? `${listboxId}-option-${active.id}` : undefined;

  const handleSelect = React.useCallback(
    (action: QuickAction) => {
      closePalette();
      if (action.to) {
        navigate({ to: action.to as never });
      } else if (action.searchQuery && trimmedQuery) {
        navigate({ to: "/search", search: { q: trimmedQuery } } as never);
      }
    },
    [closePalette, navigate, trimmedQuery],
  );

  const activate = React.useCallback(
    (entry: PaletteEntry | undefined) => {
      if (!entry) return;
      if (entry.kind === "search") {
        closePalette();
        void navigate({ to: "/search", search: { q: trimmedQuery } } as never);
        return;
      }
      handleSelect(entry.action);
    },
    [closePalette, handleSelect, navigate, trimmedQuery],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => clampIndex(i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => clampIndex(i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      activate(active);
    }
  };

  /**
   * Keep Tab inside the modal. The overlay declares `aria-modal="true"`, so
   * letting focus walk into the header behind the backdrop would put the focus
   * ring where the user cannot see it.
   */
  const handlePanelKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const panel = panelRef.current;
    if (!panel) return;
    const focusable = Array.from(
      panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
    ).filter((el) => !el.hidden && el.getAttribute("aria-hidden") !== "true");
    if (focusable.length === 0) {
      e.preventDefault();
      return;
    }
    const current = document.activeElement as HTMLElement | null;
    const index = current ? focusable.indexOf(current) : -1;
    if (e.shiftKey) {
      if (index <= 0) {
        e.preventDefault();
        focusable[focusable.length - 1].focus();
      }
      return;
    }
    if (index === -1 || index === focusable.length - 1) {
      e.preventDefault();
      focusable[0].focus();
    }
  };

  if (!open) return null;

  return (
    <div
      className="search-modal-backdrop flex items-start justify-center px-4 pt-[12vh]"
      onClick={closePalette}
      role="dialog"
      aria-modal="true"
      aria-label={t("commandPalette.label")}
    >
      <div
        ref={panelRef}
        className="search-modal-panel w-full max-w-xl overflow-hidden rounded-2xl border bg-popover shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handlePanelKeyDown}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 border-b px-4 py-3">
          <SearchOutlined className="size-5 shrink-0 text-muted-foreground" aria-hidden />
          <Input
            ref={inputRef}
            variant="borderless"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder={t("commandPalette.placeholder")}
            className="h-9 flex-1 text-base"
            role="combobox"
            aria-expanded="true"
            aria-autocomplete="list"
            aria-controls={listboxId}
            aria-activedescendant={activeOptionId}
            aria-label={t("commandPalette.inputLabel")}
          />
          <kbd>ESC</kbd>
          <Button
            type="text"
            shape="circle"
            onClick={closePalette}
            aria-label={t("common.close")}
            icon={<CloseOutlined className="size-4" aria-hidden />}
          />
        </div>

        {/* Results */}
        <div className="max-h-[50vh] overflow-y-auto p-2">
          <div
            id={listboxId}
            role="listbox"
            aria-label={t("commandPalette.results")}
            className="flex flex-col"
          >
            {entries.map((entry, index) => {
              const selected = index === clampIndex(activeIndex);
              const optionId = `${listboxId}-option-${entry.id}`;
              if (entry.kind === "search") {
                return (
                  <Button
                    key={entry.id}
                    type="text"
                    block
                    role="option"
                    id={optionId}
                    aria-selected={selected}
                    aria-label={t("commandPalette.searchLabel", { query: trimmedQuery })}
                    tabIndex={-1}
                    onClick={() => activate(entry)}
                    onMouseEnter={() => setActiveIndex(index)}
                    className={cn(
                      "h-auto justify-start gap-3 px-3 py-2.5 text-left text-sm",
                      selected && "bg-accent text-accent-foreground",
                    )}
                  >
                    <SearchOutlined className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="flex-1">
                      {t("commandPalette.searchingFor")}{" "}
                      <span className="font-semibold">&ldquo;{trimmedQuery}&rdquo;</span>
                    </span>
                    <ArrowRightOutlined className="size-3.5 text-muted-foreground" aria-hidden />
                  </Button>
                );
              }
              const Icon = entry.action.icon;
              return (
                <Button
                  key={entry.id}
                  type="text"
                  block
                  role="option"
                  id={optionId}
                  aria-selected={selected}
                  tabIndex={-1}
                  onClick={() => activate(entry)}
                  onMouseEnter={() => setActiveIndex(index)}
                  className={cn(
                    "h-auto justify-start gap-3 px-3 py-2.5 text-left text-sm",
                    selected && "bg-accent text-accent-foreground",
                  )}
                >
                  <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="flex-1">
                    <span className="font-medium">{entry.label}</span>
                    {entry.description && (
                      <span className="ml-2 text-xs text-muted-foreground">{entry.description}</span>
                    )}
                  </span>
                  <ArrowRightOutlined className="size-3.5 text-muted-foreground" aria-hidden />
                </Button>
              );
            })}
          </div>

          {filtered.length === 0 && trimmedQuery ? (
            <p
              role="status"
              className="px-3 py-6 text-center text-sm text-muted-foreground"
            >
              {t("commandPalette.noResults", { query: trimmedQuery })}
            </p>
          ) : null}
        </div>

        {/* Footer hint */}
        <div className="flex items-center justify-between border-t px-4 py-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1"><kbd>↑</kbd><kbd>↓</kbd> {t("commandPalette.hintNavigate")}</span>
            <span className="flex items-center gap-1"><kbd>Enter</kbd> {t("commandPalette.hintSelect")}</span>
          </div>
          <span className="flex items-center gap-1">
            <CmdIcon className="size-3" aria-hidden />{t("commandPalette.hintOpen")}
          </span>
        </div>
      </div>
    </div>
  );
}
