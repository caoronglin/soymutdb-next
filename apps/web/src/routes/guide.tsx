/**
 * Guide route — NCBI database retrieval guide rendered from a static page.
 *
 * Fetches `GET /content/pages/ncbi-database-guide` via the typed API client and
 * renders the Markdown body with `@ant-design/x-markdown`. Raw HTML is escaped
 * and every link goes through the published-content href policy below, so CMS
 * text can never inject markup or unsafe protocols. A table of contents is
 * auto-generated from h2/h3 headings and a back-to-top button appears after
 * scrolling.
 */
import * as React from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import XMarkdown, { type ComponentProps as MarkdownComponentProps } from "@ant-design/x-markdown";
import { useSiteContent } from "../lib/site-content-react";
import { http, ApiError } from "@soymutdb/api-client";
import { Button, Card, Skeleton, Tag, Typography } from "../lib/antd";
import {
    AimOutlined as Microscope,
    ArrowLeftOutlined as ArrowLeft,
    ArrowUpOutlined as ArrowUp,
    DatabaseOutlined as Database,
    DeploymentUnitOutlined as Dna,
    ExportOutlined as ExternalLink,
    FileTextOutlined as FileText,
    GlobalOutlined as Globe,
    ReadOutlined as BookOpen,
    SearchOutlined as Search,
} from "@ant-design/icons";
import { FadeUp } from "../components/route-motion";

export const Route = createFileRoute("/guide")({
    component: GuideComponent,
});

/** Static page shape returned by `GET /content/pages/{slug}`. */
interface StaticPage {
    id: string;
    slug: string;
    title_en: string;
    title_zh: string | null;
    content_en: string;
    content_zh: string | null;
    status: string;
    category: string | null;
    summary: string | null;
    sort_order: number;
    created_at: string;
    updated_at: string;
}

interface TocItem {
    id: string;
    text: string;
    level: 2 | 3;
}

const GUIDE_SLUG = "ncbi-database-guide";

const MARKDOWN_URL_BASE = "https://soymutdb.invalid/";
const MARKDOWN_URL_ORIGIN = "https://soymutdb.invalid";
const SAFE_MARKDOWN_PROTOCOLS = new Set(["http:", "https:"]);

/**
 * Return a link target only when it is safe for published Markdown.
 *
 * URL parsing is used instead of a scheme-prefix check so control-character
 * obfuscation (for example, `java\nscript:`) is handled by the browser's URL
 * parser as well. Relative links are resolved against an inert same-origin
 * base; protocol-relative and backslash-prefixed targets are explicitly
 * excluded because browsers can resolve them as external origins.
 */
function getSafeMarkdownHref(value: string): string | null {
    const href = value.trim();
    if (!href || href.startsWith("//") || href.startsWith("\\")) return null;

    try {
        const parsed = new URL(href, MARKDOWN_URL_BASE);
        const isSafeProtocol = SAFE_MARKDOWN_PROTOCOLS.has(parsed.protocol);
        const isSafeRelative = parsed.origin === MARKDOWN_URL_ORIGIN;
        return isSafeProtocol || isSafeRelative ? href : null;
    } catch {
        return null;
    }
}

/** Build a URL-safe anchor id from heading text (keeps CJK characters). */
function slugify(text: string): string {
    const slug = text
        .trim()
        .toLowerCase()
        .replace(/[^\p{L}\p{N}\s-]/gu, "")
        .replace(/\s+/g, "-");
    return slug || "section";
}

/** Flatten rendered heading children into the plain text used for anchor ids. */
function nodeText(node: React.ReactNode): string {
    if (typeof node === "string" || typeof node === "number") return String(node);
    if (Array.isArray(node)) return node.map(nodeText).join("");
    if (React.isValidElement(node)) {
        return nodeText((node.props as { children?: React.ReactNode }).children);
    }
    return "";
}

/**
 * Normalize a raw heading line for the table of contents: keep the visible
 * label of links, drop emphasis/code markers, and collapse whitespace so it
 * matches `nodeText` of the rendered heading.
 */
function headingText(raw: string): string {
    return raw
        .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
        .replace(/[#*`]/g, "")
        .trim();
}

/** Extract h2/h3 headings from Markdown source for the table of contents. */
function extractToc(markdown: string): TocItem[] {
    const items: TocItem[] = [];
    const lines = markdown.split(/\r?\n/);
    let inCodeFence = false;
    for (const line of lines) {
        if (line.trim().startsWith("```")) {
            inCodeFence = !inCodeFence;
            continue;
        }
        if (inCodeFence) continue;
        const h2 = /^(?:##)\s+(.+?)\s*$/.exec(line);
        const h3 = /^(?:###)\s+(.+?)\s*$/.exec(line);
        if (h3) {
            const text = headingText(h3[1]);
            items.push({ id: slugify(text), text, level: 3 });
        } else if (h2) {
            const text = headingText(h2[1]);
            items.push({ id: slugify(text), text, level: 2 });
        }
    }
    return items;
}

const HEADING_CLASS: Record<number, string> = {
    1: "mt-8 font-display text-3xl font-semibold tracking-tight",
    2: "mt-10 border-b pb-2 font-display text-2xl font-semibold tracking-tight",
    3: "mt-8 font-display text-xl font-semibold tracking-tight",
    4: "mt-6 text-lg font-semibold",
    5: "mt-4 text-base font-semibold",
    6: "mt-4 text-base font-semibold",
};

/**
 * Link renderer for published Markdown. Safe targets open in a new tab with a
 * hardened rel; rejected targets keep their visible label but never become
 * actionable anchors.
 */
function MarkdownLink({ href, title, children }: MarkdownComponentProps) {
    const target = typeof href === "string" ? getSafeMarkdownHref(href) : null;
    if (!target) return <>{children}</>;
    return (
        <a
            href={target}
            title={typeof title === "string" ? title : undefined}
            target="_blank"
            rel="noopener noreferrer"
            className="link-underline inline-flex items-center gap-0.5 text-primary"
        >
            {children}
            <ExternalLink className="size-3" aria-hidden />
        </a>
    );
}

/** Heading renderer that stamps the same anchor ids the TOC scrolls to. */
function heading(level: 1 | 2 | 3 | 4 | 5 | 6) {
    const Tag = `h${level}` as keyof React.JSX.IntrinsicElements;
    const className = HEADING_CLASS[level];
    return function MarkdownHeading({ children }: MarkdownComponentProps) {
        return (
            <Tag id={slugify(nodeText(children))} className={className}>
                {children}
            </Tag>
        );
    };
}

const MARKDOWN_COMPONENTS = {
    a: MarkdownLink,
    h1: heading(1),
    h2: heading(2),
    h3: heading(3),
    h4: heading(4),
    h5: heading(5),
    h6: heading(6),
};

export function Markdown({ content }: { content: string }): React.ReactElement {
    return (
        <div className="guide-content">
            <XMarkdown
                content={content}
                components={MARKDOWN_COMPONENTS}
                escapeRawHtml
                openLinksInNewTab
            />
        </div>
    );
}

function GuideComponent() {
    const { t, i18n } = useTranslation();
    const { get } = useSiteContent();
    const isZh = i18n.language?.startsWith("zh");

    const query = useQuery<StaticPage>({
        queryKey: ["static-page", GUIDE_SLUG],
        queryFn: () => http.get<StaticPage>(`/content/pages/${GUIDE_SLUG}`),
    });

    const page = query.data;
    const title = isZh && page?.title_zh ? page.title_zh : page?.title_en ?? "";
    const summary = page?.summary ?? null;
    const content = isZh && page?.content_zh ? page.content_zh : page?.content_en ?? "";
    const toc = React.useMemo(() => extractToc(content), [content]);

    const [showTop, setShowTop] = React.useState(false);
    React.useEffect(() => {
        const onScroll = () => setShowTop(window.scrollY > 480);
        window.addEventListener("scroll", onScroll, { passive: true });
        onScroll();
        return () => window.removeEventListener("scroll", onScroll);
    }, []);

    const scrollToId = (id: string) => {
        const el = document.getElementById(id);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    };

    return (
        <div className="container-prose section-rhythm">
            <FadeUp>
                <Link
                    to="/"
                    className="link-underline inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
                >
                    <ArrowLeft className="size-4" aria-hidden />
                    {t("common.back")}
                </Link>
            </FadeUp>

            {query.isLoading ? (
                <GuideSkeleton />
            ) : query.isError || !page ? (
                <GuideError error={query.error} onRetry={() => query.refetch()} />
            ) : (
                <>
                    <FadeUp>
                        <div className="mt-6 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <Tag className="gap-1">
                                <BookOpen className="size-3" aria-hidden />
                                {get("nav.guide", t("nav.guide"))}
                            </Tag>
                            {page.category ? (
                                <Tag variant="outlined" className="gap-1">
                                    <FileText className="size-3" aria-hidden />
                                    {page.category}
                                </Tag>
                            ) : null}
                            <span className="font-mono">
                                {new Date(page.updated_at).toLocaleDateString()}
                            </span>
                        </div>
                        <h1 className="mt-3 font-display text-4xl font-semibold tracking-tight">
                            {title}
                        </h1>
                        {summary ? (
                            <p className="mt-3 max-w-3xl text-lg leading-relaxed text-muted-foreground">
                                {summary}
                            </p>
                        ) : null}
                        <div className="mt-4 flex flex-wrap gap-2">
                            {[
                                { icon: Database, label: "NCBI" },
                                { icon: Dna, label: "GenBank" },
                                { icon: Microscope, label: "SRA" },
                                { icon: Search, label: "BLAST" },
                                { icon: Globe, label: "Entrez" },
                            ].map(({ icon: Icon, label }) => (
                                <span
                                    key={label}
                                    className="inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs text-muted-foreground"
                                >
                                    <Icon className="size-3" aria-hidden />
                                    {label}
                                </span>
                            ))}
                        </div>
                    </FadeUp>

                    <div className="mt-10 grid gap-8 lg:grid-cols-[minmax(0,1fr)_220px]">
                        <article className="max-w-4xl">
                            <Markdown content={content} />
                        </article>

                        {toc.length > 0 ? (
                            <aside className="hidden lg:block">
                                <div className="sticky top-24">
                                    <p className="eyebrow mb-3">{get("help.documentation", t("help.documentation"))}</p>
                                    <nav className="space-y-1 border-l pl-3 text-sm">
                                        {toc.map((item) => (
                                            <Button
                                                key={item.id}
                                                type="text"
                                                block
                                                onClick={() => scrollToId(item.id)}
                                                className={
                                                    "h-auto justify-start px-2 py-1 text-left text-muted-foreground " +
                                                    (item.level === 3 ? "pl-4" : "font-medium text-foreground/80")
                                                }
                                            >
                                                {item.text}
                                            </Button>
                                        ))}
                                    </nav>
                                </div>
                            </aside>
                        ) : null}
                    </div>
                </>
            )}

            {showTop ? (
                <Button
                    variant="outlined"
                   
                    onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
                    className="fixed bottom-6 right-6 z-40 rounded-full shadow-lg"
                    aria-label={t("common.back")}
                >
                    <ArrowUp className="size-4" aria-hidden />
                </Button>
            ) : null}
        </div>
    );
}

function GuideSkeleton() {
    return (
        <div className="mt-8 max-w-4xl space-y-4">
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-10 w-3/4" />
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-5/6" />
            <div className="mt-8 space-y-3">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-2/3" />
            </div>
            <div className="mt-6 space-y-3">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-4/5" />
            </div>
        </div>
    );
}

function GuideError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
    const { t } = useTranslation();
    const message =
        error instanceof ApiError
            ? `${error.message} (${error.status})`
            : error instanceof Error
              ? error.message
              : t("common.errorDescription");
    return (
        <Card className="mt-8 max-w-2xl">
            <div>
                <Typography.Title className="flex items-center gap-2">
                    <FileText className="size-5 text-destructive" aria-hidden />
                    {t("common.error")}
                </Typography.Title>
            </div>
            <div className="space-y-4">
                <p className="text-sm text-muted-foreground">{message}</p>
                <Button variant="outlined" onClick={onRetry}>
                    {t("common.retry")}
                </Button>
            </div>
        </Card>
    );
}