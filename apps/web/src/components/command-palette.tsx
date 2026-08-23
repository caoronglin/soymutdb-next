/**
 * CommandPalette — Cmd+K / Ctrl+K quick search modal.
 *
 * Simple keyboard-triggered overlay that lets users jump to primary routes
 * or initiate a text search. Uses ESC to close, arrow keys for nav (basic).
 * No external deps — pure React + a few lucide icons.
 */
import * as React from "react";
import { useNavigate } from "@tanstack/react-router";
import { SearchOutlined, CloseOutlined, DeploymentUnitOutlined, ArrowRightOutlined, ControlOutlined as CmdIcon } from "@ant-design/icons";
import { cn } from "../lib/cn";

interface QuickAction {
  id: string;
  label: string;
  description?: string;
  icon: React.ComponentType<{ className?: string }>;
  to?: string;
  searchQuery?: boolean;
}

const QUICK_ACTIONS: QuickAction[] = [
  { id: "browser", label: "Open Genome Browser", description: "Navigate to JBrowse viewer", icon: DeploymentUnitOutlined, to: "/browser" },
  { id: "genes", label: "Browse Genes", description: "Search gene models", icon: DeploymentUnitOutlined, to: "/genes" },
  { id: "variants", label: "Search Variants", description: "Query SNP/INDEL catalog", icon: DeploymentUnitOutlined, to: "/variants" },
  { id: "blast", label: "BLAST Search", description: "Sequence similarity search", icon: DeploymentUnitOutlined, to: "/blast" },
  { id: "downloads", label: "Download Data", description: "Bulk VCF/FASTA downloads", icon: ArrowRightOutlined, to: "/downloads" },
  { id: "help", label: "Help & Documentation", description: "User guides & tutorials", icon: ArrowRightOutlined, to: "/help" },
];

export function CommandPalette() {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [activeIndex, setActiveIndex] = React.useState(0);
  const navigate = useNavigate();
  const inputRef = React.useRef<HTMLInputElement>(null);

  // Keyboard shortcut: Cmd+K / Ctrl+K
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape" && open) {
        e.preventDefault();
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // Focus input when opened
  React.useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Filter actions by query
  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return QUICK_ACTIONS;
    return QUICK_ACTIONS.filter(
      (a) =>
        a.label.toLowerCase().includes(q) ||
        (a.description?.toLowerCase().includes(q) ?? false),
    );
  }, [query]);

  const handleSelect = React.useCallback(
    (action: QuickAction) => {
      setOpen(false);
      if (action.to) {
        navigate({ to: action.to as never });
      } else if (action.searchQuery && query.trim()) {
        navigate({ to: "/search", search: { q: query.trim() } } as never);
      }
    },
    [navigate, query],
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, filtered.length));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeIndex === 0 && query.trim()) {
        // Submit search
        setOpen(false);
        navigate({ to: "/search", search: { q: query.trim() } } as never);
      } else if (filtered[activeIndex - (query.trim() ? 1 : 0)]) {
        const idx = activeIndex - (query.trim() ? 1 : 0);
        if (idx >= 0) handleSelect(filtered[idx]);
      }
    }
  };

  if (!open) return null;

  return (
    <div
      className="search-modal-backdrop flex items-start justify-center px-4 pt-[12vh]"
      onClick={() => setOpen(false)}
      role="dialog"
      aria-modal="true"
      aria-label="Quick search"
    >
      <div
        className="search-modal-panel w-full max-w-xl overflow-hidden rounded-2xl border bg-popover shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 border-b px-4 py-3">
          <SearchOutlined className="size-5 shrink-0 text-muted-foreground" aria-hidden />
          <input
            ref={inputRef}
            type="search"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder="Search pages, genes, variants…"
            className="h-9 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground"
            aria-label="Search"
          />
          <kbd>ESC</kbd>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Close"
          >
            <CloseOutlined className="size-4" aria-hidden />
          </button>
        </div>

        {/* Results */}
        <div className="max-h-[50vh] overflow-y-auto p-2">
          {/* Search submission option */}
          {query.trim() && (
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                navigate({ to: "/search", search: { q: query.trim() } } as never);
              }}
              className={cn(
                "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors",
                activeIndex === 0 ? "bg-accent text-accent-foreground" : "hover:bg-accent/50",
              )}
            >
              <SearchOutlined className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="flex-1">
                Search for <span className="font-semibold">&ldquo;{query.trim()}&rdquo;</span>
              </span>
              <ArrowRightOutlined className="size-3.5 text-muted-foreground" aria-hidden />
            </button>
          )}

          {/* Quick actions */}
          {(query.trim() ? filtered : QUICK_ACTIONS).map((action, i) => {
            const idx = i + (query.trim() ? 1 : 0);
            const Icon = action.icon;
            return (
              <button
                key={action.id}
                type="button"
                onClick={() => handleSelect(action)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors",
                  activeIndex === idx ? "bg-accent text-accent-foreground" : "hover:bg-accent/50",
                )}
              >
                <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="flex-1">
                  <span className="font-medium">{action.label}</span>
                  {action.description && (
                    <span className="ml-2 text-xs text-muted-foreground">{action.description}</span>
                  )}
                </span>
                <ArrowRightOutlined className="size-3.5 text-muted-foreground" aria-hidden />
              </button>
            );
          })}

          {filtered.length === 0 && !query.trim() ? null : filtered.length === 0 && query.trim() ? (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">
              No results for &ldquo;{query.trim()}&rdquo;
            </p>
          ) : null}
        </div>

        {/* Footer hint */}
        <div className="flex items-center justify-between border-t px-4 py-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1"><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
            <span className="flex items-center gap-1"><kbd>↵</kbd> select</span>
          </div>
          <span className="flex items-center gap-1">
            <CmdIcon className="size-3" aria-hidden />K to open
          </span>
        </div>
      </div>
    </div>
  );
}
