/**
 * AntdHome — public home page matching docs/01.pptx slide 1 (real geometry).
 *
 * Actual layout (from the pptx shape coordinates):
 *   - top area: 最新动态 news list on the LEFT (~40%), a 滚动照片 photo
 *     carousel on the RIGHT (~60%);
 *   - bottom area: 收索工具 heading + the five first-level search-tool
 *     directory buttons (基因 ID / 物理位置 / Gbrowse / 引物设计 / BLAST) laid
 *     out horizontally, each linking to its second-level directory.
 *
 * Ant Design (v6) is the only UI library used here (`@/lib/antd` facade + the
 * official @ant-design/icons). Colours come from the design tokens exposed as
 * CSS variables (src/index.css), so the page follows light/dark mode.
 */
import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useSiteContent } from "@/lib/site-content";
import {
  ArrowRightOutlined,
  EnvironmentOutlined,
  ExperimentOutlined,
  GlobalOutlined,
  IdcardOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Button,
  Card,
  Alert,
  Carousel,
  Col,
  Empty,
  Input,
  List,
  Row,
  Typography,
} from "@/lib/antd";
import { FluidGradient } from "../fluids/fluid-gradient";
import { useAnimation } from "@/lib/animation-context";
import { RenderNode } from "../../page-builder/renderer";
import { getFeaturedNews, type NewsSummary } from "@soymutdb/api-client";
import { formatDate } from "../../lib/format";
import { NEWS_FEATURED_KEY } from "../news-carousel";
import { pickNewsTitle } from "../news-card";
import type { PageComponentNode } from "@soymutdb/shared";

const { Title, Paragraph, Text } = Typography;

/** Science-green fluid palette for the hero photo carousel slides. */
const HERO_PALETTES: string[][] = [
  ["#052a1f", "#0d4a37", "#1b7a52", "#2f9e6b", "#0c3326"],
  ["#171a3a", "#1a3870", "#2d5f9e", "#4a8ac4", "#0d1f4a"],
  ["#0f2b1f", "#0d4a37", "#1b6b4a", "#3f8f65", "#0a2b1a"],
];

const HERO_SLIDES = [
  {
    eyebrowKey: "home.heroEyebrow",
    eyebrow: "SOYMUTDB · MULTI-SPECIES",
    titleKey: "home.heroTitle",
    title: "探索多物种突变的未知疆域",
    subKey: "home.heroSubtitle",
    sub: "新一代多物种突变数据库，从基因组到表型一站探索。",
  },
  {
    eyebrowKey: "home.heroEyebrow",
    eyebrow: "SOYMUTDB · MUTATION",
    titleKey: "home.heroSlide2",
    title: "从染色体到全局表型",
    subKey: "home.heroSlide2Desc",
    sub: "覆盖多物种参考基因组与突变集合，支持基因、位点、BLAST 多维检索。",
  },
  {
    eyebrowKey: "home.heroEyebrow",
    eyebrow: "SOYMUTDB · JBROWSE 2",
    titleKey: "home.heroSlide3",
    title: "突变特征一览无余",
    subKey: "home.heroSlide3Desc",
    sub: "以表格与可视化呈现染色体、突变类型、基因位点与 JBrowse 2 跳转。",
  },
];

interface ToolEntry {
  key: string;
  labelKey: string;
  label: string;
  descKey: string;
  desc: string;
  route: string;
  icon: React.ReactNode;
}

// Slide 1 directory order: 基因 ID / 物理位置 / Gbrowse / 引物设计 / BLAST.
const TOOL_ENTRIES: ToolEntry[] = [
  { key: "gene", labelKey: "home.toolGeneLabel", label: "基因 ID 检索", descKey: "home.toolGeneDesc", desc: "按基因号查询突变", route: "/search/genes", icon: <IdcardOutlined /> },
  { key: "location", labelKey: "home.toolLocationLabel", label: "物理位置检索", descKey: "home.toolLocationDesc", desc: "按染色体与位点查询", route: "/search/location", icon: <EnvironmentOutlined /> },
  { key: "gbrowse", labelKey: "home.toolGbrowseLabel", label: "JBrowse 2", descKey: "home.toolGbrowseDesc", desc: "在 JBrowse 2 中浏览基因组", route: "/search/gbrowse", icon: <GlobalOutlined /> },
  { key: "primer", labelKey: "home.toolPrimerLabel", label: "引物设计", descKey: "home.toolPrimerDesc", desc: "设计并检查引物", route: "/search/primer", icon: <ExperimentOutlined /> },
  { key: "blast", labelKey: "home.toolBlastLabel", label: "BLAST 比对", descKey: "home.toolBlastDesc", desc: "序列比对检索同源", route: "/blast", icon: <ThunderboltOutlined /> },
];

const DATABASE_ENTRIES = [
  { key: "mutants", route: "/mutants", label: "突变体", description: "浏览已发布的突变体记录", search: { mutagen: "" } },
  { key: "genes", route: "/genes", label: "基因", description: "按基因与组装版本筛选", search: { q: "", chromosome: "", biotype: "", page: 1, sort_by: "gene_id", sort_dir: "asc" as const } },
  { key: "variants", route: "/variants", label: "变异", description: "按染色体、类型与影响筛选", search: { chromosome: "", variant_type: "" as const, impact: "" as const, mutant_line_id: "", cursor: undefined } },
] as const;

function LatestNewsPanel() {
  const { t, i18n } = useTranslation();
  const query = useQuery({
    queryKey: NEWS_FEATURED_KEY,
    queryFn: getFeaturedNews,
    staleTime: 60 * 1000,
  });

  if (query.isPending) {
    return <div className="flex min-h-24 items-center justify-center" role="status"><span className="sr-only">{t("common.loading", { defaultValue: "Loading" })}</span><span className="animate-pulse text-sm text-muted-foreground">{t("common.loading", { defaultValue: "Loading" })}</span></div>;
  }

  if (query.isError) {
    return <Alert type="error" showIcon message={t("home.newsUnavailable", { defaultValue: "最新动态暂不可用" })} description={t("home.newsRetry", { defaultValue: "请稍后重试，当前没有使用演示数据替代。" })} />;
  }

  const items: NewsSummary[] = query.data?.featured.slice(0, 5) ?? [];
  return (
    <List
      dataSource={items}
      split
      locale={{ emptyText: <Empty description={t("home.noNews", { defaultValue: "暂无已发布新闻" })} /> }}
      renderItem={(item) => (
        <List.Item>
          <List.Item.Meta
            title={
              <Link to="/news/$slug" params={{ slug: item.slug }} className="home-news-link" style={{ color: "var(--foreground)" }}>
                {pickNewsTitle(item, i18n.language)}
              </Link>
            }
            description={
              <span className="text-xs text-muted-foreground">
                {item.category ? `${item.category} · ` : ""}{item.published_at ? formatDate(item.published_at) : t("home.newsMeta", { defaultValue: "最新发布" })}
              </span>
            }
          />
        </List.Item>
      )}
    />
  );
}

interface AntdHomeProps {
  resourceCards?: PageComponentNode;
  /** Demo/dev may show the documented legacy shell; production must not. */
  allowLegacyResourceFallback?: boolean;
  resourceDefinitionError?: boolean;
}

export function AntdHome({
  resourceCards,
  allowLegacyResourceFallback = false,
  resourceDefinitionError = false,
}: AntdHomeProps) {
  const { t } = useTranslation();
  const { get } = useSiteContent();
  const heroImage = get("hero.image", "");
  const navigate = useNavigate();
  const { reduced } = useAnimation();

  const goSearch = () => navigate({ to: "/search", search: { q: undefined } });
  const [heroQuery, setHeroQuery] = React.useState("");
  const runHeroSearch = (term: string) => navigate({ to: "/search", search: { q: term.trim() || undefined } });

  return (
    <div data-testid="antd-home">
      {/* ---------------------------------------------------------------- */}
      {/* HERO (clean): brand intro + search. No heavy gradient/CTA.        */}
      {/* ---------------------------------------------------------------- */}
      <section className="border-b border-border/60 bg-background">
        <div className="container-prose py-14 text-center md:py-20">
          <Text className="block text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            {get("hero.eyebrow", t("home.heroEyebrow", { defaultValue: "SOYMUTDB · MULTI-SPECIES" }))}
          </Text>
          <Title level={1} style={{ margin: "18px 0 14px", color: "var(--foreground)", fontSize: "clamp(2rem, 4.5vw, 3rem)", lineHeight: 1.15, fontWeight: 700 }}>
            {get("hero.title", t("home.heroTitle", { defaultValue: "探索多物种突变的未知疆域" }))}
          </Title>
          <Paragraph style={{ maxWidth: "58ch", margin: "0 auto", color: "var(--muted-foreground)", fontSize: "clamp(1rem, 1.5vw, 1.1rem)", lineHeight: 1.7 }}>
            {get("hero.subtitle", t("home.heroSubtitle", { defaultValue: "新一代多物种突变数据库，从基因组到表型一站探索。" }))}
          </Paragraph>
          <div role="search" className="mx-auto mt-8 flex w-full max-w-2xl flex-wrap items-center gap-2.5">
            <Input
              size="large"
              value={heroQuery}
              onChange={(e) => setHeroQuery(e.target.value)}
              onPressEnter={() => runHeroSearch(heroQuery)}
              placeholder={get("hero.searchPlaceholder", t("home.searchPlaceholder", { defaultValue: "搜索基因、变异、突变系…" }))}
              prefix={<SearchOutlined style={{ color: "var(--muted-foreground)" }} />}
              style={{ flex: 1, minWidth: 220 }}
              aria-label={get("hero.searchPlaceholder", t("home.searchPlaceholder", { defaultValue: "搜索基因、变异、突变系…" }))}
            />
            <Button type="primary" size="large" onClick={() => runHeroSearch(heroQuery)}>
              {t("home.searchButton", { defaultValue: "搜索" })}
            </Button>
          </div>
          {heroImage ? (
            <div className="mx-auto mt-10 aspect-[16/9] w-full max-w-3xl overflow-hidden rounded-2xl border border-border/60 shadow-sm">
              <img
                src={heroImage}
                alt={t("home.heroTitle", { defaultValue: "探索多物种突变的未知疆域" })}
                loading="lazy"
                className="h-full w-full object-cover"
              />
            </div>
          ) : null}
        </div>
      </section>

      <section className="border-b border-border/60 bg-muted/20" data-testid="database-entrypoints">
        <div className="container-prose py-10 md:py-12">
          <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
            <div>
              <Text className="eyebrow">{t("home.databaseEyebrow", { defaultValue: "SOYMUTDB DATABASE" })}</Text>
              <Title level={2} style={{ margin: "8px 0 0", fontWeight: 700 }}>
                {t("home.databaseTitle", { defaultValue: "生物信息学数据库" })}
              </Title>
            </div>
            <Link to="/search" className="home-section-link shrink-0 text-primary" style={{ fontWeight: 500 }}>
              {t("home.databaseSearch", { defaultValue: "查询数据库" })} →
            </Link>
          </div>
          <Row gutter={[20, 20]}>
            {DATABASE_ENTRIES.map((entry) => (
              <Col key={entry.key} xs={24} md={8}>
                <Link
                  to={entry.route}
                  search={entry.search}
                  className="block h-full rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Card className="h-full rounded-xl border border-border bg-card shadow-sm transition-colors hover:border-primary/40">
                    <Text strong className="block text-base text-foreground">{t(`home.database.${entry.key}`, { defaultValue: entry.label })}</Text>
                    <Paragraph className="mb-0 mt-1 text-sm text-muted-foreground">{t(`home.database.${entry.key}Description`, { defaultValue: entry.description })}</Paragraph>
                  </Card>
                </Link>
              </Col>
            ))}
          </Row>
        </div>
      </section>

      {/* ---------------------------------------------------------------- */}
      {/* TOP: 最新动态 (left) + 滚动照片 carousel (right).                   */}
      {/* ---------------------------------------------------------------- */}
      <div className="container-prose pb-6 pt-10 md:pb-8 md:pt-14">
        <Row gutter={[32, 32]} align="stretch">
          {/* Latest news — 5 titles linking to /news. */}
          <Col xs={24} lg={9} className="flex flex-col">
            <div className="mb-3 flex items-baseline justify-between gap-3">
              <Title level={3} className="font-bold" style={{ margin: 0 }}>
                {t("home.latestNews", { defaultValue: "最新动态" })}
              </Title>
              <Link to="/news" search={{ category: undefined, page: undefined }} className="home-section-link shrink-0 text-primary" style={{ fontWeight: 500 }}>
                {t("home.openTool", { defaultValue: "进入" })} →
              </Link>
            </div>
            <Card className="flex-1 rounded-xl border border-border bg-card shadow-sm" styles={{ body: { padding: "4px 20px" } }}>
              <LatestNewsPanel />
            </Card>
          </Col>

          {/* Photo carousel (滚动照片) — 3-6 brand slides. */}
          <Col xs={24} lg={15} className="flex flex-col">
            <div className="flex-1">
              <Carousel autoplay autoplaySpeed={5200} effect="fade" className="h-full">
                {HERO_SLIDES.map((slide, i) => (
                  <div key={slide.titleKey} className="h-full">
                    <FluidGradient
                      reduced={reduced}
                      colors={HERO_PALETTES[i % HERO_PALETTES.length]}
                      style={{ minHeight: 340, height: "100%", borderRadius: "var(--radius-xl)" }}
                    >
                      <div
                        style={{
                          position: "relative",
                          zIndex: 1,
                          padding: "clamp(28px, 4vw, 52px)",
                        }}
                      >
                        <Text style={{ color: "rgba(255,255,255,0.72)", letterSpacing: "0.16em", fontSize: 11, textTransform: "uppercase", fontWeight: 600 }}>
                          {t(slide.eyebrowKey, { defaultValue: slide.eyebrow })}
                        </Text>
                        <Title level={2} style={{ color: "#fff", margin: "14px 0 10px", lineHeight: 1.15, textShadow: "0 2px 20px rgba(0,0,0,0.3)" }}>
                          {t(slide.titleKey, { defaultValue: slide.title })}
                        </Title>
                        <Paragraph style={{ color: "rgba(255,255,255,0.86)", fontSize: 15, maxWidth: "52ch", lineHeight: 1.7 }}>
                          {t(slide.subKey, { defaultValue: slide.sub })}
                        </Paragraph>
                        <Button type="primary" onClick={goSearch} style={{ marginTop: 8 }}>
                          {t("home.heroPrimary", { defaultValue: "开始探索" })} <ArrowRightOutlined />
                        </Button>
                      </div>
                    </FluidGradient>
                  </div>
                ))}
              </Carousel>
            </div>
          </Col>
        </Row>
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* BOTTOM: 收索工具 — five first-level directory buttons in a row.    */}
      {/* ---------------------------------------------------------------- */}
      <div className="container-prose pb-20 pt-4 md:pt-6">
        <div className="mb-5 flex items-baseline justify-between gap-3">
          <Title level={3} style={{ margin: 0, fontWeight: 700 }}>
            {t("home.featuredTools", { defaultValue: "搜索工具" })}
          </Title>
          <Link to="/search" className="home-section-link shrink-0 text-primary" style={{ fontWeight: 500 }}>
            {t("home.openTool", { defaultValue: "进入" })} →
          </Link>
        </div>

        <Row gutter={[20, 20]}>
          {TOOL_ENTRIES.map((tool) => {
            const label = get(`tool.${tool.key}.label`, t(tool.labelKey, { defaultValue: tool.label }));
            const desc = get(`tool.${tool.key}.desc`, t(tool.descKey, { defaultValue: tool.desc }));
            const image = get(`tool.${tool.key}.image`, "");
            return (
              <Col key={tool.key} xs={24} sm={12} lg={{ flex: 1 }}>
                <Link
                  to={tool.route}
                  className="block h-full rounded-xl outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Card
                    className="h-full rounded-xl border border-border bg-card shadow-sm transition-colors hover:border-primary/40"
                    styles={{ body: { padding: 18, height: "100%" } }}
                  >
                    <div className="flex items-center gap-3.5">
                      <div className="flex h-11 w-11 flex-none items-center justify-center overflow-hidden rounded-lg bg-accent text-accent-foreground">
                        {image ? (
                          <img src={image} alt={label} loading="lazy" className="h-full w-full object-cover" />
                        ) : (
                          tool.icon
                        )}
                      </div>
                      <div className="min-w-0">
                        <Text strong className="block text-[15px] text-foreground">
                          {label}
                        </Text>
                        <Paragraph className="mb-0 mt-1 text-[13px] leading-5 text-muted-foreground">
                          {desc}
                        </Paragraph>
                      </div>
                    </div>
                  </Card>
                </Link>
              </Col>
            );
          })}
        </Row>
      </div>

      {/* Resource guide is a published `resource_cards` component supplied by
          the page definition. The legacy static visual shell is retained only
          when an older published definition has not yet supplied this node. */}
      <div className="container-prose pb-24 pt-2">
        {resourceCards ? <RenderNode node={resourceCards} /> : resourceDefinitionError ? (
          <Alert
            type="error"
            showIcon
            message={t("home.resourceUnavailable", { defaultValue: "资源导览暂不可用" })}
            description={t("home.resourceUnavailableDetail", { defaultValue: "发布的 Page Builder 内容无法从 API 获取，未使用演示内容替代。" })}
          />
        ) : allowLegacyResourceFallback ? (
          <section data-testid="resource-cards-fallback">
            <Title level={3} style={{ margin: "0 0 18px", fontWeight: 700 }}>
              {t("home.resourceNav", { defaultValue: "资源导览" })}
            </Title>
            <Row gutter={[20, 20]}>
              {[
                { key: "downloads", route: "/downloads", label: "数据下载", desc: "下载参考基因组、变异与注释数据" },
                { key: "guide", route: "/guide", label: "使用指南", desc: "快速上手与检索帮助" },
                { key: "publications", route: "/publications", label: "文献 / 出版物", desc: "SoyMutDB 相关文献" },
              ].map((r) => (
                <Col key={r.key} xs={24} sm={12} lg={8}>
                  <Link to={r.route} className="block h-full rounded-xl outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring">
                    <Card className="h-full rounded-xl border border-border bg-card shadow-sm transition-colors hover:border-primary/40">
                      <Text strong style={{ display: "block", fontSize: 15, color: "var(--foreground)" }}>{r.label}</Text>
                      <Paragraph style={{ margin: "4px 0 0", color: "var(--muted-foreground)", fontSize: 13, lineHeight: 1.5 }}>{r.desc}</Paragraph>
                    </Card>
                  </Link>
                </Col>
              ))}
            </Row>
          </section>
        ) : (
          <Empty description={t("home.resourceUnavailable", { defaultValue: "暂无可用资源导览" })} />
        )}
      </div>
    </div>
  );
}

export default AntdHome;
