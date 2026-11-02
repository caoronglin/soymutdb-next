import { SearchOutlined } from "@ant-design/icons";
import { searchGenes, type GeneSummary } from "@soymutdb/api-client";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Input, type InputRef } from "@/lib/antd";
import { cn } from "../lib/cn";

export type AdminCommandPath = "/" | "/imports" | "/content" | "/news/new" | "/settings" | "/audit";

interface RouteCommand {
  id: string;
  kind: "route";
  path: AdminCommandPath;
  /** Locale key for the row title; `defaultValue` is the English fallback. */
  labelKey: string;
  label: string;
  /** Locale key for the one-line description under the title. */
  hintKey: string;
  hint: string;
  /** Extra search terms, including the ones operators actually type. */
  keywords: string[];
}

interface GeneResult {
  id: string;
  kind: "gene";
  geneId: string;
  label: string;
  hint: string;
}

type PaletteResult = RouteCommand | GeneResult;

// Only live destinations belong here. ADR-0009 retirements and the unavailable
// resource-catalog page are intentionally absent: a command that lands on an
// "unavailable" page is a dead end an operator cannot act on. Every copy is a
// locale key — this surface is reachable from ⌘K in a Chinese console, so
// hardcoded English here would bypass the locale entirely.
export const COMMANDS: readonly RouteCommand[] = [
  {
    id: "dashboard",
    labelKey: "admin.commandPalette.commands.dashboard.label",
    label: "Open dashboard",
    hintKey: "admin.commandPalette.commands.dashboard.hint",
    hint: "Overview and operational metrics",
    kind: "route",
    path: "/",
    keywords: ["home", "dashboard", "仪表盘"],
  },
  {
    id: "import",
    labelKey: "admin.commandPalette.commands.import.label",
    label: "Start a data import",
    hintKey: "admin.commandPalette.commands.import.hint",
    hint: "Create or inspect import work",
    kind: "route",
    path: "/imports",
    keywords: ["import", "upload", "数据导入"],
  },
  {
    id: "content",
    labelKey: "admin.commandPalette.commands.content.label",
    label: "Manage content",
    hintKey: "admin.commandPalette.commands.content.hint",
    hint: "Static pages, news, and publications",
    kind: "route",
    path: "/content",
    keywords: ["content", "page", "内容", "页面"],
  },
  {
    id: "new-news",
    labelKey: "admin.commandPalette.commands.newNews.label",
    label: "Create news",
    hintKey: "admin.commandPalette.commands.newNews.hint",
    hint: "Draft a new announcement",
    kind: "route",
    path: "/news/new",
    keywords: ["news", "announcement", "新建新闻"],
  },
  {
    id: "settings",
    labelKey: "admin.commandPalette.commands.settings.label",
    label: "Open settings",
    hintKey: "admin.commandPalette.commands.settings.hint",
    hint: "Site and system configuration",
    kind: "route",
    path: "/settings",
    keywords: ["settings", "configuration", "设置"],
  },
  {
    id: "audit",
    labelKey: "admin.commandPalette.commands.audit.label",
    label: "View audit logs",
    hintKey: "admin.commandPalette.commands.audit.hint",
    hint: "Review recent administrative changes",
    kind: "route",
    path: "/audit",
    keywords: ["audit", "history", "日志"],
  },
];

function geneResult(
  gene: GeneSummary,
  fallbackHint: string,
): GeneResult {
  const descriptor = [gene.symbol, gene.name].filter(Boolean).join(" · ");
  return {
    id: "gene-" + gene.id,
    kind: "gene",
    geneId: gene.gene_id,
    label: gene.gene_id,
    hint: descriptor || fallbackHint,
  };
}

export function AdminCommandPalette({ open, onClose, onNavigate, onOpenGene }: { open: boolean; onClose: () => void; onNavigate: (path: AdminCommandPath) => void; onOpenGene: (geneId: string) => void }) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [genes, setGenes] = useState<GeneSummary[]>([]);
  const [geneSearchFailed, setGeneSearchFailed] = useState(false);
  const normalized = query.trim();
  // The palette takes focus on open, so it has to give it back on close —
  // otherwise a keyboard operator who dismisses it lands on <body> with no idea
  // where they were in the console.
  const openerRef = useRef<HTMLElement | null>(null);

  const geneFallbackHint = t("admin.commandPalette.geneHint", {
    defaultValue: "Published gene record",
  });

  const staticResults = useMemo(() => {
    const lower = normalized.toLocaleLowerCase();
    const localized = COMMANDS.map((command) => ({
      ...command,
      label: t(command.labelKey, { defaultValue: command.label }),
      hint: t(command.hintKey, { defaultValue: command.hint }),
    }));
    if (!lower) return localized;
    return localized.filter((command) =>
      [command.label, command.hint, ...command.keywords]
        .join(" ")
        .toLocaleLowerCase()
        .includes(lower),
    );
  }, [normalized, t]);
  const results = useMemo(
    () => [...staticResults, ...genes.map((gene) => geneResult(gene, geneFallbackHint))],
    [staticResults, genes, geneFallbackHint],
  );

  useEffect(() => {
    if (!open) return;
    openerRef.current = document.activeElement as HTMLElement | null;
    setQuery(""); setGenes([]); setGeneSearchFailed(false); setActiveIndex(0);
    requestAnimationFrame(() => inputRef.current?.focus());
    return () => { openerRef.current?.focus(); };
  }, [open]);

  useEffect(() => {
    if (!open || normalized.length < 3) { setGenes([]); setGeneSearchFailed(false); return; }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void searchGenes({ q: normalized, limit: 5 }).then((response) => {
        if (!cancelled) { setGenes(response.items); setGeneSearchFailed(false); }
      }).catch(() => { if (!cancelled) { setGenes([]); setGeneSearchFailed(true); } });
    }, 250);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [normalized, open]);

  useEffect(() => { if (activeIndex >= results.length) setActiveIndex(Math.max(results.length - 1, 0)); }, [activeIndex, results.length]);

  // Declared above the `open` early return: a hook below a conditional return
  // would make the hook count depend on `open`, and closing the palette would
  // then throw "Rendered more hooks than during the previous render".
  const choose = useCallback((result: PaletteResult | undefined) => {
    if (!result) return;
    if (result.kind === "gene") onOpenGene(result.geneId); else onNavigate(result.path);
    onClose();
  }, [onClose, onNavigate, onOpenGene]);

  if (!open) return null;

  return <div className="fixed inset-0 z-[70] flex items-start justify-center bg-black/45 px-4 pt-[12vh]" onMouseDown={onClose}>
    <section aria-label={t("admin.commandPalette.dialogLabel", { defaultValue: "Command palette" })} aria-modal="true" className="w-full max-w-xl overflow-hidden rounded-lg border border-border bg-popover shadow-2xl" onMouseDown={(event) => event.stopPropagation()} onKeyDown={(event) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      else if (event.key === "ArrowDown") { event.preventDefault(); setActiveIndex((index) => Math.min(index + 1, Math.max(results.length - 1, 0))); }
      else if (event.key === "ArrowUp") { event.preventDefault(); setActiveIndex((index) => Math.max(index - 1, 0)); }
      else if (event.key === "Enter") { event.preventDefault(); choose(results[activeIndex]); }
    }} role="dialog">
      {/* The search field is antd's `Input` with the borderless variant, so it
          still carries the combobox role and aria wiring through to the DOM. */}
      <div className="flex items-center gap-3 border-b border-border px-4">
        <SearchOutlined aria-hidden className="text-muted-foreground" />
        <Input
          ref={inputRef as React.Ref<InputRef>}
          variant="borderless"
          size="large"
          aria-activedescendant={results[activeIndex] ? "admin-command-" + results[activeIndex].id : undefined}
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-expanded="true"
          aria-label={t("admin.commandPalette.inputLabel", { defaultValue: "Search commands and genes" })}
          className="min-w-0 flex-1"
          onChange={(event) => { setQuery(event.target.value); setActiveIndex(0); }}
          placeholder={t("admin.shell.commandPlaceholder", { defaultValue: "Search commands or published genes…" })}
          role="combobox"
          value={query}
        />
        <kbd className="rounded border border-border px-1.5 py-0.5 text-xs text-muted-foreground">Esc</kbd>
      </div>
      {/* Kept as a native listbox/option pair on purpose: this is an ARIA
          combobox, and the row needs `role="option"` + `aria-selected` plus a
          stable `id` for `aria-activedescendant`. antd has no Combobox
          component, and both `Button` and `List.Item` render their own roles,
          so substituting them would drop the semantics screen readers rely on.
          This is the only remaining native interactive element in apps/admin. */}
      <ul aria-label={t("admin.commandPalette.listLabel", { defaultValue: "Available commands" })} className="max-h-80 overflow-y-auto p-2" id={listboxId} role="listbox">
        {results.map((result, index) => <li key={result.id}><button aria-selected={index === activeIndex} className={cn("flex w-full items-start rounded-lg px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", index === activeIndex ? "bg-accent text-accent-foreground" : "hover:bg-accent/70")} id={"admin-command-" + result.id} onClick={() => choose(result)} onMouseMove={() => setActiveIndex(index)} role="option" type="button"><span className="min-w-0 flex-1"><span className="block text-sm font-medium">{result.label}</span><span className="mt-0.5 block text-xs text-muted-foreground">{result.hint}</span></span><span aria-hidden className="ml-3 pt-1 text-xs text-muted-foreground">↵</span></button></li>)}
        {!results.length && !geneSearchFailed ? <li className="px-3 py-8 text-center text-sm text-muted-foreground">{t("admin.shell.commandEmpty", { defaultValue: "No matching command or gene." })}</li> : null}
        {geneSearchFailed ? <li className="px-3 py-3 text-sm text-muted-foreground">{t("admin.shell.commandGeneUnavailable", { defaultValue: "Gene suggestions are unavailable; command search still works." })}</li> : null}
      </ul>
      <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">{t("admin.shell.commandHint", { defaultValue: "↑ ↓ to move, Enter to run. Gene suggestions start after 3 characters." })}</p>
    </section>
  </div>;
}
