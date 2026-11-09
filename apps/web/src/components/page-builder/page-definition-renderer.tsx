/**
 * PageDefinitionRenderer — draws a published page definition on the public
 * site.
 *
 * The definition is authored in the Admin Page Builder and validated by the
 * server registry before publication. The renderer is still defensive: it
 * re-checks link schemes, sanitises rich text, ignores unknown component
 * types, and never honours a caller-supplied template, endpoint, or action
 * outside the fixed allowlist. Nothing here reads draft/published metadata or
 * an internal identifier — the payload is `{route, version, status,
 * definition}` only.
 */
import * as React from "react";
import { useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import DOMPurify from "dompurify";
import {
  Alert,
  Button,
  Card,
  Carousel,
  Col,
  Divider,
  Empty,
  Input,
  Row,
  Select,
  Skeleton,
  Space,
  Table,
  Tabs,
  Typography,
  type TableColumnsType,
} from "@/lib/antd";
import { listNews, ontologyApi, type OntologyRelationshipGraphResponse } from "@soymutdb/api-client";
import type { PageComponentNode, PageDefinitionV2 } from "@soymutdb/shared";
import { useReleaseId } from "../../lib/release-scope";
import { SITE_VARIANT } from "../../lib/site-variant";
import { assemblyStatisticsQueryOptions } from "../../lib/query-options";

const { Paragraph, Title, Text } = Typography;

const SAFE_EXTERNAL_RE = /^(https?:\/\/|mailto:|tel:)/i;
const INTERNAL_ROUTE_RE = /^\/(?!\/)[^\s]*$/;

/** Re-validate a stored href before it reaches the DOM. */
export function safeHref(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (/^(javascript|data|vbscript|file):/i.test(trimmed)) return null;
  if (SAFE_EXTERNAL_RE.test(trimmed) || INTERNAL_ROUTE_RE.test(trimmed)) return trimmed;
  return null;
}

function safeImageSrc(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return /^https?:\/\//i.test(trimmed) || INTERNAL_ROUTE_RE.test(trimmed)
    ? trimmed
    : null;
}

interface SafeLinkProps {
  href: unknown;
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

function SafeLink({ href, children, className, style }: SafeLinkProps) {
  const navigate = useNavigate();
  const safe = safeHref(href);
  if (!safe) return <span className={className} style={style}>{children}</span>;
  const internal = safe.startsWith("/");
  return (
    <a
      href={safe}
      className={className}
      style={style}
      {...(internal
        ? {
            onClick: (event: React.MouseEvent<HTMLAnchorElement>) => {
              if (
                event.defaultPrevented ||
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
              ) {
                return;
              }
              event.preventDefault();
              void Promise.resolve(navigate({ href: safe }));
            },
          }
        : { target: "_blank", rel: "noopener noreferrer" })}
    >
      {children}
    </a>
  );
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asStringList(value: unknown, max: number): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string").slice(0, max);
}

interface RenderNodeProps {
  node: PageComponentNode;
  index?: number;
}

function renderNode({ node, index }: RenderNodeProps): React.ReactNode {
  const key = `${node.type}-${index ?? 0}`;
  switch (node.type) {
    case "navigation":
      return <NavigationNode key={key} node={node} />;
    case "news_list":
      return <NewsListNode key={key} node={node} />;
    case "media_carousel":
      return <MediaCarouselNode key={key} node={node} />;
    case "resource_cards":
      return <ResourceCardsNode key={key} node={node} />;
    case "rich_text":
      return <RichTextNode key={key} node={node} />;
    case "tool_entries":
      return <ToolEntriesNode key={key} node={node} />;
    case "assembly_select":
      return <AssemblySelectNode key={key} node={node} />;
    case "gene_search_form":
      return <GeneSearchFormNode key={key} node={node} />;
    case "location_search_form":
      return <LocationSearchFormNode key={key} node={node} />;
    case "data_table":
      return <DataTableNode key={key} node={node} />;
    case "button":
      return <ButtonNode key={key} node={node} />;
    case "link":
      return <LinkNode key={key} node={node} />;
    case "notice":
      return <NoticeNode key={key} node={node} />;
    case "divider":
      return <Divider key={key} />;
    case "tabs":
      return <TabsNode key={key} node={node} />;
    case "columns":
      return <ColumnsNode key={key} node={node} />;
    case "jbrowse_launcher":
      return <JbrowseLauncherNode key={key} node={node} />;
    case "blast_launcher":
      return <BlastLauncherNode key={key} node={node} />;
    case "ontology_relationship_graph":
      return <OntologyGraphNode key={key} node={node} />;
    default:
      return null;
  }
}

function NavigationNode({ node }: { node: PageComponentNode }) {
  const title = asString(node.props.title);
  const items = Array.isArray(node.props.items) ? node.props.items : [];
  return (
    <nav className="flex flex-col gap-3" aria-label={title || "Page navigation"}>
      {title ? <Title level={4} style={{ margin: 0 }}>{title}</Title> : null}
      <Space size="middle" wrap>
        {items.map((item, i) => {
          if (typeof item !== "object" || item === null) return null;
          const entry = item as Record<string, unknown>;
          const label = asString(entry.label);
          if (!label) return null;
          return (
            <SafeLink key={i} href={entry.route} className="text-primary hover:underline">
              {label}
            </SafeLink>
          );
        })}
      </Space>
    </nav>
  );
}

function NewsListNode({ node }: { node: PageComponentNode }) {
  const { t } = useTranslation();
  const limit = Math.min(Math.max(asNumber(node.props.limit, 6), 1), 50);
  const news = useQuery({
    queryKey: ["page-definition-news", SITE_VARIANT, limit],
    queryFn: () => listNews(undefined, 1, limit),
    staleTime: 60_000,
  });

  if (news.isPending) return <Skeleton active paragraph={{ rows: 4 }} />;
  if (news.isError) return <Alert type="warning" showIcon message={t("pageBuilder.newsUnavailable", { defaultValue: "News is temporarily unavailable" })} />;
  const items = news.data?.items ?? [];
  if (items.length === 0) return <Empty description={t("pageBuilder.noNews", { defaultValue: "No news yet" })} />;

  return (
    <section className="flex flex-col gap-3">
      <Title level={4} style={{ margin: 0 }}>
        {t("nav.news", { defaultValue: "News" })}
      </Title>
      <div className="grid gap-3 md:grid-cols-2">
        {items.map((item) => {
          const title = item.title_zh || item.title_en;
          return (
            <Card key={item.id} size="small" hoverable>
              <SafeLink href={`/news/${encodeURIComponent(item.slug)}`} className="font-medium text-primary hover:underline">
                {title}
              </SafeLink>
              {item.published_at ? (
                <Paragraph type="secondary" style={{ margin: "4px 0 0", fontSize: 12 }}>
                  {item.published_at.slice(0, 10)}
                </Paragraph>
              ) : null}
            </Card>
          );
        })}
      </div>
    </section>
  );
}

function MediaCarouselNode({ node }: { node: PageComponentNode }) {
  const items = asStringList(node.props.items, 12);
  const images = items.map(safeImageSrc).filter((src): src is string => src !== null);
  if (images.length === 0) return null;
  return (
    <Carousel arrows dots={images.length > 1} autoplay={false}>
      {images.map((src, i) => (
        <div key={i}>
          <img
            src={src}
            alt=""
            style={{ width: "100%", maxHeight: 360, objectFit: "cover", borderRadius: 12 }}
          />
        </div>
      ))}
    </Carousel>
  );
}

function ResourceCardsNode({ node }: { node: PageComponentNode }) {
  const heading = asString(node.props.heading);
  const cards = Array.isArray(node.props.cards) ? node.props.cards.slice(0, 24) : [];
  if (cards.length === 0) return null;
  return (
    <section className="flex flex-col gap-3">
      {heading ? <Title level={4} style={{ margin: 0 }}>{heading}</Title> : null}
      <Row gutter={[16, 16]}>
        {cards.map((raw, i) => {
          if (typeof raw !== "object" || raw === null) return null;
          const card = raw as Record<string, unknown>;
          const title = asString(card.title);
          if (!title) return null;
          const description = asString(card.description);
          const image = safeImageSrc(card.image_url);
          return (
            <Col key={i} xs={24} sm={12} lg={8}>
              <Card
                size="small"
                hoverable
                cover={image ? <img src={image} alt="" style={{ height: 140, objectFit: "cover" }} /> : undefined}
              >
                <Card.Meta
                  title={<SafeLink href={card.href} className="text-primary hover:underline">{title}</SafeLink>}
                  description={description || undefined}
                />
              </Card>
            </Col>
          );
        })}
      </Row>
    </section>
  );
}

function RichTextNode({ node }: { node: PageComponentNode }) {
  const content = asString(node.props.content);
  if (!content) return null;
  const safe = DOMPurify.sanitize(content, { USE_PROFILES: { html: true } });
  return (
    <div
      className="page-definition-rich-text"
      // Server-sanitised at write time; DOMPurify re-sanitises at render time.
      dangerouslySetInnerHTML={{ __html: safe }}
    />
  );
}

const TOOL_LINKS: Record<string, { to: string; label: string }> = {
  gene: { to: "/search/genes", label: "Gene ID Search" },
  location: { to: "/search/location", label: "Position Search" },
  gbrowse: { to: "/browser", label: "JBrowse 2" },
  jbrowse: { to: "/browser", label: "JBrowse 2" },
  blast: { to: "/blast", label: "BLAST" },
  primer: { to: "/tools/primer", label: "Primer Design" },
  sequence: { to: "/tools/sequence", label: "Sequence Fetch" },
  expression: { to: "/expression", label: "Expression" },
  enrichment: { to: "/tools/enrichment", label: "GO / KEGG Enrichment" },
};

function ToolEntriesNode({ node }: { node: PageComponentNode }) {
  const navigate = useNavigate();
  const entries = asStringList(node.props.entries, 8);
  const resolved = entries.flatMap((entry) => {
    const link = TOOL_LINKS[entry.trim().toLowerCase()];
    return link ? [link] : [];
  });
  if (resolved.length === 0) return null;
  return (
    <Space size="middle" wrap>
      {resolved.map((entry) => (
        <Button key={entry.to} onClick={() => void Promise.resolve(navigate({ to: entry.to }))}>
          {entry.label}
        </Button>
      ))}
    </Space>
  );
}

function AssemblySelectNode({ node }: { node: PageComponentNode }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const releaseId = useReleaseId();
  const defaultAssembly = asString(node.props.default_assembly);
  const assemblies = useQuery(
    assemblyStatisticsQueryOptions({ releaseId, siteVariant: SITE_VARIANT }),
  );

  const options = React.useMemo(
    () => (assemblies.data ?? []).map((assembly) => ({
      value: assembly.name,
      label: `${assembly.name}${assembly.version ? ` (${assembly.version})` : ""}`,
    })),
    [assemblies.data],
  );

  if (assemblies.isPending) return <Skeleton.Input active />;
  if (assemblies.isError) {
    return <Alert type="warning" showIcon message={t("pageBuilder.assembliesUnavailable", { defaultValue: "Assemblies are temporarily unavailable" })} />;
  }

  return (
    <Select
      style={{ minWidth: 260 }}
      aria-label={t("pageBuilder.selectAssembly", { defaultValue: "Select a genome assembly" })}
      placeholder={t("pageBuilder.selectAssembly", { defaultValue: "Select a genome assembly" })}
      value={defaultAssembly || undefined}
      options={options}
      onChange={(value: string) =>
        void Promise.resolve(navigate({ to: "/browser", search: { assembly: value, locus: "" } }))
      }
    />
  );
}

function GeneSearchFormNode({ node }: { node: PageComponentNode }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [term, setTerm] = React.useState("");
  const title = asString(node.props.title);
  const submit = () => {
    const q = term.trim();
    void Promise.resolve(navigate({ to: "/search/genes", search: { q: q || undefined, run: Boolean(q) } }));
  };
  return (
    <section className="flex flex-col gap-2">
      {title ? <Title level={4} style={{ margin: 0 }}>{title}</Title> : null}
      <Space.Compact style={{ width: "100%", maxWidth: 560 }}>
        <Input
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          onPressEnter={submit}
          placeholder={t("search.genes.geneIdPlaceholder", { defaultValue: "Enter a gene ID" })}
          aria-label={title || t("nav.search", { defaultValue: "Search" })}
        />
        <Button type="primary" onClick={submit}>
          {t("ui.searchButton", { defaultValue: "Search" })}
        </Button>
      </Space.Compact>
    </section>
  );
}

function LocationSearchFormNode({ node }: { node: PageComponentNode }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [chromosome, setChromosome] = React.useState("");
  const [start, setStart] = React.useState("");
  const [end, setEnd] = React.useState("");
  const title = asString(node.props.title);
  const submit = () => {
    const startValue = Number(start);
    const endValue = Number(end);
    void Promise.resolve(navigate({
      to: "/search/location",
      search: {
        chromosome: chromosome.trim() || undefined,
        start: Number.isFinite(startValue) && start !== "" ? startValue : undefined,
        end: Number.isFinite(endValue) && end !== "" ? endValue : undefined,
        run: true,
      },
    }));
  };
  return (
    <section className="flex flex-col gap-2">
      {title ? <Title level={4} style={{ margin: 0 }}>{title}</Title> : null}
      <Space wrap>
        <Input
          value={chromosome}
          onChange={(event) => setChromosome(event.target.value)}
          placeholder={t("search.location.chromosome", { defaultValue: "Chromosome" })}
          aria-label={t("search.location.chromosome", { defaultValue: "Chromosome" })}
        />
        <Input
          value={start}
          onChange={(event) => setStart(event.target.value.replace(/[^\d]/g, ""))}
          placeholder={t("search.location.start", { defaultValue: "Start" })}
          aria-label={t("search.location.start", { defaultValue: "Start" })}
        />
        <Input
          value={end}
          onChange={(event) => setEnd(event.target.value.replace(/[^\d]/g, ""))}
          placeholder={t("search.location.end", { defaultValue: "End" })}
          aria-label={t("search.location.end", { defaultValue: "End" })}
        />
        <Button type="primary" onClick={submit}>
          {t("search.location.submit", { defaultValue: "Search" })}
        </Button>
      </Space>
    </section>
  );
}

function DataTableNode({ node }: { node: PageComponentNode }) {
  const { t } = useTranslation();
  const columns = asStringList(node.props.columns, 32);
  const tableColumns: TableColumnsType<Record<string, unknown>> = columns.map((column) => ({
    title: column,
    dataIndex: column,
    key: column,
  }));
  return (
    <Table
      size="small"
      columns={tableColumns}
      dataSource={[]}
      pagination={false}
      locale={{ emptyText: t("ui.noResults", { defaultValue: "No results found" }) }}
    />
  );
}

const ACTION_ROUTES: Record<string, string> = {
  open_jbrowse: "/browser",
  run_blast: "/blast",
  submit_gene_search: "/search/genes",
  submit_location_search: "/search/location",
};

function ButtonNode({ node }: { node: PageComponentNode }) {
  const navigate = useNavigate();
  const label = asString(node.props.label);
  const action = asString(node.props.action);
  const variant = asString(node.props.variant, "primary");
  const target = ACTION_ROUTES[action];
  const type = variant === "primary" ? "primary" : variant === "ghost" ? "text" : "default";
  return (
    <Button
      type={type}
      disabled={!target}
      onClick={target ? () => void Promise.resolve(navigate({ to: target })) : undefined}
    >
      {label || action || "Button"}
    </Button>
  );
}

function LinkNode({ node }: { node: PageComponentNode }) {
  const label = asString(node.props.label);
  if (!label) return null;
  return (
    <SafeLink
      href={node.props.href}
      className={
        node.props.variant === "button"
          ? "inline-flex rounded-md bg-primary px-4 py-2 text-primary-foreground hover:opacity-90"
          : "text-primary hover:underline"
      }
    >
      {label}
    </SafeLink>
  );
}

const NOTICE_TYPES = new Set(["info", "warning", "success", "error"]);

function NoticeNode({ node }: { node: PageComponentNode }) {
  const kind = asString(node.props.kind, "info");
  const type = (NOTICE_TYPES.has(kind) ? kind : "info") as "info" | "warning" | "success" | "error";
  const content = asString(node.props.content);
  if (!content) return null;
  return <Alert type={type} showIcon message={content} />;
}

function TabsNode({ node }: { node: PageComponentNode }) {
  const labels = asStringList(node.props.tabs, 10);
  const children = Array.isArray(node.children) ? node.children : [];
  const count = Math.max(labels.length, children.length);
  if (count === 0) return null;
  const items = Array.from({ length: count }, (_, i) => ({
    key: String(i),
    label: labels[i] ?? `Tab ${i + 1}`,
    children: children[i] ? renderNode({ node: children[i], index: i }) : null,
  }));
  return <Tabs items={items} />;
}

function ColumnsNode({ node }: { node: PageComponentNode }) {
  const count = Math.min(Math.max(asNumber(node.props.columns, 2), 1), 4);
  const children = Array.isArray(node.children) ? node.children : [];
  const span = Math.max(24 / count, 6);
  return (
    <Row gutter={[24, 24]}>
      {children.map((child, i) => (
        <Col key={i} xs={24} md={span}>
          {renderNode({ node: child, index: i })}
        </Col>
      ))}
    </Row>
  );
}

function JbrowseLauncherNode({ node }: { node: PageComponentNode }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const assembly = asString(node.props.assembly);
  const track = asString(node.props.track);
  return (
    <Button
      type="primary"
      onClick={() =>
        void Promise.resolve(navigate({
          to: "/browser",
          search: { assembly, locus: "", tracks: track ? [track] : undefined },
        }))
      }
    >
      {t("pageBuilder.openJbrowse", { defaultValue: "Open JBrowse 2" })}
    </Button>
  );
}

function BlastLauncherNode({ node }: { node: PageComponentNode }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <Button type="primary" onClick={() => void Promise.resolve(navigate({ to: "/blast" }))}>
      {t("pageBuilder.openBlast", { defaultValue: "Run BLAST" })}
      {asString(node.props.program) ? ` (${asString(node.props.program)})` : ""}
    </Button>
  );
}

function graphQueryOptions(ontology: string, iri: string, maxNodes: number, maxEdges: number) {
  return {
    queryKey: ["ontology-graph", ontology, iri, maxNodes, maxEdges],
    queryFn: () => ontologyApi.relationshipGraph({
      ontology,
      iri,
      max_nodes: maxNodes,
      max_edges: maxEdges,
    }),
    staleTime: 5 * 60_000,
    retry: false,
  };
}

function OntologyGraphNode({ node }: { node: PageComponentNode }) {
  const { t } = useTranslation();
  const ontology = asString(node.props.ontology);
  const iri = asString(node.props.iri);
  const maxNodes = Math.min(Math.max(asNumber(node.props.max_nodes, 24), 1), 50);
  const maxEdges = Math.min(Math.max(asNumber(node.props.max_edges, 32), 1), 100);
  const graph = useQuery({
    ...graphQueryOptions(ontology, iri, maxNodes, maxEdges),
    enabled: Boolean(ontology && iri),
  });

  if (!ontology || !iri) return null;
  if (graph.isPending) return <Skeleton active paragraph={{ rows: 6 }} />;
  if (graph.isError) {
    return <Alert type="warning" showIcon message={t("pageBuilder.graphUnavailable", { defaultValue: "Ontology graph is temporarily unavailable" })} />;
  }
  return <GraphSvg graph={graph.data} />;
}

const GRAPH_WIDTH = 640;
const GRAPH_HEIGHT = 420;
const GRAPH_RADIUS = 160;

function GraphSvg({ graph }: { graph: OntologyRelationshipGraphResponse }) {
  const { t } = useTranslation();
  const nodes = graph.nodes.slice(0, 50);
  const positions = new Map<string, { x: number; y: number }>();
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / Math.max(nodes.length, 1) - Math.PI / 2;
    positions.set(node.iri, {
      x: GRAPH_WIDTH / 2 + GRAPH_RADIUS * Math.cos(angle),
      y: GRAPH_HEIGHT / 2 + GRAPH_RADIUS * Math.sin(angle),
    });
  });
  const edges = graph.edges.slice(0, 100).filter(
    (edge) => positions.has(edge.source) && positions.has(edge.target),
  );

  return (
    <figure className="flex flex-col gap-2">
      <svg
        role="img"
        aria-label={t("pageBuilder.ontologyGraph", { defaultValue: "Ontology relationship graph" })}
        viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`}
        style={{ width: "100%", height: "auto" }}
      >
        <title>{graph.root_iri}</title>
        {edges.map((edge, i) => {
          const source = positions.get(edge.source);
          const target = positions.get(edge.target);
          if (!source || !target) return null;
          return (
            <line
              key={`e-${i}`}
              x1={source.x}
              y1={source.y}
              x2={target.x}
              y2={target.y}
              stroke="var(--border)"
              strokeWidth={1.2}
            >
              {edge.label ? <title>{edge.label}</title> : null}
            </line>
          );
        })}
        {nodes.map((node) => {
          const position = positions.get(node.iri);
          if (!position) return null;
          const label = node.label || node.iri.split("/").pop() || node.iri;
          return (
            <g key={node.iri}>
              <circle
                cx={position.x}
                cy={position.y}
                r={node.iri === graph.root_iri ? 10 : 6}
                fill={node.is_obsolete ? "var(--muted-foreground)" : "var(--primary)"}
                stroke="var(--background)"
                strokeWidth={2}
              >
                <title>{node.iri}</title>
              </circle>
              <text
                x={position.x}
                y={position.y - 12}
                textAnchor="middle"
                fontSize={10}
                fill="var(--foreground)"
              >
                {label.length > 22 ? `${label.slice(0, 21)}…` : label}
              </text>
            </g>
          );
        })}
      </svg>
      {graph.truncated ? (
        <Text type="secondary">
          {t("pageBuilder.graphTruncated", { defaultValue: "The graph was truncated to the configured node/edge limits." })}
        </Text>
      ) : null}
    </figure>
  );
}

const THEME_ATTRIBUTE = "data-page-theme";

export interface PageDefinitionRendererProps {
  definition: PageDefinitionV2;
  className?: string;
}

export function PageDefinitionRenderer({ definition, className }: PageDefinitionRendererProps) {
  return (
    <div
      className={["page-definition flex w-full flex-col gap-6", className].filter(Boolean).join(" ")}
      {...{ [THEME_ATTRIBUTE]: definition.theme_id }}
    >
      {renderNode({ node: definition.root })}
    </div>
  );
}