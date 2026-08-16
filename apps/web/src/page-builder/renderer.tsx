/**
 * Public PageDefinition renderer (Phase 8).
 *
 * Renders the shared server-DTO `{ title_key, root }` definition tree where
 * `root` is a `PageComponentNode` using snake_case renderer keys. Unknown keys
 * render a dev-only error boundary and are dropped in production.
 *
 * Security invariants:
 *   - No `dangerouslySetInnerHTML` except the DOMPurify-sanitised `rich_text`.
 *   - `javascript:` and script-like values are rejected (defence in depth; the
 *     server registry is the authoritative gate).
 *   - New-tab links always use `rel="noopener noreferrer"`.
 */

import * as React from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import { Alert, Button, Divider, Tabs as AntTabs } from "antd";
import { Search, MapPin, Microscope, FlaskConical, FlaskRound } from "lucide-react";
import { getFeaturedNews } from "@soymutdb/api-client";
import type { PageComponentNode, PageDefinition } from "@soymutdb/shared";
import { NewsCarousel, NEWS_FEATURED_KEY } from "../components/news-carousel";
import { pickNewsTitle } from "../components/news-card";
import { formatDate } from "../lib/format";
import { isScriptLike } from "./types";
import { hasRendererFor } from "./registry";

/* ------------------------------------------------------------------------ */
/* Helpers                                                                  */
/* ------------------------------------------------------------------------ */

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function isSafeHref(value: unknown): value is string {
  if (typeof value !== "string") return false;
  if (isScriptLike(value)) return false;
  if (value.startsWith("//") || /^[a-z][a-z0-9+.-]*:/i.test(value) || value.includes("\\")) {
    // Allow http(s)/mailto/tel; reject everything else scheme-like (except
    // internal "/" routes, handled below).
    if (!/^(https?:|mailto:|tel:)/i.test(value)) return false;
  }
  return value.startsWith("/") || /^(https?:|mailto:|tel:)/i.test(value);
}

/** Map the five tool-entry labels to their public routes. */
const TOOL_TARGETS: Record<string, { to: string; icon: React.ComponentType<{ className?: string }> }> = {
  "Gene ID": { to: "/search/genes", icon: Search },
  "Physical Location": { to: "/search/location", icon: MapPin },
  "JBrowse 2": { to: "/search/gbrowse", icon: Microscope },
  BLAST: { to: "/blast", icon: FlaskConical },
  "Primer Design": { to: "/search/primer", icon: FlaskRound },
};

/* ------------------------------------------------------------------------ */
/* Adapters                                                                 */
/* ------------------------------------------------------------------------ */

function NewsListNode(props: { limit?: number }) {
  const { t, i18n } = useTranslation();
  const max = clamp(props.limit ?? 5, 1, 20);
  const query = useQuery({
    queryKey: NEWS_FEATURED_KEY,
    queryFn: getFeaturedNews,
    staleTime: 5 * 60 * 1000,
  });
  const items = (query.data?.featured ?? []).slice(0, max);

  if (query.isLoading) {
    return (
      <div className="space-y-2" data-testid="home-news-loading">
        {Array.from({ length: max }, (_, i) => (
          <div key={i} className="h-12 rounded-lg border border-border bg-muted/30" />
        ))}
      </div>
    );
  }
  if (query.isError) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card py-8 text-center">
        <p className="text-sm text-muted-foreground">{t("news.homeUnavailable")}</p>
        <Button size="small" className="mt-2" onClick={() => void query.refetch()}>
          {t("common.retry")}
        </Button>
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <div className="flex items-center justify-center rounded-xl border border-border bg-card py-8 text-center">
        <p className="text-sm text-muted-foreground">{t("news.noNews")}</p>
      </div>
    );
  }

  return (
    <ul className="m-0 flex list-none flex-col divide-y divide-border overflow-hidden rounded-xl border border-border bg-card p-0">
      {items.map((item) => {
        const title = pickNewsTitle(item, i18n.language);
        return (
          <li key={item.slug}>
            <Link
              to="/news/$slug"
              params={{ slug: item.slug }}
              aria-label={title}
              className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-accent/50"
            >
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                {title}
              </span>
              {item.published_at ? (
                <span className="shrink-0 font-mono text-xs text-muted-foreground">
                  {formatDate(item.published_at)}
                </span>
              ) : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function RichTextNode(props: { content?: string }) {
  if (!props.content || typeof props.content !== "string") return null;
  return (
    <div
      data-testid="home-welcome"
      className="news-content prose-sm mt-4 text-base leading-relaxed text-foreground/90"
      dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(props.content) }}
    />
  );
}

function ToolEntriesNode(props: { entries?: string[] }) {
  const { t } = useTranslation();
  const entries = (props.entries ?? []).filter((e) => TOOL_TARGETS[e]);
  if (entries.length === 0) return null;
  return (
    <div className="grid w-full gap-3 sm:grid-cols-2 lg:grid-cols-5">
      {entries.map((entry) => {
        const target = TOOL_TARGETS[entry];
        if (!target) return null;
        const Icon = target.icon;
        return (
          <Link
            key={entry}
            to={target.to}
            className="group block h-full rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <div className="flex h-full items-start gap-3 rounded-xl border border-border bg-card p-4 transition-all hover:-translate-y-0.5 hover:shadow-md">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted text-primary transition-colors group-hover:bg-primary/10">
                <Icon className="size-5" aria-hidden />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold tracking-tight group-hover:text-primary">
                  {entry}
                </span>
                <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">
                  {toolDescription(entry, t)}
                </span>
              </span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}

function toolDescription(entry: string, t: (k: string) => string): string {
  const map: Record<string, string> = {
    "Gene ID": "search.genes.subtitle",
    "Physical Location": "search.location.subtitle",
    "JBrowse 2": "browser.subtitle",
    BLAST: "blast.subtitle",
    "Primer Design": "search.primer.subtitle",
  };
  const key = map[entry];
  return key ? t(key) : "";
}

function ButtonNode(props: { label?: string; action?: string | null; variant?: string }) {
  const label = props.label ?? "";
  if (!label) return null;
  return <Button>{label}</Button>;
}

function LinkNode(props: { label?: string; href?: string | null; variant?: string }) {
  const label = props.label ?? "";
  const href = isSafeHref(props.href) ? props.href : undefined;
  if (!label) return null;
  if (!href) return <span className="text-sm">{label}</span>;
  const external = /^https?:/i.test(href);
  if (external) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className="link-underline text-primary">
        {label}
      </a>
    );
  }
  return (
    <Link to={href} className="link-underline text-primary">
      {label}
    </Link>
  );
}

function NoticeNode(props: { kind?: string; content?: string }) {
  const kind = props.kind === "warning" || props.kind === "success" || props.kind === "error" ? props.kind : "info";
  return <Alert type={kind} showIcon message={props.content ?? ""} />;
}

function JbrowseLauncherNode() {
  const { t } = useTranslation();
  return (
    <Link to="/search/gbrowse" className="link-underline text-primary">
      {t("nav.browser")}
    </Link>
  );
}

function BlastLauncherNode() {
  const { t } = useTranslation();
  return (
    <Link to="/blast" className="link-underline text-primary">
      {t("nav.blast")}
    </Link>
  );
}

function NavigationNode(props: { items?: Array<{ label: string; route: string }> }) {
  const items = props.items ?? [];
  if (items.length === 0) return null;
  return (
    <nav aria-label="Primary" className="flex flex-wrap gap-x-4 gap-y-2">
      {items.map((item) => (
        <Link key={`${item.route}-${item.label}`} to={item.route} className="link-underline text-sm">
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

function AssemblySelectNode() {
  // The `/search` hub shows assembly + query-form launchers as entry links;
  // the real forms live on the dedicated `/search/genes` & `/search/location`
  // routes. This adapter renders nothing on its own (the forms handle it).
  return null;
}

function ColumnListNode(props: { columns?: string[] }) {
  const cols = props.columns ?? [];
  if (cols.length === 0) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-border">
            {cols.map((c) => (
              <th key={c} className="px-3 py-2 font-medium text-muted-foreground">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody />
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Renderer                                                                 */
/* ------------------------------------------------------------------------ */

function ColumnsNode({ node }: { node: PageComponentNode }) {
  const count = clamp(typeof node.props?.columns === "number" ? node.props.columns : 1, 1, 4);
  const gridClass =
    count === 2 ? "lg:grid-cols-2" : count === 3 ? "lg:grid-cols-3" : count === 4 ? "lg:grid-cols-4" : "lg:grid-cols-1";
  return (
    <div className={`grid grid-cols-1 gap-6 ${gridClass}`}>
      {(node.children ?? []).map((child, index) => (
        <RenderNode key={childKey(child, index)} node={child} />
      ))}
    </div>
  );
}

function childKey(child: PageComponentNode, index = 0): string {
  return `${child.type}-${index}`;
}

/**
 * Render a single page-definition node. Unsupported keys render a dev-only
 * error boundary (never raw data); script-like values are dropped.
 */
export function RenderNode({ node }: { node: PageComponentNode }) {
  if (!hasRendererFor(node)) {
    return import.meta.env.DEV ? (
      <UnknownComponentError type={(node as { type?: unknown }).type} />
    ) : null;
  }
  const props = (node.props ?? {}) as Record<string, unknown>;

  switch (node.type) {
    case "navigation":
      return <NavigationNode items={props.items as Array<{ label: string; route: string }>} />;
    case "news_list":
      return <NewsListNode limit={props.limit as number | undefined} />;
    case "media_carousel":
      return <NewsCarousel />;
    case "rich_text":
      return <RichTextNode content={props.content as string | undefined} />;
    case "tool_entries":
      return <ToolEntriesNode entries={props.entries as string[] | undefined} />;
    case "assembly_select":
      return <AssemblySelectNode />;
    case "gene_search_form":
      return <SearchFormLauncher to="/search/genes" title={props.title as string | undefined} />;
    case "location_search_form":
      return <SearchFormLauncher to="/search/location" title={props.title as string | undefined} />;
    case "data_table":
      return <ColumnListNode columns={props.columns as string[] | undefined} />;
    case "button":
      return <ButtonNode label={props.label as string} action={props.action as string | null} variant={props.variant as string} />;
    case "link":
      return <LinkNode label={props.label as string} href={props.href as string | null} variant={props.variant as string} />;
    case "notice":
      return <NoticeNode kind={props.kind as string} content={props.content as string} />;
    case "divider":
      return <Divider />;
    case "tabs":
      return <TabsNode node={node} />;
    case "columns":
      return <ColumnsNode node={node} />;
    case "jbrowse_launcher":
      return <JbrowseLauncherNode />;
    case "blast_launcher":
      return <BlastLauncherNode />;
    default:
      return null;
  }
}

function SearchFormLauncher({ to, title }: { to: string; title?: string }) {
  const { t } = useTranslation();
  return (
    <Link
      to={to}
      className="flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-3 text-sm font-medium hover:bg-accent/50"
    >
      <Search className="size-4 text-primary" aria-hidden />
      {title ?? t("nav.search")}
    </Link>
  );
}

function TabsNode({ node }: { node: PageComponentNode }) {
  const labels = (node.props?.tabs as string[] | undefined) ?? [];
  const children = node.children ?? [];
  if (labels.length === 0 && children.length === 0) return null;
  const items =
    labels.length > 0
      ? labels.map((label, i) => ({ key: String(i), label, children: children[i] ? <RenderNode node={children[i]} /> : null }))
      : children.map((child, i) => ({ key: String(i), label: child.type, children: <RenderNode node={child} /> }));
  return <AntTabs items={items} />;
}

function UnknownComponentError({ type }: { type: unknown }) {
  return (
    <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
      Unsupported component type: {String(type)}
    </div>
  );
}

/** Render a full page definition (its `root` component tree). */
export function PageDefinitionRenderer({ definition }: { definition: PageDefinition }) {
  if (!definition?.root) return null;
  return <RenderNode node={definition.root} />;
}

export { isScriptLike };
