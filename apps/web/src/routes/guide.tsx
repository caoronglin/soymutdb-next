/**
 * Guide route — NCBI database retrieval guide rendered from a static page.
 *
 * Fetches `GET /content/pages/ncbi-database-guide` via the typed API client and
 * renders the Markdown body with a lightweight in-house renderer (the project
 * does not depend on `react-markdown`). A table of contents is auto-generated
 * from h2/h3 headings and a back-to-top button appears after scrolling.
 */
import * as React from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { http, ApiError } from "@soymutdb/api-client";
import { Button, Card, Skeleton, Tag, Typography } from "@/lib/antd";
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

/** Build a URL-safe anchor id from heading text (keeps CJK characters). */
function slugify(text: string): string {
    const slug = text
        .trim()
        .toLowerCase()
        .replace(/[^\p{L}\p{N}\s-]/gu, "")
        .replace(/\s+/g, "-");
    return slug || "section";
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
            const text = h3[1].replace(/[#*`]/g, "").trim();
            items.push({ id: slugify(text), text, level: 3 });
        } else if (h2) {
            const text = h2[1].replace(/[#*`]/g, "").trim();
            items.push({ id: slugify(text), text, level: 2 });
        }
    }
    return items;
}

/** Render inline Markdown (bold, italic, code, links) into React nodes. */
function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
    const nodes: React.ReactNode[] = [];
    // Order matters: bold (**) before italic (*) so the greedy star wins.
    const regex = /\*\*(.+?)\*\*|`(.+?)`|\[(.+?)\]\(([^)]+)\)|\*(.+?)\*/g;
    let lastIndex = 0;
    let match: RegExpExecArray | null;
    let i = 0;
    while ((match = regex.exec(text)) !== null) {
        if (match.index > lastIndex) {
            nodes.push(text.slice(lastIndex, match.index));
        }
        if (match[1] !== undefined) {
            nodes.push(
                <strong key={`${keyPrefix}-b-${i}`} className="font-semibold text-foreground">
                    {match[1]}
                </strong>,
            );
        } else if (match[2] !== undefined) {
            nodes.push(
                <code
                    key={`${keyPrefix}-c-${i}`}
                    className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em]"
                >
                    {match[2]}
                </code>,
            );
        } else if (match[3] !== undefined) {
            nodes.push(
                <a
                    key={`${keyPrefix}-a-${i}`}
                    href={match[4]}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="link-underline inline-flex items-center gap-0.5 text-primary"
                >
                    {match[3]}
                    <ExternalLink className="size-3" aria-hidden />
                </a>,
            );
        } else if (match[5] !== undefined) {
            nodes.push(
                <em key={`${keyPrefix}-i-${i}`} className="italic">
                    {match[5]}
                </em>,
            );
        }
        lastIndex = regex.lastIndex;
        i++;
    }
    if (lastIndex < text.length) {
        nodes.push(text.slice(lastIndex));
    }
    return nodes;
}

/** Parse a Markdown table row into trimmed cells. */
function parseTableRow(line: string): string[] {
    return line
        .replace(/^\s*\|/, "")
        .replace(/\|\s*$/, "")
        .split("|")
        .map((cell) => cell.trim());
}

const isTableSeparator = (line: string): boolean =>
    /^\s*\|?[\s:-]*-{3,}[\s:-|]*\|?\s*$/.test(line);

/** Lightweight Markdown renderer → React nodes. Handles the common subset. */
function Markdown({ content }: { content: string }): React.ReactElement {
    const lines = content.split(/\r?\n/);
    const blocks: React.ReactNode[] = [];
    let i = 0;
    let key = 0;

    while (i < lines.length) {
        const line = lines[i];

        // Code fence
        if (line.trim().startsWith("```")) {
            const lang = line.trim().slice(3).trim();
            const codeLines: string[] = [];
            i++;
            while (i < lines.length && !lines[i].trim().startsWith("```")) {
                codeLines.push(lines[i]);
                i++;
            }
            i++; // consume closing fence
            blocks.push(
                <pre
                    key={`code-${key++}`}
                    className="overflow-x-auto rounded-lg border bg-muted/40 p-4 text-sm"
                >
                    <code className={`font-mono ${lang ? `language-${lang}` : ""}`}>
                        {codeLines.join("\n")}
                    </code>
                </pre>,
            );
            continue;
        }

        // Headers
        const header = /^(#{1,6})\s+(.+?)\s*$/.exec(line);
        if (header) {
            const level = header[1].length;
            const text = header[2].replace(/[#*`]/g, "").trim();
            const id = slugify(text);
            const inner = renderInline(header[2], `h-${key}`);
            if (level === 1) {
                blocks.push(<h1 key={`h-${key++}`} id={id} className="mt-8 font-display text-3xl font-semibold tracking-tight">{inner}</h1>);
            } else if (level === 2) {
                blocks.push(<h2 key={`h-${key++}`} id={id} className="mt-10 border-b pb-2 font-display text-2xl font-semibold tracking-tight">{inner}</h2>);
            } else if (level === 3) {
                blocks.push(<h3 key={`h-${key++}`} id={id} className="mt-8 font-display text-xl font-semibold tracking-tight">{inner}</h3>);
            } else if (level === 4) {
                blocks.push(<h4 key={`h-${key++}`} id={id} className="mt-6 text-lg font-semibold">{inner}</h4>);
            } else {
                blocks.push(<h5 key={`h-${key++}`} id={id} className="mt-4 text-base font-semibold">{inner}</h5>);
            }
            i++;
            continue;
        }

        // Table: current line starts with | and next line is a separator
        if (line.trim().startsWith("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
            const headerCells = parseTableRow(line);
            i += 2; // skip header + separator
            const rows: string[][] = [];
            while (i < lines.length && lines[i].trim().startsWith("|")) {
                rows.push(parseTableRow(lines[i]));
                i++;
            }
            blocks.push(
                <div key={`tbl-${key++}`} className="my-4 overflow-x-auto rounded-lg border">
                    <table className="w-full text-sm">
                        <thead className="bg-muted/50">
                            <tr className="border-b text-left">
                                {headerCells.map((cell, ci) => (
                                    <th key={ci} className="px-4 py-2.5 font-semibold">
                                        {renderInline(cell, `th-${key}-${ci}`)}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((row, ri) => (
                                <tr key={ri} className="border-b last:border-0 hover:bg-accent/30">
                                    {row.map((cell, ci) => (
                                        <td key={ci} className="px-4 py-2.5 align-top">
                                            {renderInline(cell, `td-${key}-${ri}-${ci}`)}
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>,
            );
            continue;
        }

        // Blockquote
        if (line.trim().startsWith(">")) {
            const quoteLines: string[] = [];
            while (i < lines.length && lines[i].trim().startsWith(">")) {
                quoteLines.push(lines[i].replace(/^\s*>\s?/, ""));
                i++;
            }
            blocks.push(
                <blockquote
                    key={`bq-${key++}`}
                    className="my-4 border-l-4 border-primary/40 bg-muted/30 px-4 py-3 text-sm italic text-muted-foreground"
                >
                    {renderInline(quoteLines.join(" "), `bq-${key}`)}
                </blockquote>,
            );
            continue;
        }

        // Bullet list
        if (/^\s*[-*]\s+/.test(line)) {
            const items: string[] = [];
            while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
                items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
                i++;
            }
            blocks.push(
                <ul key={`ul-${key++}`} className="my-4 list-disc space-y-1.5 pl-6">
                    {items.map((item, ii) => (
                        <li key={ii}>{renderInline(item, `li-${key}-${ii}`)}</li>
                    ))}
                </ul>,
            );
            continue;
        }

        // Numbered list
        if (/^\s*\d+\.\s+/.test(line)) {
            const items: string[] = [];
            while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
                items.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
                i++;
            }
            blocks.push(
                <ol key={`ol-${key++}`} className="my-4 list-decimal space-y-1.5 pl-6">
                    {items.map((item, ii) => (
                        <li key={ii}>{renderInline(item, `oli-${key}-${ii}`)}</li>
                    ))}
                </ol>,
            );
            continue;
        }

        // Horizontal rule
        if (/^\s*([-*]){3,}\s*$/.test(line)) {
            blocks.push(<hr key={`hr-${key++}`} className="my-6 border-t" />);
            i++;
            continue;
        }

        // Blank line
        if (line.trim() === "") {
            i++;
            continue;
        }

        // Paragraph: gather consecutive non-blank, non-block lines
        const paraLines: string[] = [];
        while (
            i < lines.length &&
            lines[i].trim() !== "" &&
            !lines[i].trim().startsWith("```") &&
            !/^(#{1,6})\s+/.test(lines[i]) &&
            !lines[i].trim().startsWith(">") &&
            !/^\s*[-*]\s+/.test(lines[i]) &&
            !/^\s*\d+\.\s+/.test(lines[i]) &&
            !/^\s*([-*]){3,}\s*$/.test(lines[i]) &&
            !(
                lines[i].trim().startsWith("|") &&
                i + 1 < lines.length &&
                isTableSeparator(lines[i + 1])
            )
        ) {
            paraLines.push(lines[i]);
            i++;
        }
        blocks.push(
            <p key={`p-${key++}`} className="my-4 leading-relaxed text-foreground/90">
                {renderInline(paraLines.join(" "), `p-${key}`)}
            </p>,
        );
    }

    return <div className="guide-content">{blocks}</div>;
}

function GuideComponent() {
    const { t, i18n } = useTranslation();
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
                                {t("nav.guide")}
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
                                    <p className="eyebrow mb-3">{t("help.documentation")}</p>
                                    <nav className="space-y-1 border-l pl-3 text-sm">
                                        {toc.map((item) => (
                                            <button
                                                key={item.id}
                                                type="button"
                                                onClick={() => scrollToId(item.id)}
                                                className={
                                                    "block w-full text-left text-muted-foreground transition-colors hover:text-foreground " +
                                                    (item.level === 3 ? "pl-3" : "font-medium text-foreground/80")
                                                }
                                            >
                                                {item.text}
                                            </button>
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
