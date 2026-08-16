/**
 * Public PageDefinition renderer (Phase 4).
 *
 * Renders a safe, data-only PageDefinition tree into React. Component keys are
 * resolved against the exhaustive COMPONENT_RENDERERS map; unknown keys render
 * a dev-only error boundary and are rejected before production builds.
 *
 * Security invariants:
 *   - No `dangerouslySetInnerHTML` except the rich-text adapter, whose content
 *     is re-sanitised with DOMPurify (defence in depth on top of the backend).
 *   - `javascript:` (and any script-like) URLs/values are rejected.
 *   - New-tab links always set `rel="noopener noreferrer"`.
 */

import * as React from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import { Alert, Button, Divider, Tabs as AntTabs } from "antd";
import {
  Search,
  MapPin,
  Microscope,
  FlaskConical,
  FlaskRound,
} from "lucide-react";
import { getFeaturedNews, getSiteHome } from "@soymutdb/api-client";
import { NewsCarousel, NEWS_FEATURED_KEY } from "../components/news-carousel";
import { pickNewsTitle } from "../components/news-card";
import { formatDate } from "../lib/format";
import {
  type PageComponent,
  type PageDefinition,
  type PageSection,
  isComponentTypeKey,
  isScriptLike,
} from "./types";
import { hasRendererFor } from "./registry";

/* ------------------------------------------------------------------------ */
/* Leaf adapters                                                            */
/* ------------------------------------------------------------------------ */

function isSafeHref(value: unknown): value is string {
  if (typeof value !== "string") return false;
  if (isScriptLike(value)) return false;
  if (value.startsWith("//") || /^[a-z][a-z0-9+.-]*:/i.test(value) || value.includes("\\")) {
    return false;
  }
  return value.startsWith("/");
}

function LatestNewsNode(props: { max?: number }) {
  const { t, i18n } = useTranslation();
  const max = clamp(props.max ?? 5, 1, 5);
  const featuredQuery = useQuery({
    queryKey: NEWS_FEATURED_KEY,
    queryFn: getFeaturedNews,
    staleTime: 5 * 60 * 1000,
  });
  const items = (featuredQuery.data?.featured ?? []).slice(0, max);

  if (featuredQuery.isLoading) {
    return (
      <div className="space-y-2" data-testid="home-news-loading">
        {Array.from({ length: max }, (_, i) => (
          <div key={i} className="h-12 rounded-lg border border-border bg-muted/30" />
        ))}
      </div>
    );
  }
  if (featuredQuery.isError) {
    return (
      <div className="flex h-full flex-col items-center justify-center rounded-xl border border-border bg-card py-8 text-center">
        <p className="text-sm text-muted-foreground">{t("news.homeUnavailable")}</p>
        <Button size="small" className="mt-2" onClick={() => void featuredQuery.refetch()}>
          {t("common.retry")}
        </Button>
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <div className="flex h-full items-center justify-center rounded-xl border border-border bg-card py-8 text-center">
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

function FeaturedCarouselNode() {
  return <NewsCarousel />;
}

function RichTextNode(props: { contentKey?: string; html?: string }) {
  const { t } = useTranslation();
  // Prefer inline sanitised HTML from CMS (already DOMPurify'd here as
  // defence in depth); fall back to a translated block.
  if (props.html && typeof props.html === "string") {
    return (
      <div
        data-testid="home-welcome"
        className="news-content prose-sm mt-4 text-base leading-relaxed text-foreground/90"
        dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(props.html) }}
      />
    );
  }
  if (props.contentKey) {
    return <p className="mt-4 text-base leading-relaxed text-foreground/90">{t(props.contentKey)}</p>;
  }
  return null;
}

/** CMS welcome content — resolves the sanitised /site/home block. */
function HomeCmsContent() {
  const { i18n } = useTranslation();
  const homeQuery = useQuery({
    queryKey: ["site-home"],
    queryFn: getSiteHome,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const data = homeQuery.data;
  const isZh = i18n.language.toLowerCase().startsWith("zh");
  const html = data ? (isZh && data.welcome_zh ? data.welcome_zh : data.welcome_en) : null;
  if (!html?.trim()) return null;
  return <RichTextNode html={html} />;
}

const TOOL_TARGETS: Record<
  string,
  { to: string; icon: React.ComponentType<{ className?: string }> }
> = {
  "gene-id": { to: "/search/genes", icon: Search },
  "physical-location": { to: "/search/location", icon: MapPin },
  "jbrowse-2": { to: "/search/gbrowse", icon: Microscope },
  blast: { to: "/blast", icon: FlaskConical },
  "primer-design": { to: "/search/primer", icon: FlaskRound },
};

function ToolEntryNode(props: { target: string; labelKey: string; descriptionKey: string }) {
  const { t } = useTranslation();
  const target = TOOL_TARGETS[props.target];
  if (!target) return null;
  const Icon = target.icon;
  return (
    <Link
      to={target.to}
      className="group block h-full rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      <div className="flex h-full items-start gap-3 rounded-xl border border-border bg-card p-4 transition-all hover:-translate-y-0.5 hover:shadow-md">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted text-primary transition-colors group-hover:bg-primary/10">
          <Icon className="size-5" aria-hidden />
        </span>
        <span className="min-w-0">
          <span className="block text-sm font-semibold tracking-tight group-hover:text-primary">
            {t(props.labelKey)}
          </span>
          <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">
            {t(props.descriptionKey)}
          </span>
        </span>
      </div>
    </Link>
  );
}

function ButtonNode(props: { labelKey: string; action: string; to: string }) {
  const { t } = useTranslation();
  const safeTo = isSafeHref(props.to) ? props.to : undefined;
  if (!safeTo) return null;
  if (props.action === "new-tab") {
    return (
      <a href={safeTo} target="_blank" rel="noopener noreferrer">
        <Button>{t(props.labelKey)}</Button>
      </a>
    );
  }
  return (
    <Link to={safeTo}>
      <Button>{t(props.labelKey)}</Button>
    </Link>
  );
}

function LinkNode(props: { labelKey: string; to: string; newTab?: boolean }) {
  const { t } = useTranslation();
  const safeTo = isSafeHref(props.to) ? props.to : undefined;
  if (!safeTo) return null;
  if (props.newTab) {
    return (
      <a href={safeTo} target="_blank" rel="noopener noreferrer" className="link-underline text-primary">
        {t(props.labelKey)}
      </a>
    );
  }
  return (
    <Link to={safeTo} className="link-underline text-primary">
      {t(props.labelKey)}
    </Link>
  );
}

function NoticeNode(props: { kind: string; textKey: string }) {
  const { t } = useTranslation();
  const type = props.kind === "warning" ? "warning" : props.kind === "error" ? "error" : "info";
  return <Alert type={type} showIcon message={t(props.textKey)} />;
}

function DividerNode() {
  return <Divider />;
}

function TabsNode(props: { tabs?: ReadonlyArray<{ labelKey: string; id: string }> }) {
  const { t } = useTranslation();
  const tabs = props.tabs ?? [];
  return (
    <AntTabs
      items={tabs.map((tab) => ({ key: tab.id, label: t(tab.labelKey), children: null }))}
    />
  );
}

function ColumnsNode(props: {
  ratio?: string;
  children?: PageComponent[];
}) {
  const ratioClass =
    props.ratio === "2fr_3fr"
      ? "lg:grid-cols-[2fr_3fr]"
      : props.ratio === "3fr_2fr"
        ? "lg:grid-cols-[3fr_2fr]"
        : props.ratio === "1fr_1fr"
          ? "lg:grid-cols-2"
          : "lg:grid-cols-1";
  return (
    <div className={`grid grid-cols-1 gap-6 ${ratioClass}`}>
      {(props.children ?? []).map((child) => (
        <RenderNode key={child.id} node={child} />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Renderer                                                                 */
/* ------------------------------------------------------------------------ */

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

/**
 * Render a single node. Unsupported/unknown keys render a dev-only error
 * boundary (never raw data), and script-like values are dropped.
 */
export function RenderNode({ node }: { node: PageComponent }) {
  if (isScriptLike(JSON.stringify(node))) {
    return null;
  }
  if (!hasRendererFor(node)) {
    return import.meta.env.DEV ? <UnknownComponentError type={(node as { type: unknown }).type} /> : null;
  }
  switch (node.type) {
    case "columns":
      return <ColumnsNode ratio={node.props.ratio} children={node.props.children} />;
    case "latest-news":
      return <LatestNewsNode max={node.props?.max} />;
    case "featured-carousel":
      return <FeaturedCarouselNode />;
    case "rich-text":
      return <RichTextNode contentKey={node.props.contentKey} html={node.props.html} />;
    case "tool-entry":
      return (
        <ToolEntryNode
          target={node.props.target}
          labelKey={node.props.labelKey}
          descriptionKey={node.props.descriptionKey}
        />
      );
    case "button":
      return <ButtonNode labelKey={node.props.labelKey} action={node.props.action} to={node.props.to} />;
    case "link":
      return <LinkNode labelKey={node.props.labelKey} to={node.props.to} newTab={node.props.newTab} />;
    case "notice":
      return <NoticeNode kind={node.props.kind} textKey={node.props.textKey} />;
    case "divider":
      return <DividerNode />;
    case "tabs":
      return <TabsNode tabs={node.props?.tabs} />;
    // Specialized launchers: the full implementations live in their route
    // components; these adapters render safe entry links only.
    case "jbrowse-launcher":
      return <LinkNode labelKey="nav.browser" to="/search/gbrowse" />;
    case "blast-launcher":
      return <LinkNode labelKey="nav.blast" to="/blast" />;
    default:
      // site/query forms, footer nav, data-table: rendered by dedicated route
      // components; returning null here keeps the renderer honest (no data).
      return null;
  }
}

function UnknownComponentError({ type }: { type: unknown }) {
  return (
    <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
      Unsupported component type: {String(type)}
    </div>
  );
}

/** Render a full page definition (ordered sections). */
export function PageDefinitionRenderer({ definition }: { definition: PageDefinition }) {
  return (
    <>
      {definition.sections.map((section) => (
        <SectionRenderer key={section.id} section={section} />
      ))}
    </>
  );
}

function SectionRenderer({ section }: { section: PageSection }) {
  return (
    <section>
      {section.components.map((node) => {
        if (node.type === "rich-text" && node.id === "home-cms") {
          // Home CMS content is resolved from /site/home (not a seed literal).
          return <HomeCmsContent key={node.id} />;
        }
        return <RenderNode key={node.id} node={node} />;
      })}
    </section>
  );
}

// Re-export type key guard for consumers.
export { isComponentTypeKey };
