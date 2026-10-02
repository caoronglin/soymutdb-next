import { SearchOutlined } from "@ant-design/icons";
import { searchGenes, type GeneSummary } from "@soymutdb/api-client";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Input, type InputRef } from "@/lib/antd";
import { cn } from "../lib/cn";

export type AdminCommandPath = "/" | "/imports" | "/content" | "/news/new" | "/settings" | "/audit" | "/widgets" | "/page-builder" | "/resource-catalog";

type PaletteResult =
  | { id: string; label: string; hint: string; kind: "route"; path: AdminCommandPath; keywords: string[] }
  | { id: string; label: string; hint: string; kind: "gene"; geneId: string; keywords: string[] };

const COMMANDS: readonly PaletteResult[] = [
  { id: "dashboard", label: "Open dashboard", hint: "Overview and operational metrics", kind: "route", path: "/", keywords: ["home", "dashboard", "仪表盘"] },
  { id: "import", label: "Start a data import", hint: "Create or inspect import work", kind: "route", path: "/imports", keywords: ["import", "upload", "数据导入"] },
  { id: "content", label: "Manage content", hint: "Static pages, news, and publications", kind: "route", path: "/content", keywords: ["content", "page", "内容", "页面"] },
  { id: "new-news", label: "Create news", hint: "Draft a new announcement", kind: "route", path: "/news/new", keywords: ["news", "announcement", "新建新闻"] },
  { id: "settings", label: "Open settings", hint: "Site and system configuration", kind: "route", path: "/settings", keywords: ["settings", "configuration", "设置"] },
  { id: "audit", label: "View audit logs", hint: "Review recent administrative changes", kind: "route", path: "/audit", keywords: ["audit", "history", "日志"] },
  { id: "widgets", label: "Manage widgets", hint: "Configure embedded widgets", kind: "route", path: "/widgets", keywords: ["widget", "组件"] },
  { id: "page-builder", label: "Open page builder", hint: "Create and publish definition-driven pages", kind: "route", path: "/page-builder", keywords: ["builder", "page definition", "页面构建"] },
  { id: "resources", label: "Search resource catalog", hint: "Find genes, variants, and other resources", kind: "route", path: "/resource-catalog", keywords: ["gene", "variant", "mutant", "search", "基因", "变异", "搜索"] },
];

function geneResult(gene: GeneSummary): PaletteResult {
  const descriptor = [gene.symbol, gene.name].filter(Boolean).join(" · ");
  return { id: "gene-" + gene.id, label: gene.gene_id, hint: descriptor || "Published gene record", kind: "gene", geneId: gene.gene_id, keywords: [gene.gene_id, gene.symbol ?? "", gene.name ?? ""] };
}

export function AdminCommandPalette({ open, onClose, onNavigate, onOpenGene }: { open: boolean; onClose: () => void; onNavigate: (path: AdminCommandPath) => void; onOpenGene: (geneId: string) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [genes, setGenes] = useState<GeneSummary[]>([]);
  const [geneSearchFailed, setGeneSearchFailed] = useState(false);
  const normalized = query.trim();

  const staticResults = useMemo(() => {
    const lower = normalized.toLocaleLowerCase();
    if (!lower) return COMMANDS;
    return COMMANDS.filter((command) => [command.label, command.hint, ...command.keywords].join(" ").toLocaleLowerCase().includes(lower));
  }, [normalized]);
  const results = useMemo(() => [...staticResults, ...genes.map(geneResult)], [staticResults, genes]);

  useEffect(() => {
    if (!open) return;
    setQuery(""); setGenes([]); setGeneSearchFailed(false); setActiveIndex(0);
    requestAnimationFrame(() => inputRef.current?.focus());
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
  if (!open) return null;

  const choose = (result: PaletteResult | undefined) => {
    if (!result) return;
    if (result.kind === "gene") onOpenGene(result.geneId); else onNavigate(result.path);
    onClose();
  };

  return <div className="fixed inset-0 z-[70] flex items-start justify-center bg-black/45 px-4 pt-[12vh]" onMouseDown={onClose}>
    <section aria-label="Command palette" aria-modal="true" className="w-full max-w-xl overflow-hidden rounded-lg border border-border bg-popover shadow-2xl" onMouseDown={(event) => event.stopPropagation()} onKeyDown={(event) => {
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
          aria-label="Search commands and genes"
          className="min-w-0 flex-1"
          onChange={(event) => { setQuery(event.target.value); setActiveIndex(0); }}
          placeholder="Search commands or published genes…"
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
      <ul aria-label="Available commands" className="max-h-80 overflow-y-auto p-2" id={listboxId} role="listbox">
        {results.map((result, index) => <li key={result.id}><button aria-selected={index === activeIndex} className={cn("flex w-full items-start rounded-lg px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", index === activeIndex ? "bg-accent text-accent-foreground" : "hover:bg-accent/70")} id={"admin-command-" + result.id} onClick={() => choose(result)} onMouseMove={() => setActiveIndex(index)} role="option" type="button"><span className="min-w-0 flex-1"><span className="block text-sm font-medium">{result.label}</span><span className="mt-0.5 block text-xs text-muted-foreground">{result.hint}</span></span><span aria-hidden className="ml-3 pt-1 text-xs text-muted-foreground">↵</span></button></li>)}
        {!results.length && !geneSearchFailed ? <li className="px-3 py-8 text-center text-sm text-muted-foreground">No matching command or gene. Try another keyword.</li> : null}
        {geneSearchFailed ? <li className="px-3 py-3 text-sm text-muted-foreground">Gene suggestions are temporarily unavailable; command search still works.</li> : null}
      </ul>
      <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">Gene suggestions start after 3 characters. Use ↑ ↓ and Enter to run a command.</p>
    </section>
  </div>;
}
